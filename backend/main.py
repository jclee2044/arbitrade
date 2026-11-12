"""Local FastAPI transport for Arbitrade."""

import asyncio
import json
import os
import sqlite3
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from backend.paper import PaperBroker, RequestConflict
from backend.decisions import DecisionService
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Response

from backend.history import history_response
from backend.indicators import with_averages, validate_windows, DEFAULT_SHORT, DEFAULT_LONG, indicator_types, configured_indicators
from backend.indicator_store import IndicatorStore, DEFAULT_CONFIG_DATABASE

from backend.replay import Replay, selections
from backend.live import LiveFeed
from backend.observations import DEFAULT_DATABASE
from backend.timeframes import TIMEFRAMES


@asynccontextmanager
async def lifespan(app):
    # Backend only: existing process environment takes precedence; never log values.
    load_dotenv(Path(__file__).resolve().parent / '.env', override=False, interpolate=False)
    app.state.indicator_store = IndicatorStore(os.environ.get('ARBITRADE_CONFIG_DATABASE', str(DEFAULT_CONFIG_DATABASE)))
    app.state.feed = LiveFeed(Path(os.environ.get('ARBITRADE_DATABASE', str(DEFAULT_DATABASE))))
    setup_paper(app)
    if os.environ.get('ARBITRADE_LIVE_FEED', 'on').lower() not in {'off', '0', 'false'}:
        await app.state.feed.start()
    else:
        app.state.feed.status = 'disabled'
    try:
        yield
    finally:
        await app.state.feed.stop()


app = FastAPI(title="Arbitrade", lifespan=lifespan)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/history")
def history(
    symbol: str = 'AAPL',
    timeframe: Literal['1m', '5m', '15m', '30m', '1h', '1d', '1w', '1mo'] = '1m',
    as_of: datetime | None = None,
    source: Literal['sample', 'observations'] = 'sample',
    calendar: str | None = None,
    include_status: bool = False,
    short_window: int = DEFAULT_SHORT,
    long_window: int = DEFAULT_LONG,
):
    try:
        result = history_response(symbol, timeframe, as_of=as_of, source=source, calendar=calendar,
                                  database=app.state.feed.database,
                                  short_window=short_window, long_window=long_window)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return named_indicators(result, symbol, timeframe) if include_status else result['candles']


@app.websocket('/api/live')
async def live(websocket: WebSocket, symbol: str = 'AAPL', timeframe: str = '1m',
               short_window: int = DEFAULT_SHORT, long_window: int = DEFAULT_LONG):
    await websocket.accept()
    if symbol != 'AAPL' or timeframe not in TIMEFRAMES:
        await websocket.send_json({'type': 'error', 'error': 'Choose AAPL and a supported timeframe'})
        await websocket.close(code=1008)
        return
    feed = websocket.app.state.feed
    previous = {}
    try:
        validate_windows(short_window, long_window)
        snapshot = with_averages(await asyncio.to_thread(feed.snapshot, timeframe), short_window, long_window)
        snapshot = named_indicators(snapshot, symbol, timeframe)
        await websocket.send_json(snapshot)
        previous = {c['timestamp']: (c, s) for c, s in zip(snapshot['candles'], snapshot['coverage'])}
        while True:
            # A periodic snapshot also advances completion without a new quote
            # and reports upstream loss independently of the browser socket.
            await asyncio.sleep(1)
            snapshot = with_averages(await asyncio.to_thread(feed.snapshot, timeframe), short_window, long_window)
            snapshot = named_indicators(snapshot, symbol, timeframe)
            current = {c['timestamp']: (c, s) for c, s in zip(snapshot['candles'], snapshot['coverage'])}
            if previous.keys() - current.keys():
                await websocket.send_json(snapshot)
            else:
                for timestamp, (candle, completion) in current.items():
                    if previous.get(timestamp) != (candle, completion):
                        await websocket.send_json({
                            'type': 'candle', 'symbol': symbol, 'interval': timeframe,
                            'source': snapshot['source'], 'candle': candle,
                            'completion': completion, 'feed': snapshot['feed'],
                            'moving_averages': snapshot['moving_averages'],
                            'indicators': snapshot['indicators'],
                            'presets': snapshot['presets'],
                        })
            await websocket.send_json({
                'type': 'status', 'symbol': symbol, 'interval': timeframe,
                'source': snapshot['source'], 'feed': snapshot['feed'],
                'moving_averages': snapshot['moving_averages'],
                'indicators': snapshot['indicators'],
                'presets': snapshot['presets'],
            })
            previous = current
    except (WebSocketDisconnect, OSError):
        pass
    except (ValueError, RuntimeError) as error:
        await websocket.send_json({'type': 'error', 'error': str(error)})
        await websocket.close(code=1011)


