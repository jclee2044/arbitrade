"""Disposable classroom provider: captures actual outgoing body; never loads keys."""
from contextlib import asynccontextmanager
import json
import os
import sqlite3

from scripts.decision_fixture import app, lifespan as paper_lifespan
from backend.classroom_decisions import ClassroomDecisions, QUESTION
from backend.decision_provider import MODEL, ProviderFailure


class Provider:
    name, model, mode, timeout = 'controlled-classroom', MODEL, 'controlled', .1
    def post(self, body):
        with sqlite3.connect(os.environ['ARBITRADE_CONFIG_DATABASE']) as c:
            c.execute('CREATE TABLE IF NOT EXISTS classroom_receipts (body TEXT)')
            c.execute('INSERT INTO classroom_receipts VALUES (?)', (json.dumps(body),))
            number = c.execute('SELECT COUNT(*) FROM classroom_receipts').fetchone()[0]
        if number == 5: raise ProviderFailure('timeout', 'controlled_timeout')
        if number == 6: raise ProviderFailure('provider_error', 'controlled_provider_error')
        choice = ['long', 'short', 'wait', 'buy'][min(number - 1, 3)]
        return dict(model=MODEL, answers=[dict(type='choice', name=QUESTION, choice=choice)])


@asynccontextmanager
async def lifespan(application):
    async with paper_lifespan(application):
        application.state.classroom_decisions = ClassroomDecisions(application.state.paper.path, Provider())
        yield


app.router.lifespan_context = lifespan
