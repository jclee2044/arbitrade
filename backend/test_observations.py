"""Recorder checks use constructed data in disposable SQLite databases."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from backend.observations import ObservationStore


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory(prefix='arbitrade-recorder-unit-')
        self.store = ObservationStore(Path(self.directory.name) / 'test.sqlite3')
        self.message = {'id': 'AAPL', 'time': '1794234660000', 'price': 101, 'test_data': True}
        self.received = datetime(2026, 11, 9, 14, 32, tzinfo=UTC)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_repeat_and_same_timestamp_change(self):
        first = self.store.record(self.message, self.received)
        repeat = self.store.record(dict(reversed(list(self.message.items()))), self.received + timedelta(seconds=1))
        changed = self.store.record({**self.message, 'price': 102}, self.received + timedelta(seconds=2))
        self.assertEqual(first['observation_id'], repeat['observation_id'])
        self.assertTrue(repeat['exact_repeat'])
        self.assertNotEqual(first['observation_id'], changed['observation_id'])
        snapshot = self.store.snapshot()
        self.assertEqual(len(snapshot['observations']), 2)
        self.assertEqual(len(snapshot['receipts']), 3)
        self.assertEqual([o['source_fields']['price'] for o in snapshot['observations']], [101, 102])
        self.assertTrue(all(o['supersedes_observation_id'] is None for o in snapshot['observations']))

    def test_explicit_revision_preserves_previous_payload(self):
        first = self.store.record(self.message, self.received)
        self.store.record({**self.message, 'price': 102}, self.received, supersedes_id=first['observation_id'])
        rows = self.store.snapshot()['observations']
        self.assertEqual(rows[0]['source_fields']['price'], 101)
        self.assertEqual(rows[1]['supersedes_observation_id'], rows[0]['id'])

    def test_late_source_message_preserves_receipt_order(self):
        self.store.record(self.message, self.received, source_time_utc='2026-11-09T14:31:00+00:00')
        late = {**self.message, 'time': '1794234600000'}
        self.store.record(late, self.received + timedelta(seconds=1), source_time_utc='2026-11-09T14:30:00+00:00')
        snapshot = self.store.snapshot()
        self.assertEqual(snapshot['observations'][1]['source_fields'], late)
        self.assertLess(snapshot['observations'][1]['source_time_utc'], snapshot['observations'][0]['source_time_utc'])
        self.assertEqual([r['observation_id'] for r in snapshot['receipts']], [1, 2])

    def test_unrelated_revision_is_rejected_atomically(self):
        first = self.store.record(self.message, self.received)
        with self.assertRaises(ValueError):
            self.store.record({**self.message, 'id': 'MSFT'}, self.received, supersedes_id=first['observation_id'])
        self.assertEqual(len(self.store.snapshot()['receipts']), 1)

    def test_unknown_source_fields_are_preserved(self):
        message = {**self.message, 'extra': {'nested': [1, '2', None]}, 'day_volume': '1000'}
        self.store.record(message, self.received)
        self.assertEqual(self.store.snapshot()['observations'][0]['source_fields'], message)
