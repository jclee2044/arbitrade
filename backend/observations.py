"""Immutable source observations and an ordered audit of their receipts."""

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3

DEFAULT_DATABASE = Path(__file__).resolve().parent / 'data' / 'observations.sqlite3'


class ObservationStore:
    def __init__(self, path=DEFAULT_DATABASE):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute('PRAGMA foreign_keys = ON')
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY,
                provider TEXT NOT NULL,
                ticker TEXT NOT NULL,
                source_time_json TEXT NOT NULL,
                source_time_utc TEXT,
                payload_json TEXT NOT NULL,
                supersedes_observation_id INTEGER REFERENCES observations(id),
                UNIQUE(provider, payload_json)
            );
            CREATE TABLE IF NOT EXISTS receipts (
                id INTEGER PRIMARY KEY,
                observation_id INTEGER NOT NULL REFERENCES observations(id),
                received_at_utc TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS receipts_observation
                ON receipts(observation_id);
            CREATE INDEX IF NOT EXISTS observations_source_time
                ON observations(ticker, source_time_utc);
        ''')

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def record(self, message, received_at, *, source_time_utc=None,
               provider='yahoo', supersedes_id=None):
        """An exact decoded payload repeat adds a receipt, never a new value.

        supersedes_id is only for a correction relationship established by a
        caller's feed adapter. The Yahoo receiver does not infer or supply it.
        """
        ticker = message.get('id')
        if not isinstance(ticker, str) or not ticker:
            raise ValueError('A source ticker id is required')
        if received_at.tzinfo is None or received_at.utcoffset() is None:
            raise ValueError('Receipt time must have a timezone')
        payload = json.dumps(message, sort_keys=True, separators=(',', ':'), allow_nan=False)
        source_time = json.dumps(message.get('time'), allow_nan=False)
        received_utc = received_at.astimezone(UTC).isoformat(timespec='microseconds')
        with self.connection:
            if supersedes_id is not None:
                parent = self.connection.execute(
                    'SELECT provider, ticker, payload_json FROM observations WHERE id = ?',
                    (supersedes_id,),
                ).fetchone()
                if (parent is None or parent['provider'] != provider or
                        parent['ticker'] != ticker or parent['payload_json'] == payload):
                    raise ValueError('Correction must refer to a different observation of the same provider/ticker')
            cursor = self.connection.execute('''
                INSERT INTO observations
                    (provider, ticker, source_time_json, source_time_utc,
                     payload_json, supersedes_observation_id)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, payload_json) DO NOTHING
            ''', (provider, ticker, source_time, source_time_utc, payload, supersedes_id))
            repeated = cursor.rowcount == 0
            row = self.connection.execute('''
                SELECT id, supersedes_observation_id FROM observations
                WHERE provider = ? AND payload_json = ?
            ''', (provider, payload)).fetchone()
            if supersedes_id is not None and row['supersedes_observation_id'] != supersedes_id:
                raise ValueError('Conflicting correction link for an existing immutable observation')
            receipt = self.connection.execute('''
                INSERT INTO receipts (observation_id, received_at_utc) VALUES (?, ?)
            ''', (row['id'], received_utc))
        return {'observation_id': row['id'], 'receipt_id': receipt.lastrowid, 'exact_repeat': repeated}

    def snapshot(self):
        observations = []
        for row in self.connection.execute('SELECT * FROM observations ORDER BY id'):
            item = dict(row)
            item['source_fields'] = json.loads(item.pop('payload_json'))
            observations.append(item)
        return {
            'database': str(self.path),
            'observations': observations,
            'receipts': [dict(row) for row in self.connection.execute('SELECT * FROM receipts ORDER BY id')],
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['init', 'list'])
    parser.add_argument('--database', type=Path, default=DEFAULT_DATABASE)
    args = parser.parse_args()
    if args.action == 'list' and not args.database.is_file():
        parser.error('Database does not exist; run init first')
    with ObservationStore(args.database) as store:
        print(json.dumps(store.snapshot() if args.action == 'list' else {'initialized': str(store.path)}, indent=2))


if __name__ == '__main__':
    main()
