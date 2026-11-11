"""Offline-only smoke server. Never imported by backend.main's production lifespan."""
from contextlib import asynccontextmanager
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import socket
import sqlite3

from backend.main import app, setup_paper
from backend.indicator_store import IndicatorStore
from backend.observations import ObservationStore
from backend.chart_decisions import decode_png
from backend.decision_provider import MODEL, ProviderFailure
from scripts.automation_fixture import Feed
from scripts.decision_fixture import review_answer
from scripts.sma_fixture import create_fixture


def no_network(*args, **kwargs):
    raise RuntimeError('External network forbidden in offline SmokeTest')


class Provider:
    name, model, mode, timeout = 'offline-workstation', MODEL, 'controlled', 2

    def decide_image(self, snapshot, image_url, questions):
        raw, binding, metadata = decode_png(image_url)
        assert binding['snapshot_id'] == snapshot['snapshot_id']
        assert binding['symbol'] == snapshot['symbol'] == 'AAPL'
        assert binding['cutoff'] == snapshot['decision_time']
        # Cutoff uniquely matches this completed candle at the snapshot boundary.
        assert datetime.fromisoformat(snapshot['chart']['candles'][-1]['timestamp']) == datetime.fromisoformat(snapshot['candle_timestamp'])
        with sqlite3.connect(os.environ['ARBITRADE_CONFIG_DATABASE']) as c:
            c.execute('INSERT INTO smoke_payloads VALUES (?,?,?,?,?)',
                      (snapshot['snapshot_id'], snapshot['symbol'], snapshot['candle_timestamp'], raw, json.dumps(binding)))
        if app.state.scenario == 'failure':
            raise ProviderFailure('provider_error', 'offline_provider_failure')
        action = app.state.scenario
        if action not in {'buy', 'sell', 'close'}:
            action = 'hold' if snapshot['account']['shares'] else 'wait'
        choices = dict(action=action, crossover=snapshot['indicators']['crossover'] or 'none', evidence='sufficient')
        return dict(model=MODEL, answers=[dict(type='choice', name=q['name'], choice=choices[q['name']], confidence=1,
                    probabilities=[dict(value=v['value'], probability=int(v['value'] == choices[q['name']])) for v in q['choices']]) for q in questions])

    def review(self, evidence, image_url, question):
        raw, binding, metadata = decode_png(image_url)
        assert binding['snapshot_id'] == evidence['snapshot']['snapshot_id']
        return review_answer('reject_unsupported_signal' if app.state.veto else 'accept')


@asynccontextmanager
async def lifespan(application):
    state = Path(os.environ['ARBITRADE_CONFIG_DATABASE'])
    market = Path(os.environ['ARBITRADE_DATABASE'])
    assert not state.exists() and not market.exists(), 'SmokeTest must use new databases'
    create_fixture(market)
    application.state.fixture_now = [datetime(2026, 11, 10, 15, 7, tzinfo=UTC)]
    application.state.scenario = 'manual'
    application.state.veto = False
    application.state.indicator_store = IndicatorStore(state)
    application.state.feed = Feed(market)
    application.state.feed.status = 'disabled'
    application.state.paper_clock = lambda: application.state.fixture_now[0]
    application.state.decision_provider = Provider()
    setup_paper(application)
    with sqlite3.connect(state) as c:
        c.execute('CREATE TABLE smoke_payloads (snapshot_id TEXT, symbol TEXT, candle_time TEXT, png BLOB, binding TEXT)')
    # Block outbound provider/calendar/market connections, while Uvicorn accepts local clients.
    original = socket.create_connection
    socket.create_connection = no_network
    try:
        yield
    finally:
        socket.create_connection = original
        await application.state.feed.stop()


app.router.lifespan_context = lifespan


@app.post('/fixture/control')
def control(body: dict):
    if 'scenario' in body:
        assert body['scenario'] in {'manual', 'failure', 'buy', 'sell', 'close'}
        app.state.scenario = body['scenario']
    if 'veto' in body:
        app.state.veto = bool(body['veto'])
    if 'order_size' in body:
        assert body['order_size'] in (1, 4)
        app.state.paper.order_size = body['order_size']
    return dict(scenario=app.state.scenario, order_size=app.state.paper.order_size)


@app.post('/fixture/event')
def event(body: dict):
    now = datetime.fromisoformat(body['now'].replace('Z', '+00:00'))
    assert now >= app.state.fixture_now[0], 'Test clock cannot reverse'
    app.state.fixture_now[0] = now
    if 'price' in body:
        with ObservationStore(app.state.feed.database) as store:
            store.record(dict(id='AAPL', price=body['price'], time=int(now.timestamp()*1000), test_data=True),
                         now, source_time_utc=now.isoformat())
    app.state.automation.tick()
    return dict(now=now.isoformat())
