"""Controlled analyst/reviewer replies; no real key or provider access."""
from contextlib import asynccontextmanager
from hashlib import sha256
from datetime import UTC,datetime
import os
from pathlib import Path
import sqlite3

from backend.decisions import encoded
from backend.decision_provider import ProviderFailure
from backend.decision_review import review_question
from backend.indicator_store import IndicatorStore
from backend.main import app,setup_paper
from scripts.decision_fixture import seed,FixtureFeed,ControlledProvider,answer,review_answer


class ReviewProvider(ControlledProvider):
    def __init__(self):super().__init__();self.review_calls=0
    def record(self,role,snapshot,evidence):
        with sqlite3.connect(os.environ['ARBITRADE_CONFIG_DATABASE']) as c:
            c.execute('''CREATE TABLE IF NOT EXISTS fixture_role_receipts
                (id INTEGER PRIMARY KEY,role TEXT,snapshot_id TEXT,snapshot_sha256 TEXT,evidence_json TEXT)''')
            c.execute('INSERT INTO fixture_role_receipts(role,snapshot_id,snapshot_sha256,evidence_json) VALUES (?,?,?,?)',
                (role,snapshot['snapshot_id'],sha256(encoded(snapshot).encode()).hexdigest(),encoded(evidence)))
    def decide(self,snapshot):
        self.calls+=1;self.record('analyst',snapshot,dict(snapshot=snapshot))
        return answer('buy' if self.calls==3 else 'hold')
    def review(self,evidence,image_url,question):
        self.review_calls+=1;self.record('reviewer',evidence['snapshot'],evidence)
        assert question==review_question()
        if self.review_calls==4:raise ProviderFailure('timeout','controlled_review_timeout')
        if self.review_calls==5:return dict(model=self.model,answers=[])
        return review_answer('reject_unsupported_signal' if self.review_calls==2 else 'accept')


@asynccontextmanager
async def lifespan(application):
    state=Path(os.environ['ARBITRADE_CONFIG_DATABASE']);market=Path(os.environ['ARBITRADE_DATABASE'])
    seed(state,market)
    application.state.indicator_store=IndicatorStore(state)
    application.state.feed=FixtureFeed(market);application.state.feed.status='disabled'
    application.state.paper_clock=lambda:datetime(2026,11,10,15,7,tzinfo=UTC)
    application.state.decision_provider=ReviewProvider();setup_paper(application)
    try:yield
    finally:await application.state.feed.stop()

app.router.lifespan_context=lifespan
