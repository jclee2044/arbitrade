"""Independent numerical reference and causal execution checks for frozen daily research."""
import copy
from datetime import timedelta
from fractions import Fraction
import json
from types import SimpleNamespace
import unittest

import pandas as pd

from backend.classroom_decisions import ChartCapture
from backend.daily_history import DailyHistory, HISTORY, daily_history
from backend.daily_strategy import StrategySelection, backtest, capture_facts, simulate, simulation
from backend.decision_provider import ProviderFailure
from backend.test_classroom_decisions import capture


class DailyStrategyTests(unittest.TestCase):
    def test_pandas_reference_and_incremental_prefixes(self):
        history = daily_history()
        prices = pd.Series([b['close'] for b in history.bars])
        means = {size: prices.rolling(size).mean() for size in (20, 50, 200)}
        seeded = pd.concat([means[200].iloc[199:200], prices.iloc[200:]])
        ema = seeded.ewm(span=200, adjust=False).mean()
        # Independent online oracle, updated exactly once per arriving session.
        sums = {size: Fraction(0) for size in means}
        online = []
        online_ema = None
        side = 0
        for i, row in enumerate(history.studies):
            online.append(Fraction(str(history.bars[i]['close'])))
            for size, series in means.items():
                sums[size] += online[-1]
                if len(online) > size:
                    sums[size] -= online[-size-1]
                if len(online) >= size:
                    self.assertAlmostEqual(row[f'sma{size}'], float(sums[size] / size), places=10)
                if i+1 < size:
                    self.assertIsNone(row[f'sma{size}'])
                else:
                    self.assertAlmostEqual(row[f'sma{size}'], series[i], places=10)
            if i >= 199:
                online_ema = (float(sums[200] / 200) if online_ema is None else
                              (2 * float(online[-1]) + 199 * online_ema) / 201)
                self.assertAlmostEqual(row['ema200'], online_ema, places=10)
                self.assertAlmostEqual(row['ema200'], ema[i], places=10)
            else:
                self.assertIsNone(row['ema200'])
            direction = 0 if i < 49 else (1 if means[20][i] > means[50][i] else -1 if means[20][i] < means[50][i] else 0)
            cross = ('up' if direction == 1 else 'down') if direction and side and direction != side else None
            self.assertEqual(row['crossover'], cross)
            side = direction or side
        for end in (49, 199, 200, 201, 390, 500, 750):
            prefix = copy.copy(history)
            prefix.bars = history.bars[:end]
            del prefix.studies
            self.assertEqual(prefix.studies, history.studies[:end])
            for variant in ('baseline', 'sma200', 'ema200'):
                self.assertEqual(simulate(prefix, variant).facts, simulation(variant).facts[:end])

    def test_execution_filter_independence_and_ledger(self):
        # One upward cross with close between thresholds. A second entry gaps beyond cash.
        def bar(i, o, c):
            return dict(timestamp=f'open{i}', cutoff=f'close{i}', open=o, close=c)
        series = [bar(0, 99, 100), bar(1, 110, 115), bar(2, 120, 101), bar(3, 1100, 200)]
        studies = [dict(sma20=102, sma50=101, sma200=100, ema200=99, crossover=s) for s in ('up','down','up',None)]
        h = SimpleNamespace(bars=series, studies=studies, symbol='SAMPLE', digest='fixture')
        for variant in ('baseline','ema200'):
            run = simulate(h, variant)
            self.assertEqual([o['status'] for o in run.orders], ['filled','filled','rejected'])
            self.assertEqual([o.get('fill_at') for o in run.orders[:2]], ['open1','open2'])
            self.assertEqual(run.facts[1]['unrealized'], '5')
            self.assertEqual((run.summary['cash'], run.summary['realized'], run.summary['shares']), ('1010','10',0))
        sma = simulate(h, 'sma200')
        self.assertEqual(sma.facts[0]['reason'], 'entry_filter_failed')  # Equal also fails.
        self.assertEqual(sma.facts[1]['reason'], 'no_position')
        h.bars = series[:1]
        self.assertEqual(simulate(h, 'baseline').orders[0]['status'], 'pending')

    def test_partial_bar_gaps_close_boundaries_and_stale_range(self):
        h = daily_history()
        i = next(i for i,b in enumerate(h.bars) if b['date'] == '2025-11-28')  # half-day
        at = h.ends[i]
        self.assertEqual(at.hour, 18)
        self.assertEqual(h.index_at(at - timedelta(microseconds=1)), i-1)
        self.assertEqual(h.index_at(at), i)
        self.assertIsNone(h.index_at(h.expires))
        self.assertIsNone(h.index_at(h.ends[0] - timedelta(seconds=1)))
        snapshot = dict(as_of=at - timedelta(seconds=1), coverage=[dict(timestamp='forming', interval_end=at)])
        self.assertEqual(h.overlay('ema200', snapshot)[0]['value'], h.studies[i-1]['ema200'])
        data = json.loads(HISTORY.read_text())
        data['rows'].pop(4)
        with self.assertRaises(ValueError):
            DailyHistory(data, 'fixture')
        data = json.loads(HISTORY.read_text())
        data['fetched_at'] = h.bars[-1]['timestamp']
        with self.assertRaises(ValueError):
            DailyHistory(data, 'fixture')

    def test_capture_cutoffs_and_comparison(self):
        h = daily_history()
        run = backtest('sma200')
        first = next(f for f in run['facts'] if f['reason'] == 'entry_filter_failed')
        i = h.index_at(first['cutoff'])
        def cap(**kwargs):
            return ChartCapture.model_validate(dict(capture(), **kwargs))
        selection = StrategySelection(variant='sma200', dataset_id=h.digest)
        self.assertEqual(capture_facts(cap(interval='1d', candle_timestamp=first['cutoff']), selection, 'backtest'), first)
        for mode in ('live','replay'):
            before = cap(interval='1m', candle_timestamp=first['cutoff'].replace('20:00','19:58'),
                         last_quote_at=first['cutoff'])
            self.assertEqual(capture_facts(before, selection, mode), run['facts'][i-1])
        session = cap(interval='1d', candle_timestamp=h.bars[i]['timestamp'], last_quote_at=h.bars[i]['timestamp'])
        self.assertEqual(capture_facts(session, selection, 'replay'), run['facts'][i-1])
        for c, s in [(cap(ticker='MSFT'), selection), (cap(), StrategySelection(variant='baseline')),
                     (cap(interval='1d', candle_timestamp=h.bars[2]['cutoff']), selection)]:
            with self.assertRaises(ProviderFailure):
                capture_facts(c, s, 'backtest')
        for variant in ('baseline', 'sma200', 'ema200'):
            r = simulation(variant)
            for f in r.facts:
                self.assertEqual(Fraction(f['equity']) - 1000, Fraction(f['realized']) + Fraction(f['unrealized']))
        self.assertEqual([s['fills'] for s in run['comparisons']], [15, 11, 11])
