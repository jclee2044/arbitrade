import tempfile
import unittest
from pathlib import Path
from datetime import datetime

from backend.observations import ObservationStore
from backend.replay import Replay, selections


class ReplayTests(unittest.TestCase):
    def test_same_source_time_counter_increases_only_at_its_receipt_step(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.sqlite3'
            with ObservationStore(path) as store:
                for source, received, volume in [
                    ('14:59:59', '14:59:59', 1000),
                    ('15:00:10', '15:00:11', 1004),
                    ('15:00:10', '15:00:12', 1009),
                ]:
                    store.record(dict(id='AAPL', time=source, price=100,
                                      day_volume=volume, test_data=True),
                                 datetime.fromisoformat('2026-11-10T' + received + '+00:00'),
                                 source_time_utc='2026-11-10T' + source + '+00:00')
                before = store.snapshot()
            bounds = selections(path)[0]
            replay = Replay(path, 'AAPL', bounds['start'], bounds['end'])
            try:
                replay.step()
                self.assertEqual(replay.step()['candles'][-1]['volume'], 4)
                self.assertEqual(replay.step()['candles'][-1]['volume'], 9)
            finally:
                replay.close()
            with ObservationStore(path) as store:
                self.assertEqual(store.snapshot(), before)

    def test_arrival_order_revision_repeat_and_readonly(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.sqlite3'
            with ObservationStore(path) as store:
                def add(source, received, price, total, supersedes=None):
                    return store.record(dict(id='AAPL', time=source, price=price, day_volume=total,
                                             test_data=True), datetime.fromisoformat(received),
                                        source_time_utc=source, supersedes_id=supersedes)
                add('2026-11-10T14:59:59+00:00', '2026-11-10T14:59:59+00:00', 99, 1000)
                first = add('2026-11-10T15:00:10+00:00', '2026-11-10T15:00:11+00:00', 100, 1004)
                add('2026-11-10T15:00:40+00:00', '2026-11-10T15:00:41+00:00', 103, 1011)
                add('2026-11-10T15:00:10+00:00', '2026-11-10T15:01:01+00:00', 98, 1004, first['observation_id'])
                add('2026-11-10T15:00:40+00:00', '2026-11-10T15:01:02+00:00', 103, 1011)
                before = store.snapshot()
            bounds = selections(path)[0]
            results = []
            for _ in range(2):
                replay = Replay(path, 'AAPL', bounds['start'], bounds['end'])
                try:
                    frames = [replay.step() for _ in range(5)]
                    self.assertEqual(frames[1]['candles'][-1]['close'], 100)
                    self.assertEqual(frames[2]['candles'][-1]['open'], 100)
                    self.assertEqual(frames[3]['candles'][-1]['open'], 98)
                    self.assertEqual(frames[-1]['candles'][-1]['close'], 103)
                    self.assertEqual(frames[-1]['candles'][-1]['volume'], 11)
                    self.assertTrue(frames[-1]['replay']['done'])
                    results.append(frames)
                finally:
                    replay.close()
            self.assertEqual(*results)
            with ObservationStore(path) as store:
                self.assertEqual(before, store.snapshot())
            empty = Replay(path, 'AAPL', '2020-01-01T00:00:00Z', '2020-01-02T00:00:00Z')
            self.assertIn('no recorded observations', empty.snapshot()['replay']['message'])
            empty.close()
            with self.assertRaises(ValueError):
                Replay(path, 'AAPL', bounds['end'], bounds['start'])
