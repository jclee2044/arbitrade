"""Frozen regular-session Yahoo daily research data, separate from receipt replay."""
from bisect import bisect_right
from datetime import date, timedelta
from functools import cached_property, lru_cache
from hashlib import sha256
import json
import math
from pathlib import Path

from backend.candles import utc_datetime, utc_label
from backend.indicators import indicator_rows, moving_averages

HISTORY = Path(__file__).parent / 'data/research/aapl-daily-2026-11-16.json'
DIGEST = '340ffdb8ed3685fd75f7192542b37b1bfd349a427e1de3917e60570d18396b99'


class DailyHistory:
    def __init__(self, data, digest):
        import exchange_calendars
        rows = data['rows']
        first = date.fromisoformat(data['requested_start'])
        last = date.fromisoformat(data['valid_through'])
        schedule = exchange_calendars.get_calendar('NASDAQ', start=first,
            end=last + timedelta(days=14)).schedule
        sessions = schedule.loc[:last.isoformat()]
        dates = [str(index.date()) for index in sessions.index]
        if (not rows or data['interval'] != '1d' or data['calendar'] != 'NASDAQ'
                or [r['date'] for r in rows] != dates or dates[-1] != last.isoformat()):
            raise ValueError('Daily history must contain every completed session in order')
        self.symbol, self.source, self.digest = data['symbol'], data['source'], digest
        self.bars = []
        for row, (_, session) in zip(rows, sessions.iterrows()):
            o, h, l, c, v = (row[k] for k in ('open', 'high', 'low', 'close', 'volume'))
            end = session['close'].to_pydatetime()
            if (not all(type(n) in (float, int) and math.isfinite(n) for n in (o, h, l, c, v))
                    or not 0 < l <= min(o, c) <= max(o, c) <= h or v < 0 or row['stock_splits'] != 0
                    or end > utc_datetime(data['fetched_at'])):
                raise ValueError(f"Invalid, unfinished or split-affected research bar on {row['date']}")
            self.bars.append(dict(date=row['date'], timestamp=utc_label(session['open'].to_pydatetime()),
                cutoff=utc_label(end), open=o, high=h, low=l, close=c, volume=v))
        self.ends = [utc_datetime(bar['cutoff']) for bar in self.bars]
        self.expires = schedule.iloc[len(rows)]['close'].to_pydatetime()

    @cached_property
    def studies(self):
        coverage = [dict(timestamp=b['timestamp'], ended=True) for b in self.bars]
        cross = moving_averages(self.bars, coverage, 20, 50)['rows']
        sma, ema = (indicator_rows(kind, self.bars, coverage, {'window': 200}) for kind in ('sma', 'ema'))
        return [dict(sma20=row['short'], sma50=row['long'], crossover=row['signal'],
                     sma200=s['value'], ema200=e['value']) for row, s, e in zip(cross, sma, ema)]

    def index_at(self, cutoff):
        instant = utc_datetime(cutoff)
        if instant >= self.expires:
            return None
        index = bisect_right(self.ends, instant) - 1
        return index if index >= 0 else None

    def overlay(self, field, snapshot):
        as_of = utc_datetime(snapshot['as_of'])
        rows = []
        for bar in snapshot['coverage']:
            index = self.index_at(min(utc_datetime(bar['interval_end']), as_of))
            value = self.studies[index][field] if index is not None else None
            rows.append(dict(timestamp=bar['timestamp'], value=value))
        return rows


@lru_cache(maxsize=1)
def daily_history():
    raw = HISTORY.read_bytes()
    digest = sha256(raw).hexdigest()
    if digest != DIGEST:
        raise ValueError('Frozen research history checksum mismatch')
    return DailyHistory(json.loads(raw), digest)
