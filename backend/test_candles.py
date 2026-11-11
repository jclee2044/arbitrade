"""Constructed source observations only; no market network or production writes."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from backend.candles import form_candles
from backend.observations import ObservationStore

EXPECTED = {'timestamp': '2026-11-09T15:00:00Z', 'open': 100, 'high': 103,
            'low': 100, 'close': 101, 'volume': 11}
SAMPLES = [('14:59:59', 99, 1000), ('15:00:05', 100, 1004),
           ('15:00:20', 103, 1009), ('15:00:50', 101, 1011)]


class CandleTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory(prefix='arbitrade-candle-test-')
        self.store = ObservationStore(Path(self.directory.name) / 'test.sqlite3')
        self.receipt = datetime(2026, 11, 9, 15, 2, tzinfo=UTC)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def add(self, time, price, volume, *, supersedes=None, ticker='AAPL', **fields):
        source = datetime.fromisoformat('2026-11-09T' + time).replace(tzinfo=UTC)
        message = {'id': ticker, 'time': str(int(source.timestamp() * 1000)),
                   'price': price, 'test_data': True, **fields}
        if volume is not None:
            message['day_volume'] = str(volume)
        self.receipt += timedelta(seconds=1)
        return self.store.record(message, self.receipt, source_time_utc=source.isoformat(), supersedes_id=supersedes)

    def target(self, as_of='2026-11-09T15:01:00Z'):
        result = form_candles(self.store.connection, 'AAPL', as_of=as_of)
        index = next(i for i, c in enumerate(result['candles']) if c['timestamp'] == EXPECTED['timestamp'])
        return result['candles'][index], result['minute_status'][index]

    def seed(self):
        return [self.add(*row) for row in SAMPLES]

    def test_expected_before_and_after_minute_end(self):
        self.seed()
        candle, status = self.target('2026-11-09T15:00:55Z')
        self.assertEqual(candle, EXPECTED)
        self.assertFalse(status['ended'])
        self.assertEqual(list(candle), ['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        candle, status = self.target()
        self.assertEqual(candle, EXPECTED)
        self.assertTrue(status['ended'])

    def test_late_middle_tick_revises_ended_candle(self):
        for i in (0, 1, 3):
            self.add(*SAMPLES[i])
        self.assertEqual(self.target()[0]['high'], 101)
        self.add(*SAMPLES[2])
        self.assertEqual(self.target()[0], EXPECTED)

    def test_repeat_does_not_change_candle(self):
        self.seed()
        self.add(*SAMPLES[2])
        self.assertEqual(self.target()[0], EXPECTED)

    def test_explicit_price_and_volume_correction(self):
        ids = self.seed()
        self.add('15:00:50', 104, 1012, supersedes=ids[-1]['observation_id'])
        candle, _ = self.target()
        self.assertEqual(candle, {**EXPECTED, 'high': 104, 'close': 104, 'volume': 12})
        self.assertEqual(len(self.store.snapshot()['observations']), 5)

    def test_corrected_baseline_changes_next_candle_volume(self):
        ids = self.seed()
        self.add('14:59:59', 99, 1001, supersedes=ids[0]['observation_id'])
        self.assertEqual(self.target()[0]['volume'], 10)

    def test_missing_baseline_is_unknown_then_late_baseline_recovers(self):
        for sample in SAMPLES[1:]:
            self.add(*sample)
        self.assertIsNone(self.target()[0]['volume'])
        self.add(*SAMPLES[0])
        self.assertEqual(self.target()[0], EXPECTED)

    def test_counter_reset_unknown(self):
        self.add(*SAMPLES[0])
        self.add('15:00:05', 100, 4)
        self.add('15:00:50', 101, 11)
        candle, status = self.target()
        self.assertIsNone(candle['volume'])
        self.assertIn('reset', status['volume_reason'])

    def test_missing_counter_unknown(self):
        self.add(*SAMPLES[0])
        self.add('15:00:05', 100, None)
        self.add(*SAMPLES[-1])
        self.assertIsNone(self.target()[0]['volume'])

    def test_session_change_unknown(self):
        self.add(*SAMPLES[0], session_id='session-one')
        self.add(*SAMPLES[-1], session_id='session-two')
        self.assertIsNone(self.target()[0]['volume'])

    def test_same_time_distinct_messages_retained_and_flagged(self):
        self.seed()
        self.add('15:00:50', 102, 1012)
        candle, status = self.target()
        self.assertEqual(candle['close'], 102)  # deterministic receipt-order tie break
        self.assertIsNone(candle['volume'])
        self.assertTrue(status['price_order_ambiguous'])

    def test_ambiguous_preceding_baseline_is_unknown(self):
        self.seed()
        self.add('14:59:59', 99, 1001)
        self.assertIsNone(self.target()[0]['volume'])

    def test_other_ticker_is_excluded(self):
        self.seed()
        self.add('15:00:25', 900, 2000, ticker='MSFT')
        self.assertEqual(self.target()[0], EXPECTED)

    def test_no_empty_minutes_or_volume_assignment_across_gap(self):
        self.add('14:58:59', 99, 1000)
        self.add(*SAMPLES[-1])
        result = form_candles(self.store.connection, 'AAPL')
        self.assertEqual(len(result['candles']), 2)
        self.assertIsNone(self.target()[0]['volume'])

    def test_cross_date_baseline_without_session_id_unknown(self):
        previous = {'id': 'AAPL', 'time': 'test', 'price': 99, 'day_volume': '1000', 'test_data': True}
        self.store.record(previous, self.receipt, source_time_utc='2026-11-08T23:59:59+00:00')
        self.add('00:00:05', 100, 1004)
        result = form_candles(self.store.connection, 'AAPL')
        self.assertIsNone(result['candles'][-1]['volume'])

    def test_unknown_source_time_is_reported(self):
        self.store.record({'id': 'AAPL', 'price': 99, 'test_data': True}, self.receipt)
        result = form_candles(self.store.connection, 'AAPL')
        self.assertEqual(result['candles'], [])
        self.assertEqual(result['unbucketed_observation_ids'], [1])
