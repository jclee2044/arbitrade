"""Weighted-average P&L, event idempotency, valuation visibility and migration."""

from contextlib import closing
from datetime import UTC, datetime, timedelta
from fractions import Fraction
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from backend.observations import ObservationStore
from backend.paper import PaperBroker
from backend.replay import Replay


class PnlTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.market = Path(self.directory.name)/'observations.sqlite3'
        self.database = Path(self.directory.name)/'chart-config.sqlite3'
        with ObservationStore(self.market):
            pass
        self.start = datetime(2026,11,10,15,tzinfo=UTC)
        self.now = self.start
        self.broker = PaperBroker(self.database, self.market, clock=lambda:self.now)
        self.broker.create_account()
        self.order_number = 0

    def submit(self, action, quantity=None):
        self.order_number += 1
        return self.broker.execute('live', request_id=str(self.order_number), action=action, quantity=quantity,
                                   after_receipt_id=self.broker.market_cursor())

    def tick(self, price, seconds):
        self.now = self.start+timedelta(seconds=seconds)
        with ObservationStore(self.market) as store:
            store.record(dict(id='AAPL',time=int(self.now.timestamp()*1000),price=price,test_data=True),
                         self.now, source_time_utc=self.now.isoformat())
        self.broker.catch_up_live()

    def advance(self, seconds):
        self.now = self.start+timedelta(seconds=seconds)
        self.broker.catch_up_live()

    def test_reference_five_rows_and_restart_reprocessing(self):
        buy = self.submit('buy',4); self.tick(100,10)
        self.tick(110,40); self.advance(60)
        self.submit('sell',1); self.tick(110,70)
        self.tick(95,100); self.advance(120)
        self.submit('close'); self.tick(105,130)
        state = self.broker.snapshot()
        rows = state['pnl_history']
        expected = [('600',4,'0','0','0'), ('600',4,'0','40','40'),
                    ('710',3,'10','30','40'), ('710',3,'10','-15','-5'), ('1025',0,'25','0','25')]
        self.assertEqual([(r['cash'],r['shares'],r['realized'],r['unrealized'],r['total']) for r in rows], expected)
        self.assertEqual([r['event_type'] for r in rows], ['fill','valuation','fill','valuation','fill'])
        self.assertEqual([r['price'] for r in rows], ['100','110','110','95','105'])
        self.assertEqual([r['average_cost'] for r in rows], ['100','100','100','100',None])
        self.broker.execute('live',request_id='1',action='buy',quantity=4)
        for _ in range(3):self.broker.catch_up_live()
        self.broker = PaperBroker(self.database,self.market,clock=lambda:self.now)
        self.broker.create_account(); self.broker.catch_up_live()
        self.assertEqual(rows,self.broker.snapshot()['pnl_history'])
        self.assertEqual(buy['id'],self.broker.snapshot()['orders'][0]['id'])
        self.assertEqual(len({r['event_key'] for r in rows}),5)
        self.assertTrue(all(r['account_id']=='live' and r['symbol']=='AAPL' for r in rows))

    def test_weighted_purchases_partial_sale_and_exact_fractional_cost(self):
        self.submit('buy',1); self.tick(100,10)
        self.submit('buy',2); self.tick(101,20)
        self.submit('sell',1); self.tick(102,30)
        row=self.broker.snapshot()['pnl_history'][-1]
        self.assertEqual(row['basis_exact'],'604/3')
        self.assertEqual(row['realized_exact'],'4/3')
        self.assertTrue(row['average_cost'].startswith('100.666666666'))
        self.submit('close'); self.tick(100,40)
        final=self.broker.snapshot()['pnl_history'][-1]
        self.assertEqual((final['realized'],final['unrealized'],final['total'],final['cash']),('0','0','0','1000'))

    def test_unavailable_price_revisions_preserve_prior_rows(self):
        self.submit('buy',4); self.tick(100,10)
        def mark(price, timestamp='2026-11-10T15:01:00Z', ended=True, receipt_id=1):
            snapshot=dict(symbol='AAPL',candles=[dict(timestamp=timestamp,close=price)],
                          coverage=[dict(timestamp=timestamp,ended=ended,interval_end='2026-11-10T15:02:00Z')])
            self.broker.mark_completed('live',snapshot,event_time='2026-11-10T15:02:00Z',receipt_id=receipt_id)
        mark(None); mark(None)
        state=self.broker.snapshot()
        self.assertEqual(len(state['pnl_history']),2)
        self.assertEqual(state['pnl_summary'][0]['valuation_status'],'unavailable')
        self.assertIsNone(state['pnl_history'][-1]['total'])
        mark(95,receipt_id=2); mark(100,receipt_id=3); mark(95,receipt_id=4)
        rows=self.broker.snapshot()['pnl_history']
        self.assertEqual([r['unrealized'] for r in rows],['0',None,'-20','0','-20'])
        self.assertEqual(len(set(r['event_key'] for r in rows)),5)
        mark(95,receipt_id=2)  # Reprocessing an older version must not append or rewind.
        mark(None,receipt_id=1)
        mark(999,timestamp='2026-11-10T15:00:00Z')
        mark(999,ended=False)
        self.assertEqual(rows,self.broker.snapshot()['pnl_history'])

    def test_pnl_insert_failure_rolls_back_fill_and_account(self):
        self.submit('buy',4)
        with closing(sqlite3.connect(self.database)) as c,c:
            c.execute("CREATE TRIGGER fail_pnl BEFORE INSERT ON paper_pnl_history BEGIN SELECT RAISE(ABORT,'test P&L failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.tick(100,10)
        state=self.broker.snapshot()
        self.assertEqual(state['account']['cash'],'1000')
        self.assertEqual(state['account']['last_receipt_id'],0)
        self.assertEqual(state['orders'][0]['status'],'pending')
        self.assertEqual(state['fills'],[]); self.assertEqual(state['pnl_history'],[])
        with closing(sqlite3.connect(self.database)) as c,c:c.execute('DROP TRIGGER fail_pnl')
        self.broker.catch_up_live()
        self.assertEqual(len(self.broker.snapshot()['pnl_history']),1)
        self.assertEqual(self.broker.snapshot()['account']['cash'],'600')

    def test_legacy_fill_backfill_once(self):
        self.submit('buy',4); self.tick(100,10)
        self.submit('sell',1); self.tick(110,20)
        with closing(sqlite3.connect(self.database)) as c,c:
            c.execute('DROP TABLE paper_pnl_history'); c.execute('DROP TABLE paper_pnl_state')
        self.broker=PaperBroker(self.database,self.market,clock=lambda:self.now)
        rows=self.broker.snapshot()['pnl_history']
        self.assertEqual([(r['cash'],r['realized'],r['unrealized']) for r in rows], [('600','0','0'),('710','10','30')])
        self.broker=PaperBroker(self.database,self.market,clock=lambda:self.now)
        self.assertEqual(rows,self.broker.snapshot()['pnl_history'])

    def test_replay_and_same_timestamp_receipt_boundary(self):
        for price, seconds in [(100,10),(110,40),(110,70),(95,100)]:
            self.now=self.start+timedelta(seconds=seconds)
            with ObservationStore(self.market) as store:
                store.record(dict(id='AAPL',time=int(self.now.timestamp()*1000),price=price,test_data=True),
                             self.now,source_time_utc=self.now.isoformat())
        replay=Replay(self.market,'AAPL',self.start.isoformat(),self.now.isoformat())
        account=self.broker.create_account('replay',now=self.start)
        self.broker.execute(account,request_id='r',action='buy',quantity=4,submitted_at=self.start,after_receipt_id=0)
        try:
            for _ in range(3):
                replay.step(); row=replay.events[replay.position-1]
                self.broker.mark_completed(account,replay.minute_snapshot(),event_time=replay.evaluation,receipt_id=row[0])
                self.broker.observe(account,dict(receipt_id=row[0],observation_id=row[2],received_at_utc=row[1],
                    source_time_utc=row[6],payload=json.loads(row[7]),repeat=False,supersedes=None))
            rows=self.broker.snapshot(account)['pnl_history']
            self.assertEqual([(r['price'],r['unrealized']) for r in rows],[('100','0'),('110','40')])
            self.assertEqual(self.broker.snapshot()['pnl_history'],[])
        finally:replay.close()
        # Explicit receipt boundary excludes a later ID even with identical receipt time.
        from backend.history import history_response
        available=self.start+timedelta(minutes=2)
        with ObservationStore(self.market) as store:
            store.record(dict(id='AAPL',time=1,price=500,test_data=True),available,
                         source_time_utc='2026-11-10T15:00:55+00:00')
        limited=history_response(source='observations',database=self.market,as_of=available,receipt_limit=4)
        self.assertEqual(limited['candles'][0]['close'],110)
        self.assertEqual(history_response(source='observations',database=self.market,as_of=available)['candles'][0]['close'],500)
