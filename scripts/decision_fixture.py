"""Controlled Decision API fixture: no live model calls or real keys loaded."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path

from backend.decision_provider import ACTIONS, MODEL, ProviderFailure
from backend.indicator_store import IndicatorStore
from backend.live import LiveFeed
from backend.main import app, setup_paper
from backend.observations import ObservationStore
from backend.paper import PaperBroker


def answer(choice='hold'):
    return dict(model=MODEL, answers=[dict(type='choice', name='paper_action', choice=choice, confidence=1.0,
        probabilities=[dict(value=action, probability=float(action==choice)) for action in ACTIONS])])


def review_answer(verdict='accept'):
    from backend.decision_review import VERDICTS
    return dict(model=MODEL,answers=[dict(type='choice',name='review_verdict',choice=verdict,confidence=1.0,
        probabilities=[dict(value=v,probability=float(v==verdict)) for v in VERDICTS])])


class ControlledProvider:
    name, model, mode, timeout = 'controlled-fixture', MODEL, 'controlled', 0.1
    def __init__(self):self.calls=0
    def review(self,evidence,image_url,question):return review_answer()
    def decide(self,snapshot):
        self.calls+=1
        if self.calls==2:raise ProviderFailure('timeout','controlled_provider_timeout')
        if self.calls==3:return dict(model=MODEL,answers=[dict(type='choice',name='wrong',choice='hold')])
        return answer('hold')

    def decide_image(self,snapshot,image_url,questions):
        import json,sqlite3
        from backend.chart_decisions import decode_png
        raw,binding,meta=decode_png(image_url)
        assert binding['snapshot_id']==snapshot['snapshot_id']
        with sqlite3.connect(os.environ['ARBITRADE_CONFIG_DATABASE']) as c:
            c.execute('CREATE TABLE IF NOT EXISTS fixture_image_receipts (png BLOB, snapshot_id TEXT, questions_json TEXT)')
            c.execute('INSERT INTO fixture_image_receipts VALUES (?,?,?)',(raw,snapshot['snapshot_id'],json.dumps(questions)))
            calls=c.execute('SELECT COUNT(*) FROM fixture_image_receipts').fetchone()[0]
        if calls==5:raise ProviderFailure('timeout','controlled_image_timeout')
        choices={'action':'hold','crossover':'down' if calls==2 else 'unreadable' if calls==3 else 'up','evidence':'sufficient'}
        return dict(model=MODEL,answers=[dict(type='choice',name=q['name'],choice=choices[q['name']],confidence=1.0,
            probabilities=[dict(value=v['value'],probability=float(v['value']==choices[q['name']])) for v in q['choices']])
            for q in questions if not (calls==4 and q['name']=='evidence')])


def seed(state,market):
    now=[datetime(2026,11,10,14,59,tzinfo=UTC)]
    with ObservationStore(market):pass
    broker=PaperBroker(state,market,clock=lambda:now[0],order_size=1)
    broker.create_account()
    broker.execute('live',request_id='fixture-initial-holding',action='buy',quantity=4)
    for index,price in enumerate([13,10,7,13,19,7,1]):
        now[0]=datetime(2026,11,10,15,tzinfo=UTC)+timedelta(minutes=index,seconds=10)
        with ObservationStore(market) as store:
            store.record(dict(id='AAPL',time=int(now[0].timestamp()*1000),price=price,test_data=True,day_volume=str((index+1)*100)),
                         now[0],source_time_utc=now[0].isoformat())
        broker.catch_up_live()
    now[0]=datetime(2026,11,10,15,7,tzinfo=UTC);broker.catch_up_live()
    return broker,now


class FixtureFeed(LiveFeed):
    def snapshot(self,timeframe='1m'):
        from backend.history import history_response
        result=history_response(source='observations',database=self.database,timeframe=timeframe,
                                as_of=datetime(2026,11,10,15,7,tzinfo=UTC))
        return dict(result,type='snapshot',interval=timeframe,source='CONSTRUCTED decision fixture · test_data=true',feed=self.feed_state())


@asynccontextmanager
async def lifespan(application):
    state=Path(os.environ['ARBITRADE_CONFIG_DATABASE']);market=Path(os.environ['ARBITRADE_DATABASE'])
    seed(state,market)
    application.state.indicator_store=IndicatorStore(state)
    if os.environ.get('ARBITRADE_CHART_FIXTURE')=='on':
        application.state.indicator_store.create('AAPL','1m','Range 2','price_range',{'window':2})
    application.state.feed=FixtureFeed(market);application.state.feed.status='disabled'
    application.state.paper_clock=lambda:datetime(2026,11,10,15,7,tzinfo=UTC)
    application.state.decision_provider=ControlledProvider()
    setup_paper(application)
    try:yield
    finally:await application.state.feed.stop()


app.router.lifespan_context=lifespan
