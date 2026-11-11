"""Mocked voice negotiation; no backend key or external voice provider."""
from contextlib import asynccontextmanager
from datetime import UTC,datetime
import os
from pathlib import Path

from backend.main import app,setup_paper
from backend.indicator_store import IndicatorStore
from backend.decision_provider import ProviderFailure
from backend.voice import configuration
from scripts.decision_fixture import seed,FixtureFeed,ControlledProvider


class Provider:
    mode='mocked'
    def __init__(self):self.calls=[];self.fail=False
    def create(self,sdp,record):
        self.calls.append(dict(record=record,configuration=configuration(record)))
        if self.fail:raise ProviderFailure('provider_error','controlled_voice_failure')
        return dict(session=dict(id='live_mock_'+str(len(self.calls))),transport=dict(type='webrtc',sdp='v=0\r\nmock-answer'))


@asynccontextmanager
async def lifespan(application):
    state=Path(os.environ['ARBITRADE_CONFIG_DATABASE']);market=Path(os.environ['ARBITRADE_DATABASE'])
    seed(state,market)
    application.state.indicator_store=IndicatorStore(state)
    application.state.feed=FixtureFeed(market);application.state.feed.status='disabled'
    application.state.paper_clock=lambda:datetime(2026,11,10,15,7,tzinfo=UTC)
    application.state.decision_provider=ControlledProvider();application.state.voice_provider=Provider()
    setup_paper(application)
    saved=application.state.decisions.freeze(candle_timestamp='2026-11-10T15:04:00Z',short_window=2,long_window=3)
    await application.state.decisions.decide(saved['snapshot']['snapshot_id'])
    await application.state.decisions.decide(saved['snapshot']['snapshot_id'])
    try:yield
    finally:await application.state.feed.stop()

app.router.lifespan_context=lifespan


@app.get('/fixture/voice-calls')
def calls():return app.state.voice_provider.calls


@app.post('/fixture/voice-fail')
def fail(body:dict):app.state.voice_provider.fail=bool(body.get('fail'));return dict(ok=True)
