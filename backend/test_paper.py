"""Paper execution: pending arrival fills, idempotency, resources and atomicity."""

from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from backend.observations import ObservationStore
from backend.paper import PaperBroker, RequestConflict


class PaperTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.market = Path(self.directory.name) / 'observations.sqlite3'
        self.state = Path(self.directory.name) / 'chart-config.sqlite3'
        with ObservationStore(self.market):
            pass
        self.broker = PaperBroker(self.state, self.market)
        self.broker.create_account()
        self.time = datetime(2026, 11, 10, 15, tzinfo=UTC)
        self.sequence = 0

    def submit(self, action, quantity=None, request_id=None, **kwargs):
        return self.broker.execute('live', action=action, quantity=quantity,
                                   request_id=request_id or f'request-{action}-{len(self.broker.snapshot()["orders"])}',
                                   submitted_at=self.time, after_receipt_id=self.broker.market_cursor(), **kwargs)

    def record(self, price, **extra):
        self.sequence += 1
        timestamp = self.time + timedelta(seconds=10*self.sequence)
        with ObservationStore(self.market) as store:
            return store.record(dict(id='AAPL', time=int(timestamp.timestamp()*1000), price=price,
                                     test_data=True, **extra), timestamp, source_time_utc=timestamp.isoformat())

    def tick(self, price):
        self.record(price)
        self.broker.catch_up_live()

    def balances(self):
        state = self.broker.snapshot()
        return state['account']['cash'], sum(p['shares'] for p in state['positions'])

    def test_reference_three_fills_retry_and_restart(self):
        self.assertEqual(self.balances(), ('1000', 0))
        buy = self.submit('buy', 4, 'buy-four')
        self.assertEqual(buy['status'], 'pending')
        self.assertEqual(self.broker.snapshot()['fills'], [])
        self.tick(100)
        self.assertEqual(self.balances(), ('600', 4))
        retry = self.submit('buy', 4, 'buy-four')
        self.assertEqual(retry['id'], buy['id'])
        self.assertEqual(retry['status'], 'filled')
        self.submit('sell', 1)
        self.tick(110)
        self.assertEqual(self.balances(), ('710', 3))
        self.submit('close')
        self.tick(105)
        self.assertEqual(self.balances(), ('1025', 0))
        rejected = self.submit('sell', 1)
        self.assertEqual(rejected['status'], 'rejected')
        self.assertIn('more shares', rejected['rejection_reason'])
        self.broker = PaperBroker(self.state, self.market)
        self.broker.create_account()
        self.broker.catch_up_live()
        self.assertEqual(self.balances(), ('1025', 0))
        self.assertEqual(len(self.broker.snapshot()['fills']), 3)
        self.assertEqual(self.submit('buy', 4, 'buy-four')['id'], buy['id'])
        with self.assertRaises(RequestConflict):
            self.submit('buy', 5, 'buy-four')
        self.assertEqual(len(self.broker.snapshot()['orders']), 4)

    def test_invalid_quantities_hold_wait_and_oversell(self):
        self.assertEqual(self.submit('wait', request_id='wait')['status'], 'no_order')
        self.assertEqual(self.submit('hold', request_id='hold-empty')['status'], 'rejected')
        self.assertEqual(len(self.broker.snapshot()['orders']), 0)
        for index, quantity in enumerate([None, 0, -1, True, 1.5, 4.0, '4', 2147483648]):
            result = self.submit('buy', quantity, f'invalid-{index}')
            self.assertEqual(result['status'], 'rejected')
            self.assertIn('positive whole', result['rejection_reason'])
        self.submit('buy', 2)
        self.tick(100)
        count = len(self.broker.snapshot()['orders'])
        self.assertEqual(self.submit('hold', request_id='hold')['status'], 'no_order')
        self.assertEqual(self.submit('wait', request_id='wait-in-position')['status'], 'rejected')
        self.assertEqual(count, len(self.broker.snapshot()['orders']))
        self.assertEqual(self.submit('sell', 3)['status'], 'rejected')

    def test_fill_rechecks_cash_and_shares_fifo(self):
        self.submit('buy', 8, 'first')
        self.submit('buy', 8, 'second')
        self.tick(100)
        self.assertEqual(self.balances(), ('200', 8))
        self.assertEqual(self.broker.snapshot()['orders'][1]['rejection_reason'], 'Insufficient cash at fill')
        self.submit('sell', 6, 'sell-first')
        self.submit('sell', 6, 'sell-second')
        self.submit('close', request_id='close-rest')
        self.tick(110)
        self.assertEqual(self.balances(), ('1080', 0))
        state = self.broker.snapshot()
        self.assertEqual(state['orders'][3]['rejection_reason'], 'Insufficient shares at fill')
        self.assertEqual(state['fills'][-1]['quantity'], 2)

    def test_no_old_quote_fill_and_recover_committed_receipt_after_crash(self):
        self.tick(99)
        self.submit('buy', 4)
        self.broker.catch_up_live()
        self.assertEqual(self.broker.snapshot()['fills'], [])
        self.record(100)  # Receiver committed then process died before execution callback.
        self.broker = PaperBroker(self.state, self.market)
        self.broker.create_account()
        self.broker.catch_up_live()
        self.assertEqual(self.balances(), ('600', 4))
        self.assertEqual(len(self.broker.snapshot()['fills']), 1)

    def test_atomic_rollback_and_concurrent_retry(self):
        def submit_same(_):
            return self.submit('buy', 4, 'concurrent')['id']
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(len(set(pool.map(submit_same, range(8)))), 1)
        self.record(100)
        with closing(sqlite3.connect(self.state)) as c, c:
            c.execute("CREATE TRIGGER fail_fill BEFORE INSERT ON paper_fills BEGIN SELECT RAISE(ABORT,'test failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.broker.catch_up_live()
        self.assertEqual(self.balances(), ('1000', 0))
        self.assertEqual(self.broker.snapshot()['orders'][0]['status'], 'pending')
        self.assertEqual(self.broker.snapshot()['account']['last_receipt_id'], 0)
        with closing(sqlite3.connect(self.state)) as c, c:
            c.execute('DROP TRIGGER fail_fill')
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(lambda _: self.broker.catch_up_live(), range(6)))
        self.assertEqual(self.balances(), ('600', 4))
        self.assertEqual(len(self.broker.snapshot()['fills']), 1)

    def test_replay_uses_only_delivered_receipts_and_separate_accounts(self):
        for price in (100, 110, 105):
            self.record(price)
        replay_id = self.broker.create_account('replay', now=self.time)
        self.broker.execute(replay_id, request_id='replay-buy', action='buy', quantity=4,
                            submitted_at=self.time, after_receipt_id=0)
        self.assertEqual(self.broker.snapshot(replay_id)['fills'], [])
        with ObservationStore(self.market) as store:
            saved = store.snapshot()
        observation = saved['observations'][0]
        receipt = saved['receipts'][0]
        self.broker.observe(replay_id, dict(receipt_id=receipt['id'], observation_id=observation['id'],
            received_at_utc=receipt['received_at_utc'], source_time_utc=observation['source_time_utc'],
            payload=observation['source_fields'], repeat=False, supersedes=None))
        state = self.broker.snapshot(replay_id)
        self.assertEqual(state['account']['cash'], '600')
        self.assertEqual(state['fills'][0]['price'], '100')
        self.assertEqual(self.broker.snapshot()['account']['cash'], '1000')
        retry = self.broker.execute(replay_id, request_id='replay-buy', action='buy', quantity=4, accept_new=False)
        self.assertEqual(retry['status'], 'filled')
        with self.assertRaises(ValueError):
            self.broker.execute(replay_id, request_id='closed', action='buy', quantity=1, accept_new=False)

    def test_eligibility_and_no_retroactive_price_changes(self):
        event = dict(receipt_id=1, observation_id=1, payload={'id':'AAPL', 'price':100},
                     received_at_utc=self.time.isoformat(), source_time_utc=self.time.isoformat(), repeat=False, supersedes=None)
        self.assertEqual(self.broker.eligible(event), 100)
        for patch in ({'repeat':True}, {'supersedes':1}, {'source_time_utc':None},
                      {'source_time_utc':(self.time+timedelta(seconds=1)).isoformat()},
                      {'source_time_utc':'2026-11-10T23:00:00Z', 'received_at_utc':'2026-11-10T23:00:01Z'},
                      {'payload':{'id':'AAPL','price':0}}, {'payload':{'id':'AAPL','price':True}}):
            self.assertIsNone(self.broker.eligible(dict(event, **patch)))
        self.submit('buy', 4)
        self.tick(100)
        with ObservationStore(self.market) as store:
            row = store.snapshot()['observations'][0]
            payload = dict(row['source_fields'], price=1)
            store.record(payload, self.time+timedelta(minutes=1), source_time_utc=row['source_time_utc'], supersedes_id=row['id'])
        self.broker.catch_up_live()
        self.assertEqual(self.broker.snapshot()['fills'][0]['price'], '100')
