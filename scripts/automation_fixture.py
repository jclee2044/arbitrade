"""Disposable automation clock/quote controls; never imported by production app."""
from contextlib import asynccontextmanager
from datetime import UTC,datetime
import json
import os
from pathlib import Path
import sqlite3
import threading

from fastapi import HTTPException
from backend.main import app,setup_paper
from backend.live import LiveFeed
from backend.indicator_store import IndicatorStore
from backend.observations import ObservationStore
from backend.decision_provider import MODEL
from scripts.decision_fixture import seed,review_answer


class Provider:
    name,model,mode,timeout='controlled-automation',MODEL,'controlled',5
    def __init__(self,path):self.path=path;self.entered=threading.Event();self.release=threading.Event()
    def decide_image(self,snapshot,url,questions):
        from backend.chart_decisions import decode_png
        raw,binding,meta=decode_png(url)
        with sqlite3.connect(self.path) as c:
            c.execute('CREATE TABLE IF NOT EXISTS fixture_captures (snapshot_id TEXT,png BLOB)')
            c.execute('INSERT INTO fixture_captures VALUES (?,?)',(snapshot['snapshot_id'],raw))
            count=c.execute('SELECT COUNT(*) FROM fixture_captures').fetchone()[0]
        choices=dict(action='buy' if snapshot['account']['shares']==0 else 'sell',crossover=snapshot['indicators']['crossover'] or 'none',evidence='sufficient')
        return dict(model=MODEL,answers=[dict(type='choice',name=q['name'],choice=choices[q['name']],confidence=1,
            probabilities=[dict(value=v['value'],probability=int(v['value']==choices[q['name']])) for v in q['choices']]) for q in questions])
    def review(self,evidence,image_url,question):
        return review_answer('reject_unsupported_signal' if evidence['analyst']['proposal']=='sell' else 'accept')


class Feed(LiveFeed):
    def snapshot(self,timeframe='1m'):
        from backend.history import history_response
        result=history_response(source='observations',database=self.database,timeframe=timeframe,as_of=app.state.fixture_now[0])
        return dict(result,type='snapshot',interval=timeframe,source='CONSTRUCTED automation fixture',feed=self.feed_state())


@asynccontextmanager
async def lifespan(application):
    state=Path(os.environ['ARBITRADE_CONFIG_DATABASE']);market=Path(os.environ['ARBITRADE_DATABASE'])
    # Preserve actual test databases across the SmokeTest's backend restart.
    if not state.exists():seed(state,market)
    application.state.fixture_now=[datetime(2026,11,10,15,7,tzinfo=UTC)]
    application.state.indicator_store=IndicatorStore(state)
    application.state.feed=Feed(market);application.state.feed.status='disabled'
    application.state.paper_clock=lambda:application.state.fixture_now[0]
    application.state.decision_provider=Provider(state)
    setup_paper(application)
    try:yield
    finally:await application.state.feed.stop()


app.router.lifespan_context=lifespan


@app.post('/fixture/advance')
def advance(body:dict):
    now=datetime.fromisoformat(body['now'].replace('Z','+00:00'));app.state.fixture_now[0]=now
    if 'price' in body:
        with ObservationStore(app.state.feed.database) as store:
            store.record(dict(id='AAPL',price=body['price'],time=int(now.timestamp()*1000),day_volume=str(body.get('volume',1000)),test_data=True),now,source_time_utc=now.isoformat())
    app.state.automation.tick()
    return dict(now=now.isoformat())


@app.get('/fixture/pending')
def pending():return dict(entered=app.state.decision_provider.entered.is_set())


@app.post('/fixture/release')
def release():app.state.decision_provider.release.set();return dict(released=True)
