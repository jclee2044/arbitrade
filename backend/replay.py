"""Receipt-ordered replay; saved databases are opened strictly read-only."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3

from backend.candles import form_candles, utc_datetime
from backend.timeframes import MinuteVersion, derive_timeframe
from backend.indicators import with_averages, validate_windows, DEFAULT_SHORT, DEFAULT_LONG


def connect_readonly(database):
    return sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True)


def selections(database):
    if not Path(database).is_file():
        return []
    with closing(connect_readonly(database)) as connection:
        rows = connection.execute('''
            SELECT o.ticker, MIN(r.received_at_utc), MAX(r.received_at_utc), COUNT(*)
            FROM receipts r JOIN observations o ON o.id=r.observation_id
            WHERE o.provider='yahoo' GROUP BY o.ticker ORDER BY o.ticker
        ''')
        return [dict(symbol=r[0], start=r[1], end=r[2], receipts=r[3]) for r in rows]


class Replay:
    def __init__(self, database, symbol, start, end, timeframe='1m', calendar=None, *,
                 short_window=DEFAULT_SHORT, long_window=DEFAULT_LONG):
        validate_windows(short_window, long_window)
        self.short_window, self.long_window = short_window, long_window
        self.start, self.end = utc_datetime(start), utc_datetime(end)
        if self.end < self.start:
            raise ValueError('End must be at or after start')
        self.symbol = symbol.strip().upper()
        self.timeframe = timeframe
        self.calendar = calendar or ('NASDAQ' if self.symbol == 'AAPL' else None)
        if not self.calendar:
            raise ValueError('Specify an exchange calendar for this symbol')
        self.events = []
        if Path(database).is_file():
            with closing(connect_readonly(database)) as connection:
                for row in connection.execute('''
                    SELECT r.id,r.received_at_utc,o.id,o.provider,o.ticker,o.source_time_json,
                           o.source_time_utc,o.payload_json,o.supersedes_observation_id
                    FROM receipts r JOIN observations o ON o.id=r.observation_id
                    WHERE o.ticker=? AND o.provider='yahoo' ORDER BY r.id
                ''', (self.symbol,)):
                    if self.start <= utc_datetime(row[1]) <= self.end:
                        self.events.append(row)
        # Only this disposable derivation state is writable. Preserve original ids,
        # receipt order, payloads and correction links, including exact repeats.
        self.connection = sqlite3.connect(':memory:')
        self.connection.executescript('''
            CREATE TABLE observations (id INTEGER PRIMARY KEY, provider TEXT, ticker TEXT,
                source_time_json TEXT, source_time_utc TEXT, payload_json TEXT,
                supersedes_observation_id INTEGER);
            CREATE TABLE receipts (id INTEGER PRIMARY KEY, observation_id INTEGER, received_at_utc TEXT);
        ''')
        self.source = ('Replay · CONSTRUCTED test_data=true'
                       if any(json.loads(event[7]).get('test_data') for event in self.events)
                       else 'Replay · recorded SQLite observations')
        self.position = 0
        self.evaluation = self.start
        self.current = None

    def close(self):
        self.connection.close()

    def step(self):
        if self.position < len(self.events):
            event = self.events[self.position]
            receipt, received, observation, *fields = event
            self.connection.execute('INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?,?)', (observation, *fields))
            self.connection.execute('INSERT INTO receipts VALUES (?,?,?)', (receipt, observation, received))
            self.position += 1
            self.evaluation = max(self.evaluation, utc_datetime(received))
            self.current = dict(receipt_id=receipt, observation_id=observation,
                                received_at_utc=received, source_time_utc=event[6])
        return self.snapshot()

    def snapshot(self):
        base = form_candles(self.connection, self.symbol, as_of=self.evaluation,
                            available_at=self.evaluation)
        versions = [MinuteVersion(c, self.evaluation) for c in base['candles']]
        result = derive_timeframe(versions, self.timeframe, as_of=self.evaluation, calendar=self.calendar)
        result = with_averages(result, self.short_window, self.long_window)
        return dict(result, type='snapshot', symbol=self.symbol, interval=self.timeframe,
                    source=self.source,
                    feed=dict(status='replay', source_time_utc=(self.current or {}).get('source_time_utc')),
                    replay=dict(position=self.position, total=len(self.events), current=self.current,
                                done=self.position == len(self.events),
                                message='This selection has no recorded observations.' if not self.events else None))

    def minute_snapshot(self):
        base = form_candles(self.connection, self.symbol, as_of=self.evaluation, available_at=self.evaluation)
        versions = [MinuteVersion(c, self.evaluation) for c in base['candles']]
        result = derive_timeframe(versions, '1m', as_of=self.evaluation, calendar=self.calendar)
        return dict(result, symbol=self.symbol)
