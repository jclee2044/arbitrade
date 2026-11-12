"""Constructed minute data with the actual installed exchange calendar."""

from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from backend.candles import utc_datetime
from backend.history import history_response, load_history
from backend.observations import ObservationStore
from backend.timeframes import MinuteVersion, derive_timeframe, exchange_sessions


def version(candle, available_at=None):
    timestamp = utc_datetime(candle['timestamp'])
    return MinuteVersion(candle, utc_datetime(available_at) if available_at else timestamp + timedelta(minutes=1))


def minute(timestamp, price=104, volume=500):
    return {'timestamp': timestamp, 'open': price, 'high': price + 2,
            'low': price - 1, 'close': price + 1, 'volume': volume}


class TimeframeTests(unittest.TestCase):
    def setUp(self):
        self.sample = [version(c) for c in load_history()]
        self.now = '2026-11-10T22:00:00Z'

    def derive(self, versions=None, timeframe='5m', as_of=None):
        return derive_timeframe(versions if versions is not None else self.sample,
                                timeframe, as_of=as_of or self.now)

    def test_required_five_minute_sample(self):
        result = self.derive()
        self.assertEqual(result['candles'], [{
            'timestamp': '2026-11-09T14:30:00Z', 'open': 100, 'high': 105,
            'low': 99, 'close': 104, 'volume': 3550,
        }])
        status = result['coverage'][0]
        self.assertEqual((status['available_minutes'], status['expected_minutes']), (3, 5))
        self.assertFalse(status['complete'])
        self.assertTrue(status['volume_known'])

    def test_default_minute_and_all_timeframes(self):
        self.assertEqual(history_response(as_of=self.now)['candles'], load_history())
        for timeframe in ('1m', '5m', '15m', '30m', '1h', '1d', '1w', '1mo'):
            result = self.derive(timeframe=timeframe)
            self.assertEqual(set(result['candles'][0]), {'timestamp', 'open', 'high', 'low', 'close', 'volume'})

    def test_week_and_month_use_full_calendar_period_and_actual_final_close(self):
        from backend.decisions import candle_end
        data = [version(minute('2026-11-25T16:00:00Z', 101)),
                version(minute('2026-11-27T17:59:00Z', 103, None)),
                version(minute('2026-11-30T15:00:00Z', 110)),
                version(minute('2026-12-01T15:00:00Z', 120))]
        partial = self.derive(data, '1w', '2026-11-25T17:00:00Z')
        bar, status = partial['candles'][0], partial['coverage'][0]
        self.assertEqual(bar['timestamp'], '2026-11-23T14:30:00Z')
        self.assertEqual((status['interval_end'], status['expected_minutes'], status['ended']),
                         ('2026-11-27T18:00:00Z', 3 * 390 + 210, False))
        done = self.derive(data, '1w', '2026-11-27T18:00:00Z')
        self.assertIsNone(done['candles'][0]['volume'])
        self.assertTrue(done['coverage'][0]['ended'])
        monthly = self.derive(data, '1mo', '2026-12-01T16:00:00Z')
        self.assertEqual([r['timestamp'] for r in monthly['candles']], ['2026-11-02T14:30:00Z', '2026-12-01T14:30:00Z'])
        self.assertEqual(monthly['coverage'][0]['interval_end'], '2026-11-30T21:00:00Z')
        self.assertEqual([r['ended'] for r in monthly['coverage']], [True, False])
        for frame, result in [('1w', done), ('1mo', monthly)]:
            for r in result['coverage']:
                self.assertEqual(candle_end('AAPL', frame, r['timestamp']), utc_datetime(r['interval_end']))
        with self.assertRaises(ValueError):
            candle_end('AAPL', '1w', '2026-11-25T14:30:00Z')

    def test_second_five_minute_group_stays_in_same_day(self):
        data = self.sample + [version(minute('2026-11-09T14:35:00Z'))]
        self.assertEqual([c['timestamp'] for c in self.derive(data)['candles']],
                         ['2026-11-09T14:30:00Z', '2026-11-09T14:35:00Z'])
        daily = self.derive(data, '1d')
        self.assertEqual(len(daily['candles']), 1)
        self.assertEqual(daily['candles'][0]['volume'], 4050)
        self.assertEqual(daily['coverage'][0]['expected_minutes'], 390)
        self.assertFalse(daily['coverage'][0]['coverage_complete'])

    def test_next_session_creates_new_daily(self):
        data = self.sample + [version(minute('2026-11-10T14:30:00Z', 110, 1000))]
        self.assertEqual([c['timestamp'] for c in self.derive(data, '1d')['candles']],
                         ['2026-11-09T14:30:00Z', '2026-11-10T14:30:00Z'])

    def test_hour_aligned_to_session_open_not_clock_hour(self):
        data = [version(minute(t)) for t in ('2026-11-09T15:29:00Z', '2026-11-09T15:30:00Z')]
        self.assertEqual([c['timestamp'] for c in self.derive(data, '1h')['candles']],
                         ['2026-11-09T14:30:00Z', '2026-11-09T15:30:00Z'])

    def test_gap_does_not_split_daily_session(self):
        data = self.sample + [version(minute('2026-11-09T20:59:00Z'))]
        result = self.derive(data, '1d')
        self.assertEqual(len(result['candles']), 1)
        self.assertEqual(result['coverage'][0]['available_minutes'], 4)

    def test_early_close_and_short_last_hour(self):
        data = [version(minute('2026-11-27T17:59:00Z'))]
        result = self.derive(data, '1h', '2026-11-27T18:01:00Z')
        self.assertEqual(result['candles'][0]['timestamp'], '2026-11-27T17:30:00Z')
        self.assertEqual(result['coverage'][0]['interval_end'], '2026-11-27T18:00:00Z')
        self.assertEqual(result['coverage'][0]['expected_minutes'], 30)
        self.assertEqual(self.derive(data, '1d', '2026-11-27T18:01:00Z')['coverage'][0]['expected_minutes'], 210)

    def test_holiday_closed_and_close_boundary_excluded(self):
        data = [version(minute('2026-11-26T14:30:00Z')),
                version(minute('2026-11-27T18:00:00Z'))]
        result = self.derive(data, '1d', '2026-11-28T00:00:00Z')
        self.assertEqual(result['candles'], [])
        self.assertEqual(len(result['excluded_out_of_session_minutes']), 2)

    def test_daylight_saving_session_open_changes(self):
        sessions = exchange_sessions('NASDAQ', '2026-03-06', '2026-03-09')
        self.assertEqual([s.opened.hour for s in sessions], [14, 13])
        sessions = exchange_sessions('NASDAQ', '2026-10-30', '2026-11-02')
        self.assertEqual([s.opened.hour for s in sessions], [13, 14])

    def test_unknown_and_zero_volume_are_distinct(self):
        zero = self.derive([version(minute('2026-11-09T14:30:00Z', volume=0))])
        self.assertEqual(zero['candles'][0]['volume'], 0)
        self.assertTrue(zero['coverage'][0]['volume_known'])
        unknown = self.derive([*self.sample, version(minute('2026-11-09T14:33:00Z', volume=None))])
        self.assertIsNone(unknown['candles'][0]['volume'])
        self.assertFalse(unknown['coverage'][0]['volume_known'])

    def test_available_minute_versions_only_and_revisions_replace(self):
        revised = {**load_history()[1], 'high': 107, 'close': 106, 'volume': 900}
        data = self.sample + [version(revised, '2026-11-09T14:40:00Z')]
        before = self.derive(data, as_of='2026-11-09T14:35:00Z')
        after = self.derive(data, as_of='2026-11-09T14:40:01Z')
        self.assertEqual(before['candles'][0]['high'], 105)
        self.assertEqual(before['candles'][0]['volume'], 3550)
        self.assertEqual(after['candles'][0]['high'], 107)
        self.assertEqual(after['candles'][0]['volume'], 3600)

    def test_replay_does_not_expose_unfinished_csv_minute(self):
        result = self.derive(timeframe='1m', as_of='2026-11-09T14:31:30Z')
        self.assertEqual(len(result['candles']), 1)
        self.assertEqual(result['candles'][0]['timestamp'], '2026-11-09T14:30:00Z')

    def test_coverage_complete_separate_from_ended(self):
        data = [version(minute(f'2026-11-09T14:3{i}:00Z')) for i in range(5)]
        result = self.derive(data, as_of='2026-11-09T14:35:00Z')
        self.assertTrue(result['coverage'][0]['complete'])
        self.assertTrue(result['coverage'][0]['coverage_complete'])
        result = self.derive(self.sample, as_of='2026-11-09T14:33:00Z')
        self.assertFalse(result['coverage'][0]['ended'])
        self.assertFalse(result['coverage'][0]['coverage_complete'])

    def test_invalid_symbol_and_calendar_fail_clearly(self):
        with self.assertRaises(ValueError):
            history_response(symbol='MSFT')
        with self.assertRaises(ValueError):
            history_response(calendar='UNKNOWN_EXCHANGE')


