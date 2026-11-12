"""Shared indicator contract, independent persisted settings and range reference."""

from fractions import Fraction
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from backend.indicators import (INDICATOR_TYPES, IndicatorType, indicator_rows,
                                moving_averages, configured_indicators, validate_settings)
from backend.indicator_store import IndicatorStore


def reference():
    candles = [dict(timestamp=f'2026-11-10T15:0{i}:00Z', open=low, high=high, low=low,
                    close=high, volume=None) for i, (high, low) in enumerate([(12, 9), (15, 10), (13, 11)])]
    coverage = [dict(timestamp=c['timestamp'], ended=True) for c in candles]
    return candles, coverage


class IndicatorInstanceTests(unittest.TestCase):
    def test_window_edit_persists_without_changing_other_instances(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.sqlite3'
            store = IndicatorStore(path)
            first = store.create('AAPL', '1m', 'Edited', 'sma', {'window': 2})
            other = store.create('AAPL', '1m', 'Unchanged', 'sma', {'window': 2})
            store.update_settings(first['id'], {'window': 3})
            reopened = IndicatorStore(path)
            rows = reopened.list('AAPL', '1m')
            self.assertEqual(rows[0], dict(first, settings={'window': 3}))
            self.assertEqual(rows[1], other)
            for invalid in (0, -1, 1.5, True):
                with self.assertRaises(ValueError):
                    reopened.update_settings(first['id'], {'window': invalid})
                self.assertEqual(reopened.list('AAPL', '1m'), rows)
            with self.assertRaisesRegex(ValueError, 'not found'):
                reopened.update_settings(999, {'window': 3})

    def test_range_warmup_completion_and_independence(self):
        candles, coverage = reference()
        self.assertEqual([r['value'] for r in indicator_rows('price_range', candles, coverage, {'window': 2})], [None, 6, 5])
        self.assertEqual([r['value'] for r in indicator_rows('price_range', candles, coverage, {'window': 3})], [None, None, 6])
        coverage[-1]['ended'] = False
        self.assertIsNone(indicator_rows('price_range', candles, coverage, {'window': 2})[-1]['value'])
        self.assertIsNone(indicator_rows('price_range', candles, coverage, {'window': 3})[-1]['value'])
        coverage[-1]['ended'] = True
        candles[0]['low'] = 8  # A revision affects window 3, not window 2 at the last candle.
        self.assertEqual(indicator_rows('price_range', candles, coverage, {'window': 2})[-1]['value'], 5)
        self.assertEqual(indicator_rows('price_range', candles, coverage, {'window': 3})[-1]['value'], 7)

    def test_ema_seeds_on_completed_closes_and_recomputes_after_a_revision(self):
        candles, coverage = reference()
        for candle, close in zip(candles, (10, 14, 21)):
            candle['close'] = close
        def result():
            return [r['value'] for r in indicator_rows('ema', candles, coverage, {'window': 2})]
        self.assertEqual(result(), [None, 12, 18])
        coverage[-1]['ended'] = False
        self.assertEqual(result(), [None, 12, None])
        coverage[-1]['ended'] = True
        candles[0]['close'] = 16
        self.assertEqual(result(), [None, 15, 19])

    def test_preset_choices_survive_reopening_and_are_independent_of_named_studies(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'charts.sqlite3'
            store = IndicatorStore(path)
            named = store.create('AAPL', '1m', 'SMA 20', 'sma', {'window': 20})
            initial = store.presets('AAPL', '1m')
            store.set_preset('AAPL', '1m', 'ema', 100, True)
            store.set_preset('AAPL', '1m', 'sma', 20, False)
            store.set_preset('AAPL', '1m', 'ema', 100, True)
            reopened = IndicatorStore(path)
            self.assertEqual([p['id'] for p in reopened.presets('AAPL','1m')], ['sma-200','ema-30','ema-100'])
            self.assertEqual(reopened.list('AAPL','1m'), [named])
            self.assertEqual(reopened.presets('AAPL','1w'), initial)

    def test_sma_uses_same_contract_and_registry_can_extend(self):
        candles, coverage = reference()
        generic = indicator_rows('sma', candles, coverage, {'window': 2})
        pair = moving_averages(candles, coverage, 2, 3)
        self.assertEqual([r['value'] for r in generic], [r['short'] for r in pair['rows']])
        third = IndicatorType('Constant', 'Contract test', 'test units', 'separate', {},
                              lambda completed, settings: [Fraction(7) for _ in completed])
        with patch.dict(INDICATOR_TYPES, {'constant': third}):
            result = configured_indicators(dict(candles=candles, coverage=coverage),
                                          [dict(id=1, name='Third type', type='constant', settings={})])
            self.assertEqual([r['value'] for r in result[0]['rows']], [7, 7, 7])

    def test_invalid_settings_rejected(self):
        for settings in ({'window': 0}, {'window': -1}, {'window': 1.5}, {'window': True},
                         {'window': '2'}, {}, {'window': 2, 'extra': 1}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                validate_settings('price_range', settings)
        with self.assertRaises(ValueError):
            validate_settings('unknown', {'window': 2})

    def test_store_survives_reopen_scopes_and_atomic_invalid_create(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'chart-config.sqlite3'
            store = IndicatorStore(path)
            shared = {'window': 2}
            store.create('AAPL', '1m', 'Range 2', 'price_range', shared)
            shared['window'] = 999
            store.create('AAPL', '1m', 'Range 3', 'price_range', {'window': 3})
            reopened = IndicatorStore(path)
            before = reopened.list('AAPL', '1m')
            self.assertEqual([item['settings']['window'] for item in before], [2, 3])
            self.assertEqual(reopened.list('AAPL', '5m'), [])
            self.assertEqual(reopened.list('MSFT', '1m'), [])
            for name, kind, settings in [('Zero', 'price_range', {'window': 0}), ('', 'sma', {'window': 2}),
                                         ('Unknown', 'unknown', {'window': 2})]:
                with self.assertRaises(ValueError):
                    reopened.create('AAPL', '1m', name, kind, settings)
            with self.assertRaises(sqlite3.IntegrityError):
                reopened.create('AAPL', '1m', 'Range 2', 'price_range', {'window': 10})
            self.assertEqual(before, reopened.list('AAPL', '1m'))
            candles, coverage = reference()
            calculated = configured_indicators(dict(candles=candles, coverage=coverage), before)
            self.assertEqual([item['rows'][-1]['value'] for item in calculated], [5, 6])
