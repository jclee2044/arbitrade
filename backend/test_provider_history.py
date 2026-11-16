"""Constructed provider history, not evidence of live Yahoo availability."""
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from backend.provider_history import ProviderHistory, months_before, validate
from backend.timeframes import exchange_sessions

NOW = datetime(2026, 11, 12, 18, tzinfo=UTC)


def fixture_rows():
    return [dict(date=s.label, open=100+i, high=103+i, low=99+i, close=102+i, volume=1000+i)
            for i, s in enumerate(exchange_sessions('NASDAQ', '2026-05-12', '2026-11-12'))]


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'history.json'
        self.download = Mock(return_value=fixture_rows())
        self.history = ProviderHistory(self.path, self.download)
        self.empty = dict(candles=[], coverage=[], symbol='AAPL', as_of=NOW.isoformat())

    def merge(self, frame='1d', now=NOW):
        return self.history.merge(self.empty, self.empty, frame, now)

    def test_ranges_weekly_ohlcv_dst_and_shared_cache(self):
        daily, weekly = self.merge(), self.merge('1w')
        self.assertEqual(daily['candles'][0]['timestamp'], '2026-08-12T13:30:00Z')
        self.assertEqual(daily['candles'][-1]['timestamp'], '2026-11-12T14:30:00Z')
        self.assertTrue(60 <= len(daily['candles']) <= 67)
        self.assertTrue(13 <= len(weekly['candles']) <= 15)
        self.assertFalse(weekly['coverage'][0]['complete'])  # truncated first week
        self.assertFalse(weekly['coverage'][-1]['complete']) # forming last week
        week = next(c for c in weekly['candles'] if c['timestamp'] == '2026-11-02T14:30:00Z')
        rows = [r for r in fixture_rows() if '2026-11-02' <= r['date'] <= '2026-11-06']
        self.assertEqual(week['open'], rows[0]['open'])
        self.assertEqual(week['close'], rows[-1]['close'])
        self.assertEqual(week['high'], max(r['high'] for r in rows))
        self.assertEqual(week['volume'], sum(r['volume'] for r in rows))
        self.download.assert_called_once()
        cached = ProviderHistory(self.path, Mock(side_effect=AssertionError('No second download')))
        self.assertEqual(cached.merge(self.empty, self.empty, '1d', NOW)['candles'], daily['candles'])
        self.assertFalse(daily['coverage'][-1]['complete'])
        self.assertTrue(daily['coverage'][-2]['complete'])

    def test_failure_retains_cache_retries_and_reports_unavailable(self):
        self.merge()
        stored = self.path.read_text()
        self.history.next_attempt = 0
        self.download.side_effect = TimeoutError()
        result = self.merge(now=NOW + timedelta(minutes=6))
        self.assertEqual(result['historical']['status'], 'cached')
        self.assertEqual(self.path.read_text(), stored)
        self.merge(now=NOW + timedelta(minutes=7))
        self.assertEqual(self.download.call_count, 2)
        missing = ProviderHistory(self.path.with_name('missing.json'), Mock(side_effect=TimeoutError()))
        self.assertEqual(missing.merge(self.empty, self.empty, '1w', NOW)['historical']['status'], 'unavailable')
        self.history.next_attempt = 0
        self.download.side_effect = None
        self.assertEqual(self.merge(now=NOW + timedelta(minutes=8))['historical']['status'], 'ready')

    def test_live_revision_retains_provider_open_and_does_not_duplicate_day(self):
        self.merge()
        daily = self.merge()
        candle = dict(daily['candles'][-1], open=230, high=999, low=98, close=998, volume=None)
        observed = dict(candles=[candle], coverage=[daily['coverage'][-1]])
        result = self.history.merge(self.empty, observed, '1d', NOW + timedelta(seconds=10), NOW + timedelta(seconds=5))
        revised = result['candles'][-1]
        self.assertEqual(revised['open'], daily['candles'][-1]['open'])
        self.assertEqual(revised['close'], 998)
        self.assertEqual(revised['high'], 999)
        self.assertIsNone(revised['volume'])
        self.assertEqual(len(result['candles']), len(daily['candles']))

    def test_invalid_download_cannot_replace_good_cache(self):
        self.merge()
        self.history.next_attempt = 0
        self.download.return_value = [dict(fixture_rows()[-1], close=float('nan'))]
        self.assertEqual(self.merge(now=NOW + timedelta(minutes=6))['historical']['status'], 'cached')
        self.assertTrue(json.loads(self.path.read_text())['rows'])
        self.assertEqual(months_before(NOW.date().replace(month=5, day=31), 3).isoformat(), '2026-02-28')
        with self.assertRaises(ValueError):
            validate([])

    def test_intraday_live_volume_uses_observed_delta_without_adding_provider_volume(self):
        stamp = '2026-11-12T17:59:00Z'
        cached = dict(timestamp=stamp, open=100, high=103, low=99, close=101, volume=20)
        cache = ProviderHistory(self.path.with_name('minute.json'), Mock(return_value=[cached]), timeframe='1m')
        fetched = NOW - timedelta(seconds=30)
        cache.refresh(fetched)
        self.history.intraday['1m'] = cache
        candle = dict(cached, close=102, volume=12)
        status = dict(interval_end='2026-11-12T18:00:00Z', volume_scope='Observed cumulative-volume change')
        observed = dict(candles=[candle], coverage=[status])
        result = self.history.merge_intraday(observed, '1m', NOW, NOW - timedelta(seconds=5))
        self.assertEqual(result['candles'][-1]['volume'], 12)  # never 20 + 12
        self.assertEqual(result['coverage'][-1]['volume_provenance'], 'yahoo_quote_counter')
        self.assertTrue(result['coverage'][-1]['volume_known'])
        candle['volume'] = None
        result = self.history.merge_intraday(observed, '1m', NOW, NOW - timedelta(seconds=5))
        self.assertIsNone(result['candles'][-1]['volume'])
        self.assertFalse(result['coverage'][-1]['volume_known'])
        # Without a newer quote, the provider's own bar volume remains unchanged.
        result = self.history.merge_intraday(observed, '1m', NOW, fetched)
        self.assertEqual(result['candles'][-1]['volume'], 20)


if __name__ == '__main__':
    unittest.main()
