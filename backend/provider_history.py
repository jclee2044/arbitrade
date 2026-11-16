"""Cached Yahoo OHLCV for live charts."""
from calendar import monthrange
from datetime import UTC, date, datetime, timedelta
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo
from tempfile import NamedTemporaryFile
from threading import Lock, Thread
import time

from backend.candles import utc_label
from backend.timeframes import TIMEFRAMES, exchange_sessions, sessions_for_chart


MARKET_ZONE = ZoneInfo("America/New_York")
HISTORY_MONTHS = 3


def months_before(day, months):
    index = day.year * 12 + day.month - 1 - months
    year, month = divmod(index, 12)
    return date(year, month + 1, min(day.day, monthrange(year, month + 1)[1]))


def download_daily():
    import yfinance as yf
    frame = yf.Ticker('AAPL').history(period='6mo', interval='1d', auto_adjust=False,
                                     actions=False, prepost=False, timeout=10, raise_errors=True)
    return [dict(date=str(index.date()), **{
        key: float(row[column]) for key, column in
        [('open', 'Open'), ('high', 'High'), ('low', 'Low'), ('close', 'Close'), ('volume', 'Volume')]
    }) for index, row in frame.iterrows()]


def validate(rows, key="date"):
    if not rows:
        raise ValueError('Empty price history')
    result = {}
    for row in rows:
        if key == 'date':
            date.fromisoformat(row[key])
        else:
            stamp = datetime.fromisoformat(row[key])
            if stamp.tzinfo is None or stamp.second or stamp.microsecond:
                raise ValueError('Invalid bar timestamp')
        values = [row[k] for k in ('open', 'high', 'low', 'close', 'volume')]
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
            raise ValueError('Invalid historical price or volume')
        if min(values[:4]) <= 0 or row['volume'] < 0 or not (
            row['low'] <= min(row['open'], row['close']) <= max(row['open'], row['close']) <= row['high']
        ):
            raise ValueError('Invalid historical OHLCV')
        result[row[key]] = dict(row)
    return [result[day] for day in sorted(result)]


def download_intraday(timeframe, earliest=None):
    import yfinance as yf
    # Yahoo has different retention limits for each native resolution.
    period = '8d' if timeframe == '1m' else '6mo' if timeframe == '1h' else '60d'
    ticker = yf.Ticker('AAPL')
    settings = dict(interval=timeframe, auto_adjust=False, actions=False, prepost=False,
                    timeout=10, raise_errors=True)
    frame = ticker.history(period=period, **settings)
    rows = intraday_rows(frame)
    if timeframe == '1m' and rows:
        # Older minute data is accessible only in requests of at most eight days.
        oldest = datetime.now(MARKET_ZONE).date() - timedelta(days=29)
        end = date.fromisoformat(rows[0]['timestamp'][:10])
        if earliest and earliest <= oldest + timedelta(days=3):
            return rows
        while end > oldest:
            start = max(oldest, end - timedelta(days=7))
            rows.extend(intraday_rows(ticker.history(start=start, end=end, **settings)))
            end = start
    return rows


def intraday_rows(frame):
    return [dict(timestamp=utc_label(index.to_pydatetime().astimezone(UTC)),
                 open=float(row.Open), high=float(row.High), low=float(row.Low),
                 close=float(row.Close), volume=float(row.Volume)) for index, row in frame.iterrows()]


