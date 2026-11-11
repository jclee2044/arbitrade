"""Reviewed paper application: idempotence, isolation, fill/stop races and atomicity."""
import asyncio
from contextlib import closing
from datetime import UTC,datetime,timedelta
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from backend.automation import AutomationService
from backend.decisions import DecisionService
from backend.chart_decisions import manifest,decide_image
from backend.indicator_store import IndicatorStore
from backend.observations import ObservationStore
from backend.test_chart_decisions import png
from scripts.decision_fixture import seed,review_answer
from backend.decision_provider import MODEL


class Provider:
    name,model,mode,timeout='controlled-automation',MODEL,'controlled',.5
    def __init__(self):self.calls=0;self.reviews=0;self.verdict='accept';self.action='buy';self.entered=None;self.release=None
    def decide_image(self,snapshot,url,questions):
        self.calls+=1
        if self.entered:self.entered.set();self.release.wait(3)
        choices=dict(action=self.action,crossover=snapshot['indicators']['crossover'] or 'none',evidence='sufficient')
        return dict(model=MODEL,answers=[dict(type='choice',name=q['name'],choice=choices[q['name']],confidence=1,
            probabilities=[dict(value=v['value'],probability=int(v['value']==choices[q['name']])) for v in q['choices']]) for q in questions])
    def review(self,*args):self.reviews+=1;return review_answer(self.verdict)


class AutomationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.state=Path(self.tmp.name)/'state.sqlite3';self.market=Path(self.tmp.name)/'market.sqlite3'
        self.broker,self.now=seed(self.state,self.market);self.broker.order_size=4
        self.provider=Provider();self.ds=DecisionService(self.state,self.market,self.broker,provider=self.provider)
        self.indicators=IndicatorStore(self.state);self.auto=AutomationService(self.broker,self.ds,self.indicators)
        self.run=self.auto.start(short_window=2,long_window=3)['run'];self.account=self.run['account_id']
        self.quote('2026-11-10T15:07:10Z',13);self.quote('2026-11-10T15:08:10Z',19)
        self.now[0]=datetime(2026,11,10,15,9,tzinfo=UTC);self.auto.tick()

    def quote(self,stamp,price):
        self.now[0]=datetime.fromisoformat(stamp.replace('Z','+00:00'))
        with ObservationStore(self.market) as store:
            store.record(dict(id='AAPL',price=price,time=int(self.now[0].timestamp()*1000),test_data=True),self.now[0],source_time_utc=self.now[0].isoformat())
        self.auto.tick()

    def claim(self):return self.auto.claim(self.run['id'],'2026-11-10T15:08:00Z')
    def capture(self,claim):
        binding=manifest(claim['snapshot']);return dict(image_url=png(binding),manifest=binding)
    def state_now(self):return self.broker.snapshot(self.account)
    def balances(self):
        s=self.state_now();return s['account']['cash'],sum(p['shares'] for p in s['positions']),len(s['fills'])
    async def approved(self):
        claim=self.claim();return await self.auto.analyze(claim['attempt']['id'],self.capture(claim))

    async def test_approved_twice_one_fill_and_pnl_decision_atomic(self):
        self.assertTrue(self.account.startswith('test-'));self.assertEqual(self.balances(),('1000',0,0))
        live_before=self.broker.snapshot('live')
        a=await self.approved();self.assertEqual(a['status'],'pending')
        self.auto.apply(a['id']);self.assertEqual(self.balances(),('1000',0,0))
        self.quote('2026-11-10T15:09:10Z',20)
        self.assertEqual(self.balances(),('920',4,1))
        self.auto.apply(a['id']);duplicate=self.claim();self.assertFalse(duplicate['claimed'])
        self.assertEqual(self.balances(),('920',4,1));self.assertEqual(self.provider.calls,1);self.assertEqual(self.provider.reviews,1)
        a=self.auto.attempt(a['id']);self.assertEqual(a['status'],'filled')
        with closing(sqlite3.connect(self.state)) as c:
            row=c.execute('''SELECT a.decision_id,f.id,p.cash,p.shares,p.total FROM automation_attempts a
                JOIN paper_fills f ON f.id=a.fill_id JOIN paper_pnl_history p ON p.fill_id=f.id WHERE a.id=?''',(a['id'],)).fetchone()
        self.assertEqual(row,(a['decision_id'],a['fill_id'],'920',4,'0'))
        self.assertEqual(len(self.broker.snapshot('live')['fills']),len(live_before['fills']))
        self.assertEqual(self.broker.snapshot('live')['account']['cash'],live_before['account']['cash'])

    async def test_veto_missing_image_and_manual_question_no_orders(self):
        claim=self.claim();before=self.balances()
        manual=await decide_image(self.ds,claim['snapshot']['snapshot']['snapshot_id'],self.capture(claim))
        self.assertTrue(manual['review']['final_check']['passed']);self.assertEqual(self.balances(),before)
        self.provider.verdict='reject_unsupported_signal'
        a=await self.auto.analyze(claim['attempt']['id'],self.capture(claim))
        self.assertEqual((a['status'],a['reason']),('skipped','decision_not_approved'));self.assertEqual(self.balances(),before)
        # A separate strategy key can test a failed capture without reusing the handled candle.
        self.auto.stop(self.run['id']);self.run=self.auto.start(short_window=2,long_window=4)['run']
        self.quote('2026-11-10T15:09:10Z',20);self.now[0]+=timedelta(minutes=1)
        claim=self.auto.claim(self.run['id'],'2026-11-10T15:09:00Z');calls=self.provider.calls
        a=await self.auto.analyze(claim['attempt']['id'],None,'chart_unavailable')
        self.assertEqual(a['status'],'skipped');self.assertIsNotNone(a['decision_id']);self.assertEqual(self.provider.calls,calls)
        self.assertEqual(self.ds.get_decision(a['decision_id'])['status'],'invalid_image')

    async def test_stop_during_model_reply_and_pending_order(self):
        claim=self.claim();self.provider.entered=threading.Event();self.provider.release=threading.Event()
        task=asyncio.create_task(self.auto.analyze(claim['attempt']['id'],self.capture(claim)))
        self.assertTrue(await asyncio.to_thread(self.provider.entered.wait,1))
        self.auto.stop(self.run['id']);self.provider.release.set();a=await task
        self.assertEqual((a['status'],a['reason']),('skipped','automation_stopped'));self.assertEqual(self.balances(),('1000',0,0))
        self.assertFalse(self.state_now()['orders'])

    async def test_stop_cancels_pending_and_restart_deduplicates(self):
        a=await self.approved();self.auto.stop(self.run['id']);self.quote('2026-11-10T15:09:10Z',20)
        self.assertEqual(self.balances(),('1000',0,0));self.assertEqual(self.auto.attempt(a['id'])['reason'],'automation_stopped')
        self.auto=AutomationService(self.broker,self.ds,self.indicators)
        self.run=self.auto.start(short_window=2,long_window=3)['run']
        self.assertFalse(self.claim()['claimed']);self.assertEqual(self.provider.calls,1)

    async def test_fill_rechecks_price_cash_age_and_transaction_rollback(self):
        a=await self.approved()
        self.quote('2026-11-10T15:09:10Z',300)
        self.assertEqual(self.balances(),('1000',0,0));self.assertEqual(self.auto.attempt(a['id'])['reason'],'Insufficient cash at fill')

    async def test_stale_decision_and_fill_failure_rollback(self):
        a=await self.approved();self.now[0]+=timedelta(seconds=121)
        self.quote(self.now[0].isoformat(),20)
        self.assertEqual(self.balances(),('1000',0,0));self.assertEqual(self.auto.attempt(a['id'])['reason'],'decision_expired')

    async def test_fill_pnl_and_application_roll_back_together(self):
        a=await self.approved();before=self.state_now()
        from backend import pnl
        original=pnl.record_fill
        def fail(c,fill,order,cash):
            if order['account_id']==self.account:raise RuntimeError('controlled fill failure')
            return original(c,fill,order,cash)
        with patch.object(pnl,'record_fill',side_effect=fail):
            with self.assertRaisesRegex(RuntimeError,'controlled fill failure'):self.quote('2026-11-10T15:09:10Z',20)
        self.assertEqual(self.balances(),('1000',0,0));self.assertEqual(self.auto.attempt(a['id'])['status'],'pending')
        self.auto.tick();self.assertEqual(self.balances(),('920',4,1));self.assertEqual(self.auto.attempt(a['id'])['status'],'filled')

    async def test_restart_cancels_pending_before_new_receipt_and_stale_quote(self):
        a=await self.approved()
        self.auto=AutomationService(self.broker,self.ds,self.indicators)
        self.quote('2026-11-10T15:09:10Z',20)
        self.assertEqual(self.balances(),('1000',0,0));self.assertEqual(self.auto.attempt(a['id'])['reason'],'backend_restarted')

    async def test_stale_fill_quote_rejected(self):
        a=await self.approved();self.now[0]=datetime(2026,11,10,15,9,40,tzinfo=UTC)
        with ObservationStore(self.market) as store:
            store.record(dict(id='AAPL',price=20,time=1,test_data=True),self.now[0],source_time_utc='2026-11-10T15:09:01Z')
        self.auto.tick();self.assertEqual(self.auto.attempt(a['id'])['reason'],'stale_fill_quote')
        self.assertEqual(self.balances(),('1000',0,0))

    async def test_close_whole_position_and_wait_no_order(self):
        a=await self.approved();self.quote('2026-11-10T15:09:10Z',20)
        self.quote('2026-11-10T15:09:50Z',1);self.now[0]=datetime(2026,11,10,15,10,tzinfo=UTC)
        self.provider.action='close';claim=self.auto.claim(self.run['id'],'2026-11-10T15:09:00Z')
        a=await self.auto.analyze(claim['attempt']['id'],self.capture(claim));self.assertEqual(a['status'],'pending')
        self.quote('2026-11-10T15:10:10Z',10);self.assertEqual(self.balances(),('960',0,2))
        self.provider.action='wait';self.now[0]=datetime(2026,11,10,15,11,tzinfo=UTC)
        claim=self.auto.claim(self.run['id'],'2026-11-10T15:10:00Z')
        a=await self.auto.analyze(claim['attempt']['id'],self.capture(claim));self.assertEqual(a['status'],'no_order')
        self.assertEqual(len(self.state_now()['orders']),2)

    async def test_sell_rechecks_position_after_manual_order(self):
        await self.approved();self.quote('2026-11-10T15:09:10Z',20)
        self.quote('2026-11-10T15:09:50Z',1);self.now[0]=datetime(2026,11,10,15,10,tzinfo=UTC)
        # An earlier manual order consumes shares before the automated sale's FIFO turn.
        self.broker.execute(self.account,request_id='manual-close',action='close',after_receipt_id=self.broker.market_cursor())
        self.provider.action='sell';claim=self.auto.claim(self.run['id'],'2026-11-10T15:09:00Z')
        a=await self.auto.analyze(claim['attempt']['id'],self.capture(claim));self.quote('2026-11-10T15:10:10Z',10)
        self.assertEqual(self.auto.attempt(a['id'])['reason'],'Insufficient shares at fill')
        self.assertEqual(self.balances(),('960',0,2))
