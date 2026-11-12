"""Session-aligned history derived on demand from available minute versions."""

from dataclasses import dataclass
from bisect import bisect_left
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from itertools import groupby
from calendar import monthrange
import math

from backend.candles import utc_datetime, utc_label

TIMEFRAMES = {'1m': 1, '5m': 5, '15m': 15, '30m': 30, '1h': 60, '1d': None, '1w': None, '1mo': None}


@dataclass(frozen=True)
class MinuteVersion:
    candle: dict
    available_at: datetime


@dataclass(frozen=True)
class Session:
    label: str
    opened: datetime
    closed: datetime
    minutes: tuple


@lru_cache(maxsize=16)
def exchange_sessions(name, start_date, end_date):
    try:
        import exchange_calendars as calendars
    except ImportError as error:
        raise RuntimeError('Exchange calendar dependency is missing; see docs/dependency-proposal.md') from error
    try:
        calendar = calendars.get_calendar(name, start=start_date, end=end_date)
    except Exception as error:
        raise ValueError(f'Cannot load exchange calendar {name}: {error}') from error
    sessions = []
    for label, row in calendar.schedule.iterrows():
        opened, closed = row['open'].to_pydatetime(), row['close'].to_pydatetime()
        break_start, break_end = row['break_start'], row['break_end']
        minutes = []
        current = opened
        while current < closed:
            if break_start != break_start or not (break_start <= current < break_end):
                minutes.append(current)
            current += timedelta(minutes=1)
        sessions.append(Session(str(label.date()), opened, closed, tuple(minutes)))
    return tuple(sessions)


def period_sessions(sessions, timeframe):
    if timeframe not in ('1w', '1mo'):
        return sessions

    def period(session):
        day = date.fromisoformat(session.label)
        return day.isocalendar()[:2] if timeframe == '1w' else (day.year, day.month)

    result = []
    for _, members in groupby(sessions, key=period):
        group = list(members)
        result.append(Session(group[0].label, group[0].opened, group[-1].closed,
                              tuple(minute for session in group for minute in session.minutes)))
    return tuple(result)


@lru_cache(maxsize=16)
def sessions_for_chart(calendar, timeframe, first, last):
    start, end = first - timedelta(days=2), last + timedelta(days=2)
    if timeframe == '1w':
        start -= timedelta(days=start.weekday())
        end += timedelta(days=6 - end.weekday())
    elif timeframe == '1mo':
        start = start.replace(day=1)
        end = end.replace(day=monthrange(end.year, end.month)[1])
    return period_sessions(exchange_sessions(calendar, start.isoformat(), end.isoformat()), timeframe)


def derive_timeframe(versions, timeframe='1m', *, as_of=None, calendar='NASDAQ', sessions=None):
    if timeframe not in TIMEFRAMES:
        raise ValueError('Unsupported timeframe')
    now = utc_datetime(as_of) if as_of is not None else datetime.now(UTC)
    latest = {}
    for version in versions:
        available = utc_datetime(version.available_at)
        candle = version.candle
        timestamp = utc_datetime(candle['timestamp'])
        if timestamp.second or timestamp.microsecond:
            raise ValueError('Base candle timestamp must start a minute')
        if available > now or timestamp > now:
            continue
        for field in ('open', 'high', 'low', 'close'):
            if isinstance(candle[field], bool) or not isinstance(candle[field], (int, float)) or not math.isfinite(candle[field]):
                raise ValueError(f'Invalid minute {field}')
        volume = candle['volume']
        if volume is not None and (isinstance(volume, bool) or not isinstance(volume, (int, float)) or not math.isfinite(volume) or volume < 0):
            raise ValueError('Invalid minute volume')
        if timestamp not in latest or available >= latest[timestamp][0]:
            latest[timestamp] = (available, candle)
    if sessions is None:
        if latest:
            sessions = sessions_for_chart(calendar, timeframe, min(latest).date(), max(latest).date())
        else:
            sessions = ()
    else:
        sessions = period_sessions(sessions, timeframe)
    membership = {minute: session for session in sessions for minute in session.minutes}
    groups = {}
    excluded = []
    duration = TIMEFRAMES[timeframe]
    for timestamp, (_, candle) in sorted(latest.items()):
        session = membership.get(timestamp)
        if session is None:
            excluded.append(utc_label(timestamp))
            continue
        if duration is None:
            start, end = session.opened, session.closed
        else:
            offset = int((timestamp - session.opened).total_seconds() // 60)
            start = session.opened + timedelta(minutes=(offset // duration) * duration)
            end = min(start + timedelta(minutes=duration), session.closed)
        key = (session.label, start)
        if key not in groups:
            groups[key] = (session, end, [])
        groups[key][2].append(candle)

    candles, statuses = [], []
    for (_, start), (session, end, base) in sorted(groups.items(), key=lambda item: item[0][1]):
        expected = bisect_left(session.minutes, end) - bisect_left(session.minutes, start)
        volume_known = all(c['volume'] is not None for c in base)
        label = utc_label(start)
        candles.append({
            'timestamp': label, 'open': base[0]['open'],
            'high': max(c['high'] for c in base), 'low': min(c['low'] for c in base),
            'close': base[-1]['close'],
            'volume': sum(c['volume'] for c in base) if volume_known else None,
        })
        coverage_complete = len(base) == expected
        ended = now >= end
        statuses.append({
            'timestamp': label, 'session': session.label,
            'interval_end': utc_label(end), 'expected_minutes': expected,
            'available_minutes': len(base), 'coverage_complete': coverage_complete,
            'ended': ended, 'complete': ended and coverage_complete,
            'volume_known': volume_known,
            'volume_scope': 'available constituent minutes only',
        })
    return {
        'timeframe': timeframe, 'calendar': calendar, 'as_of': utc_label(now),
        'candles': candles, 'coverage': statuses,
        'excluded_out_of_session_minutes': excluded,
    }