@app.get('/api/replay/selections')
def replay_selections():
    return selections(app.state.feed.database)


@app.websocket('/api/replay')
async def replay(websocket: WebSocket, symbol: str, start: str, end: str,
                 timeframe: str = '1m', calendar: str | None = None,
                 short_window: int = DEFAULT_SHORT, long_window: int = DEFAULT_LONG):
    await websocket.accept()
    session = None
    try:
        session = Replay(websocket.app.state.feed.database, symbol, start, end, timeframe, calendar,
                         short_window=short_window, long_window=long_window)
        account_id = websocket.app.state.paper.create_account('replay', now=session.start)
        websocket.app.state.paper_replays[account_id] = session
        initial = named_indicators(session.snapshot(), symbol, timeframe)
        initial['paper_account_id'] = account_id
        await websocket.send_json(initial)
        while True:
            command = await websocket.receive_json()
            if command == {'action': 'next'}:
                before = session.position
                snapshot = session.step()
                if session.position > before:
                    row = session.events[session.position-1]
                    first = session.connection.execute('SELECT MIN(id) FROM receipts WHERE observation_id=?', (row[2],)).fetchone()[0]
                    # Complete bars value the prior holding before this receipt's fill.
                    minute_snapshot = session.minute_snapshot()
                    websocket.app.state.paper.mark_completed(account_id, minute_snapshot,
                        event_time=session.evaluation, receipt_id=row[0])
                    websocket.app.state.paper.observe(account_id, dict(receipt_id=row[0], observation_id=row[2],
                        received_at_utc=row[1], source_time_utc=row[6], payload=json.loads(row[7]),
                        supersedes=row[8], repeat=row[0] != first))
            elif command == {'action': 'refresh'}:
                snapshot = session.snapshot()
            else:
                raise ValueError('Expected next or refresh replay action')
            snapshot = named_indicators(snapshot, symbol, timeframe)
            snapshot['paper_account_id'] = account_id
            await websocket.send_json(snapshot)
    except WebSocketDisconnect:
        pass
    except (ValueError, RuntimeError, OSError) as error:
        await websocket.send_json({'type': 'error', 'error': str(error)})
        await websocket.close(code=1008)
    finally:
        if session:
            if 'account_id' in locals():
                websocket.app.state.paper_replays.pop(account_id, None)
            session.close()


class IndicatorCreate(BaseModel):
    symbol: str = 'AAPL'
    timeframe: str = '1m'
    name: str
    type: str
    settings: dict


def named_indicators(snapshot, symbol, timeframe):
    store = app.state.indicator_store
    return dict(snapshot, indicators=configured_indicators(snapshot, store.list(symbol, timeframe)),
                presets=configured_indicators(snapshot, store.presets(symbol, timeframe)))


@app.get('/api/indicators/types')
def available_indicator_types():
    return indicator_types()


class PresetSelection(BaseModel):
    symbol: str
    timeframe: str
    enabled: bool


@app.get('/api/indicator-presets')
def active_presets(symbol: str = 'AAPL', timeframe: str = '1m'):
    try:
        return app.state.indicator_store.presets(symbol, timeframe)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.put('/api/indicator-presets/{kind}/{period}')