class ProviderHistory:
    def __init__(self, path, downloader=None, *, timeframe=None, background=False):
        self.background = background
        self.schedule_lock = Lock()
        self.worker = None
        self.timeframe = timeframe
        self.key = "timestamp" if timeframe else "date"
        self.intraday = {}
        self.path = Path(path)
        self.downloader = downloader or (self.fetch_intraday if timeframe else download_daily)
        self.lock = Lock()
        self.rows = []
        self.fetched_at = None
        self.next_attempt = 0
        self.error = None
        try:
            cached = json.loads(self.path.read_text())
            self.rows = validate(cached['rows'], self.key)
            self.fetched_at = datetime.fromisoformat(cached['fetched_at'])
        except (OSError, ValueError, KeyError, TypeError):
            self.rows = []
            self.fetched_at = None

    def fetch_intraday(self):
        earliest = date.fromisoformat(self.rows[0]['timestamp'][:10]) if self.rows else None
        return download_intraday(self.timeframe, earliest)

    def refresh(self, now):
        if self.background and self.rows:
            with self.schedule_lock:
                if time.monotonic() < self.next_attempt or (self.worker and self.worker.is_alive()):
                    return
                if self.fetched_at and timedelta(0) <= now - self.fetched_at < timedelta(minutes=5):
                    return
                self.worker = Thread(target=self._refresh, args=(now,), daemon=True)
                self.worker.start()
            return
        self._refresh(now)

    def _refresh(self, now):
        with self.lock:
            if time.monotonic() < self.next_attempt:
                return
            if self.fetched_at and timedelta(0) <= now - self.fetched_at < timedelta(minutes=5):
                return
            self.next_attempt = time.monotonic() + 60
            try:
                rows = validate(self.downloader(), self.key)
                if date.fromisoformat(rows[-1][self.key][:10]) < now.date() - timedelta(days=7):
                    raise ValueError('Provider returned outdated history')
                if self.timeframe:
                    cutoff = months_before(now.astimezone(MARKET_ZONE).date(), HISTORY_MONTHS).isoformat()
                    merged = {r[self.key]: r for r in self.rows + rows if r[self.key][:10] >= cutoff}
                    rows = [merged[t] for t in sorted(merged)]
                # Atomic local cache; download failures never overwrite good data.
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with NamedTemporaryFile('w', dir=self.path.parent, suffix='.history.tmp', delete=False) as temporary:
                    json.dump(dict(rows=rows, fetched_at=now.isoformat()), temporary, allow_nan=False)
                Path(temporary.name).replace(self.path)
                self.rows, self.fetched_at, self.error = rows, now, None
                self.next_attempt = time.monotonic() + 300
            except Exception as error:
                # Avoid logging provider payloads, URLs or credentials.
                self.error = type(error).__name__

    def merge_intraday(self, observed, timeframe, now, latest_source):
        with self.schedule_lock:
            if timeframe not in self.intraday:
                path = self.path.with_name(f'{self.path.stem}.{timeframe}.history.json')
                self.intraday[timeframe] = ProviderHistory(path, timeframe=timeframe, background=self.background)
            cache = self.intraday[timeframe]
        cache.refresh(now)
        start = months_before(now.astimezone(MARKET_ZONE).date(), HISTORY_MONTHS)
        sessions = {s.label: s for s in sessions_for_chart('NASDAQ', timeframe, start, now.date())}
        bars = {}
        duration = timedelta(minutes=TIMEFRAMES[timeframe])
        for candle in cache.rows:
            stamp = candle['timestamp']
            opened = datetime.fromisoformat(stamp)
            session = sessions.get(stamp[:10])
            if (opened.date() < start or not session or opened > now
                    or not session.opened <= opened < session.closed
                    or (opened - session.opened) % duration):
                continue
            end = min(session.closed, opened + duration)
            complete = cache.fetched_at is not None and cache.fetched_at >= end
            status = dict(timestamp=stamp, session=session.label, interval_end=utc_label(end),
                          expected_minutes=int((end-opened).total_seconds()//60), available_minutes=None,
                          coverage_complete=complete, ended=now >= end, complete=complete,
                          volume_known=True, volume_scope='Yahoo intraday bar', provenance='yahoo_intraday')
            bars[stamp] = candle, status
        for candle, status in zip(observed['candles'], observed['coverage']):
            stamp = candle['timestamp']
            if stamp[:10] < start.isoformat():
                continue
            if stamp not in bars:
                bars[stamp] = candle, status
            elif (latest_source and cache.fetched_at and latest_source > cache.fetched_at
                  and datetime.fromisoformat(stamp) <= latest_source < datetime.fromisoformat(status['interval_end'])):
                base, coverage = bars[stamp]
                bars[stamp] = (dict(base, high=max(base['high'], candle['high']), low=min(base['low'], candle['low']),
                                    close=candle['close'], volume=candle['volume']),
                               dict(coverage, volume_known=candle['volume'] is not None,
                                    volume_scope=status.get('volume_scope', 'Observed cumulative-volume change'),
                                    volume_provenance='yahoo_quote_counter'))
        ordered = [bars[t] for t in sorted(bars)]
        return dict(observed, candles=[c for c, _ in ordered], coverage=[s for _, s in ordered],
                    historical=dict(months=HISTORY_MONTHS, status='unavailable' if not cache.rows else 'cached' if cache.error else 'ready'),
                    source='Yahoo Finance · historical intraday prices + stored observations')

    def merge(self, observed, daily, timeframe, now, latest_source=None):
        if TIMEFRAMES[timeframe]:
            return self.merge_intraday(observed, timeframe, now, latest_source)
        self.refresh(now)
        start = months_before(now.astimezone(MARKET_ZONE).date(), HISTORY_MONTHS)
        sessions = sessions_for_chart('NASDAQ', timeframe, start, now.date())
        individual = exchange_sessions('NASDAQ', sessions[0].opened.date().isoformat(),
                                       sessions[-1].closed.date().isoformat())
        day_sessions = {s.label: s for s in individual}
        rows = {}
        statuses = {}
        for row in self.rows:
            session = day_sessions.get(row['date'])
            if not session or session.opened > now or row['date'] < start.isoformat():
                continue
            stamp = utc_label(session.opened)
            rows[stamp] = {k: row[k] for k in ('open', 'high', 'low', 'close', 'volume')}
            rows[stamp]['timestamp'] = stamp
            ended = now >= session.closed
            confirmed = ended and self.fetched_at is not None and self.fetched_at >= session.closed
            # Daily provider bars do not prove receipt/minute coverage.
            statuses[stamp] = dict(timestamp=stamp, session=session.label,
                interval_end=utc_label(session.closed), expected_minutes=len(session.minutes),
                available_minutes=None, coverage_complete=confirmed, ended=ended, complete=confirmed,
                volume_known=True, volume_scope='Yahoo daily bar', provenance='yahoo_daily')
        for candle, status in zip(daily['candles'], daily['coverage']):
            stamp = candle['timestamp']
            if stamp[:10] < start.isoformat():
                continue
            if stamp not in rows:
                rows[stamp], statuses[stamp] = dict(candle), dict(status)
            elif (not statuses[stamp]['ended'] and latest_source and self.fetched_at
                  and latest_source > self.fetched_at
                  and datetime.fromisoformat(stamp) <= latest_source < datetime.fromisoformat(statuses[stamp]['interval_end'])):
                # Retain the full provider open/extremes; replace only the forming
                # session's close with newer recorded regular-session data.
                row = rows[stamp]
                row.update(high=max(row['high'], candle['high']), low=min(row['low'], candle['low']),
                           close=candle['close'], volume=None)
                statuses[stamp].update(volume_known=False, volume_scope='Unavailable after live revision')
        candles, coverage = [], []
        for session in sessions:
            members = sorted(stamp for stamp in rows if session.opened <= datetime.fromisoformat(stamp) < session.closed)
            if not members:
                continue
            group = [rows[stamp] for stamp in members]
            stamp = utc_label(session.opened)
            known = all(c['volume'] is not None for c in group)
            candles.append(dict(timestamp=stamp, open=group[0]['open'], high=max(c['high'] for c in group),
                low=min(c['low'] for c in group), close=group[-1]['close'],
                volume=sum(c['volume'] for c in group) if known else None))
            expected_days = [s for s in individual if session.opened <= s.opened < session.closed]
            complete = len(members) == len(expected_days) and all(statuses[s]['complete'] for s in members)
            ended = now >= session.closed
            coverage.append(dict(timestamp=stamp, session=session.label, interval_end=utc_label(session.closed),
                expected_minutes=len(session.minutes), available_minutes=None, coverage_complete=complete,
                ended=ended, complete=ended and complete, volume_known=known,
                volume_scope='Available daily bars', provenance='yahoo_daily_and_observations'))
        return dict(observed, candles=candles, coverage=coverage,
            historical=dict(status='unavailable' if not self.rows else 'cached' if self.error else 'ready',
                            error=self.error, fetched_at=self.fetched_at.isoformat() if self.fetched_at else None,
                            months=HISTORY_MONTHS),
            source='Yahoo Finance · historical daily prices + stored observations')
