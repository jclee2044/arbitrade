"""Frozen candle-close inputs, named choices, durable statuses and zero execution."""

import asyncio
from contextlib import closing
from datetime import UTC,datetime,timedelta
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from backend.decisions import DecisionService, validate_proposal
from backend.decision_provider import MODEL, OpenAIDecisions, ProviderFailure, request_body
from backend.observations import ObservationStore
from backend.replay import Replay
from scripts.decision_fixture import seed, answer, review_answer


class FixedProvider:
    name,model,mode,timeout='controlled',MODEL,'controlled',0.01
    def __init__(self,response=None,failure=None):self.response=response or answer();self.failure=failure;self.calls=0
    def review(self,evidence,image_url,question):return review_answer()
    def decide(self,snapshot):
        self.calls+=1
        if self.failure:raise self.failure
        return self.response


class DecisionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.state=Path(self.directory.name)/'state.sqlite3';self.market=Path(self.directory.name)/'observations.sqlite3'
        self.broker,self.now=seed(self.state,self.market)
        self.provider=FixedProvider()
        self.service=DecisionService(self.state,self.market,self.broker,provider=self.provider)

    def freeze(self,**kwargs):
        return self.service.freeze(candle_timestamp='2026-11-10T15:04:00Z',short_window=2,long_window=3,**kwargs)['snapshot']

    def paper_records(self):
        with closing(sqlite3.connect(self.state)) as c:
            tables=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'paper_%' ORDER BY name")]
            return {table:c.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall() for table in tables}

    async def test_fixed_hold_saved_and_paper_account_untouched(self):
        before=self.paper_records();snapshot=self.freeze()
        self.assertEqual(snapshot['candle']['close'],19)
        self.assertEqual((snapshot['indicators']['short'],snapshot['indicators']['long'],snapshot['indicators']['crossover']),(16,13,'up'))
        self.assertEqual((snapshot['account']['cash'],snapshot['account']['shares']),('948',4))
        self.assertTrue(snapshot['completeness']['complete'])
        self.assertFalse(snapshot['completeness']['paper_order_eligible'])
        result=await self.service.decide(snapshot['snapshot_id'])
        self.assertEqual((result['status'],result['proposal'],result['quantity']),('valid','hold',None))
        self.assertIn('Model proposal: hold. Backend facts',result['explanation'])
        self.assertEqual(result,self.service.get_decision(result['id']))
        self.assertEqual(before,self.paper_records())
        self.assertEqual(self.service.get_snapshot(snapshot['snapshot_id'])['snapshot'],snapshot)
        self.assertEqual(request_body(snapshot)['questions'][0]['name'],'paper_action')
        self.assertEqual([c['value'] for c in request_body(snapshot)['questions'][0]['choices']],['buy','sell','hold','wait','close'])

    async def test_late_revision_and_later_fill_not_visible_at_close(self):
        frozen=self.freeze()
        self.now[0]=datetime(2026,11,10,15,8,tzinfo=UTC)
        self.broker.execute('live',request_id='later-sale',action='sell',quantity=1)
        with ObservationStore(self.market) as store:
            store.record(dict(id='AAPL',time=99,price=999,test_data=True),self.now[0],
                         source_time_utc='2026-11-10T15:04:10+00:00',supersedes_id=5)
            later=self.now[0]+timedelta(seconds=10)
            store.record(dict(id='AAPL',time=100,price=2,test_data=True),later,source_time_utc=later.isoformat())
        self.now[0]=later;self.broker.catch_up_live()
        self.assertEqual(self.broker.snapshot()['positions'][0]['shares'],3)
        again=self.freeze()
        self.assertEqual(again['candle'],frozen['candle'])
        self.assertEqual(again['account'],frozen['account'])
        self.assertEqual(again['indicators'],frozen['indicators'])
        self.assertEqual(self.service.get_snapshot(frozen['snapshot_id'])['snapshot'],frozen)
        evidence=self.service.get_snapshot(again['snapshot_id'],evidence=True)['records']
        self.assertNotIn(8,[row['id'] for row in evidence['observations']])
        self.assertEqual(len(evidence['account_fills']),1)

    async def test_missing_warmup_forming_and_replay_boundary(self):
        missing=await self.service.decide(None)
        self.assertEqual(missing['status'],'missing_input')
        incomplete=self.service.freeze(candle_timestamp='2026-11-10T15:00:00Z',short_window=2,long_window=3)['snapshot']
        self.assertFalse(incomplete['completeness']['complete'])
        self.assertEqual((await self.service.decide(incomplete['snapshot_id']))['error_code'],'snapshot_incomplete')
        self.assertEqual(self.provider.calls,0)
        replay=Replay(self.market,'AAPL','2026-11-10T14:59:00Z','2026-11-10T15:07:00Z',short_window=2,long_window=3)
        account=self.broker.create_account('replay',now=replay.start)
        try:
            for _ in range(5):replay.step()
            snapshot=self.service.freeze(account_id=account,replay=replay,candle_timestamp='2026-11-10T15:04:00Z',short_window=2,long_window=3)['snapshot']
            self.assertFalse(snapshot['completeness']['complete'])
            self.assertIn('candle_not_completed_at_available_time',snapshot['completeness']['missing'])
            self.assertEqual(snapshot['provenance']['receipt_count'],5)
        finally:replay.close()

    async def test_timeout_malformed_refusal_and_provider_error_statuses(self):
        identifier=self.freeze()['snapshot_id'];before=self.paper_records()
        for failure,status in [(ProviderFailure('timeout','controlled_timeout'),'timeout'),
                               (ProviderFailure('provider_error','controlled_failure'),'provider_error'),
                               (ProviderFailure('missing_credentials','backend_key_not_configured'),'missing_credentials')]:
            self.provider.failure=failure
            result=await self.service.decide(identifier)
            self.assertEqual(result['status'],status)
            self.assertIsNone(result['proposal'])
        self.provider.failure=None
        for response,status in [({'model':MODEL,'answers':[]},'malformed_answer'),
            ({'model':MODEL,'answers':[{'type':'choice','name':'other','choice':'hold'}]},'malformed_answer'),
            ({'model':MODEL,'answers':[{'type':'refusal','name':'paper_action'}]},'refused')]:
            self.provider.response=response
            self.assertEqual((await self.service.decide(identifier))['status'],status)
        self.assertEqual(before,self.paper_records())

    async def test_proposal_rules_order_size_and_model_facts_separated(self):
        snapshot=self.freeze();snapshot['account']['order_size']=2
        self.assertEqual(validate_proposal(snapshot,'sell'),(True,'Valid under frozen long-only account rules; no order executed.',2))
        self.assertEqual(validate_proposal(snapshot,'close')[2],4)
        self.assertFalse(validate_proposal(snapshot,'wait')[0])
        snapshot['account']['cash']='1'
        self.assertFalse(validate_proposal(snapshot,'buy')[0])
        snapshot['account']['shares']=0
        self.assertTrue(validate_proposal(snapshot,'wait')[0])
        for action in ('sell','hold','close'):self.assertFalse(validate_proposal(snapshot,action)[0])
        self.provider.response=answer('wait')
        result=await self.service.decide(self.freeze()['snapshot_id'])
        self.assertEqual((result['status'],result['proposal'],result['validation_status']),('invalid_proposal','wait','rejected'))
        self.assertIn('shares 4',result['explanation'])

    async def test_snapshot_and_evidence_integrity_and_provider_sanitization(self):
        identifier=self.freeze()['snapshot_id']
        self.assertEqual(self.service.get_snapshot(identifier,evidence=True)['snapshot']['snapshot_id'],identifier)
        with closing(sqlite3.connect(self.state)) as c,c:
            c.execute("UPDATE decision_snapshots SET evidence_json='{}' WHERE id=?",(identifier,))
        with self.assertRaises(ValueError):self.service.get_snapshot(identifier)
        adapter=OpenAIDecisions()
        with patch.dict(os.environ,{'OPENAI_API_KEY':'fake-secret-for-unit-test'}),patch('backend.decision_provider.urlopen',side_effect=TimeoutError('fake-secret-for-unit-test')):
            with self.assertRaises(ProviderFailure) as failure:adapter.decide({})
            self.assertEqual(failure.exception.status,'timeout')
            self.assertNotIn('fake-secret',str(failure.exception))