def select_preset(kind: str, period: int, selection: PresetSelection):
    try:
        return app.state.indicator_store.set_preset(selection.symbol, selection.timeframe, kind, period, selection.enabled)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get('/api/indicators')
def saved_indicators(symbol: str = 'AAPL', timeframe: str = '1m'):
    try:
        return app.state.indicator_store.list(symbol, timeframe)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post('/api/indicators', status_code=201)
def create_indicator(configuration: IndicatorCreate):
    try:
        return app.state.indicator_store.create(configuration.symbol, configuration.timeframe,
                                                configuration.name, configuration.type, configuration.settings)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=409, detail='An indicator with this name already exists on this chart') from error


class IndicatorSettings(BaseModel):
    settings: dict


@app.patch('/api/indicators/{identifier}')
def update_indicator(identifier: int, configuration: IndicatorSettings):
    try:
        return app.state.indicator_store.update_settings(identifier, configuration.settings)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


# Shared initialization also used by disposable fixture server lifespans.
def setup_paper(application):
    broker = PaperBroker(application.state.indicator_store.path, application.state.feed.database,
                         clock=getattr(application.state, 'paper_clock', None),
                         order_size=int(os.environ.get('ARBITRADE_PAPER_ORDER_SIZE', '1')))
    broker.create_account('live')
    application.state.paper = broker
    application.state.paper_replays = {}
    application.state.feed.on_record = broker.catch_up_live
    application.state.decisions = DecisionService(broker.path, broker.market, broker,
        provider=getattr(application.state, 'decision_provider', None))
    from backend.automation import AutomationService
    application.state.automation=AutomationService(broker,application.state.decisions,application.state.indicator_store)
    application.state.feed.on_record=application.state.automation.tick
    application.state.automation.tick()


class PaperAction(BaseModel):
    account_id: str = 'live'
    request_id: str
    action: str
    symbol: str = 'AAPL'
    quantity: Any = None