class ReplayObservationTests(unittest.TestCase):
    def test_late_receipts_and_corrections_are_hidden_until_received(self):
        with TemporaryDirectory(prefix='arbitrade-replay-test-') as directory:
            path = Path(directory) / 'test.sqlite3'
            with ObservationStore(path) as store:
                def add(source, received, price, total, supersedes=None):
                    return store.record(
                        {'id': 'AAPL', 'price': price, 'time': str(int(utc_datetime(source).timestamp() * 1000)),
                         'day_volume': str(total), 'test_data': True},
                        utc_datetime(received), source_time_utc=source, supersedes_id=supersedes,
                    )
                baseline = add('2026-11-09T14:29:59Z', '2026-11-09T14:29:59Z', 99, 1000)
                add('2026-11-09T14:30:05Z', '2026-11-09T14:30:06Z', 100, 1004)
                add('2026-11-09T14:30:50Z', '2026-11-09T14:30:51Z', 101, 1011)
                add('2026-11-09T14:30:20Z', '2026-11-09T14:35:00Z', 103, 1009)
                add('2026-11-09T14:29:59Z', '2026-11-09T14:40:00Z', 99, 1001, baseline['observation_id'])
            def replay(at):
                return history_response(source='observations', database=path, as_of=at)['candles'][0]
            before = replay('2026-11-09T14:31:00Z')
            self.assertEqual((before['high'], before['volume']), (101, 11))
            late = replay('2026-11-09T14:35:01Z')
            self.assertEqual((late['high'], late['volume']), (103, 11))
            revised = replay('2026-11-09T14:40:01Z')
            self.assertEqual((revised['high'], revised['volume']), (103, 10))