@app.get('/api/paper/account')
def paper_account(account_id: str = 'live'):
    try:
        if account_id == 'live':
            app.state.paper.catch_up_live()
        return app.state.paper.snapshot(account_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post('/api/paper/actions')
async def paper_action(request: PaperAction):
    try:
        broker = app.state.paper
        session = app.state.paper_replays.get(request.account_id)
        if request.account_id == 'live':
            broker.catch_up_live()
        result = broker.execute(request.account_id, request_id=request.request_id,
            action=request.action, symbol=request.symbol, quantity=request.quantity,
            submitted_at=session.evaluation if session else None,
            after_receipt_id=(session.current or {}).get('receipt_id', 0) if session else broker.market_cursor(),
            accept_new=request.account_id == 'live' or session is not None)
        return dict(result=result, state=broker.snapshot(request.account_id))
    except RequestConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


class DecisionSnapshotRequest(BaseModel):
    account_id: str = 'live'
    symbol: str = 'AAPL'
    interval: str = '1m'
    candle_timestamp: str
    short_window: int = 20
    long_window: int = 50
    chart_start: str | None = None
    chart_end: str | None = None


class DecisionRequest(BaseModel):
    snapshot_id: str | None = None
    capture: dict | None = None


@app.post('/api/decision-snapshots', status_code=201)
async def create_decision_snapshot(request: DecisionSnapshotRequest):
    try:
        return app.state.decisions.freeze(**request.model_dump(),
            instances=app.state.indicator_store.chart_indicators(request.symbol,request.interval),
            replay=app.state.paper_replays.get(request.account_id))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get('/api/decision-snapshots/{snapshot_id}')
def get_decision_snapshot(snapshot_id: str, include_records: bool = False):
    try:
        return app.state.decisions.get_snapshot(snapshot_id, evidence=include_records)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post('/api/decisions')
async def create_decision(request: DecisionRequest):
    if request.capture is not None:
        from backend.chart_decisions import decide_image
        return await decide_image(app.state.decisions,request.snapshot_id,request.capture)
    return await app.state.decisions.decide(request.snapshot_id)


@app.get('/api/decision-questions/chart')
def chart_questions():
    from backend.chart_decisions import questions
    return questions()


@app.get('/api/decisions/{decision_id}/image')
def decision_image(decision_id: str):
    from contextlib import closing
    with closing(sqlite3.connect(app.state.decisions.path)) as c:
        row=c.execute('SELECT png FROM decision_images WHERE decision_id=?',(decision_id,)).fetchone()
    if not row or not row[0]:raise HTTPException(status_code=404,detail='No saved chart capture')
    return Response(row[0],media_type='image/png',headers={'Cache-Control':'no-store'})


@app.get('/api/decisions/{decision_id}')
def get_decision(decision_id: str):
    try:
        return app.state.decisions.get_decision(decision_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


class AutomationStart(BaseModel):
    account_id: str='live'
    symbol: str='AAPL'
    interval: str='1m'
    short_window: int=20
    long_window: int=50


class AutomationClaim(BaseModel):
    run_id: str
    candle_timestamp: str


class AutomationCapture(BaseModel):
    capture: dict | None=None
    capture_error: str | None=None


@app.get('/api/paper/automation')
def automation_state(run_id: str | None=None):
    return app.state.automation.state(run_id)


@app.post('/api/paper/automation/start')
def automation_start(request: AutomationStart):
    try:return app.state.automation.start(**request.model_dump())
    except ValueError as e:raise HTTPException(status_code=422,detail=str(e)) from e


@app.post('/api/paper/automation/{run_id}/stop')
def automation_stop(run_id: str):
    return app.state.automation.stop(run_id)


@app.post('/api/paper/automation/claim')
def automation_claim(request: AutomationClaim):
    try:return app.state.automation.claim(request.run_id,request.candle_timestamp)
    except ValueError as e:raise HTTPException(status_code=422,detail=str(e)) from e


@app.post('/api/paper/automation/attempts/{attempt_id}/analyze')
async def automation_analyze(attempt_id: str,request: AutomationCapture):
    try:return await app.state.automation.analyze(attempt_id,**request.model_dump())
    except ValueError as e:raise HTTPException(status_code=422,detail=str(e)) from e


@app.post('/api/paper/automation/attempts/{attempt_id}/apply')
def automation_apply(attempt_id: str):
    try:return app.state.automation.apply(attempt_id)
    except ValueError as e:raise HTTPException(status_code=422,detail=str(e)) from e


class VoiceOffer(BaseModel):
    model_config={'extra':'forbid'}
    decision_id: str
    sdp: str


@app.get('/api/voice/decisions')
def voice_decisions():
    from backend.voice import records
    return records(app.state.paper.path)


@app.get('/api/voice/decisions/{decision_id}')
def voice_decision(decision_id: str):
    from backend.voice import summary
    try:return summary(app.state.paper.path,decision_id)
    except ValueError as e:raise HTTPException(status_code=404,detail=str(e)) from e


@app.post('/api/voice/sessions',status_code=201)
def voice_session(request: VoiceOffer):
    from backend.voice import summary,LiveVoice
    from backend.decision_provider import ProviderFailure
    if (len(request.sdp)>65536 or not request.sdp.startswith('v=0') or 'm=audio ' not in request.sdp):
        raise HTTPException(status_code=422,detail='A WebRTC audio SDP offer is required')
    try:record=summary(app.state.paper.path,request.decision_id)
    except ValueError as e:raise HTTPException(status_code=404,detail=str(e)) from e
    try:
        result=getattr(app.state,'voice_provider',None) or LiveVoice()
        return dict(**result.create(request.sdp,record),decision_id=request.decision_id,record=record,provider_mode=result.mode)
    except ProviderFailure as e:
        code=503 if e.status=='missing_credentials' else 504 if e.status=='timeout' else 502
        raise HTTPException(status_code=code,detail=e.code) from None
