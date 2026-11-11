"""Reference SMA arithmetic, completion, precision and receipt-aware revisions."""

from datetime import timedelta
from pathlib import Path
import tempfile
import unittest

from backend.history import history_response
from backend.indicators import moving_averages, validate_windows
from backend.observations import ObservationStore
from backend.replay import Replay
from scripts.sma_fixture import create_fixture, reference_rows, START, CLOSES


def inputs(closes):
    rows = [dict(timestamp=(START + timedelta(minutes=i)).isoformat(), close=price)
            for i, price in enumerate(closes)]
    return rows, [dict(timestamp=row['timestamp'], ended=True) for row in rows]


class IndicatorTests(unittest.TestCase):
    def test_hand_calculation_and_every_completed_prefix(self):
        rows, coverage = inputs(CLOSES)
        expected = reference_rows()
        # Inputs use +00:00; indicators preserve timestamps exactly.
        expected = [dict(row, timestamp=rows[i]['timestamp']) for i, row in enumerate(expected)]
        batch = moving_averages(rows, coverage, 2, 3)['rows']
        self.assertEqual(batch, expected)
        for count in range(1, 8):
            self.assertEqual(moving_averages(rows[:count], coverage[:count], 2, 3)['rows'], batch[:count])
        coverage[-1]['ended'] = False
        forming = moving_averages(rows, coverage, 2, 3)['rows']
        self.assertEqual(forming[:-1], batch[:-1])
        self.assertEqual(forming[-1], dict(timestamp=rows[-1]['timestamp'], short=None, long=None, signal=None))

    def test_initial_ties_first_side_and_unrounded_comparison(self):
        rows, coverage = inputs([1, 1, 1, 2, 1])
        result = moving_averages(rows, coverage, 1, 2)['rows']
        self.assertEqual([r['signal'] for r in result], [None, None, None, None, 'down'])
        # These averages display as 1.000000 but their exact sides differ.
        rows, coverage = inputs([1.00000004, 1.00000002, 1.00000003])
        result = moving_averages(rows, coverage, 1, 2)['rows']
        self.assertEqual(result[-1]['signal'], 'up')
        # Exact decimal tie: binary floating addition must not invent a side.
        rows, coverage = inputs([0.1, 0.3, 0.2])
        result = moving_averages(rows, coverage, 1, 3)['rows']
        self.assertIsNone(result[-1]['signal'])
        self.assertEqual(result[-1]['short'], result[-1]['long'])

    def test_invalid_windows(self):
        for short, long in [(0, 3), (-1, 3), (3, 3), (4, 3), (1.5, 3), (True, 3), (2, '3')]:
            with self.subTest(short=short, long=long), self.assertRaises(ValueError):
                validate_windows(short, long)
        validate_windows(1, 2)

    def test_sqlite_replay_batch_forming_and_late_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / 'constructed.sqlite3'
            bounds = create_fixture(database)
            before = database.read_bytes()
            batch = history_response(source='observations', database=database, as_of=bounds['end'],
                                     short_window=2, long_window=3)['moving_averages']['rows']
            self.assertEqual(batch, reference_rows())
            replay = Replay(database, 'AAPL', **bounds, short_window=2, long_window=3)
            try:
                for count in range(1, 7):
                    frame = replay.step()
                    self.assertEqual(frame['moving_averages']['rows'], batch[:count])
                forming = replay.step()['moving_averages']['rows']
                self.assertEqual(forming[:-1], batch[:-1])
                self.assertEqual(forming[-1], dict(timestamp=batch[-1]['timestamp'], short=None, long=None, signal=None))
                self.assertEqual(replay.step()['moving_averages']['rows'], batch)
            finally:
                replay.close()
            self.assertEqual(before, database.read_bytes())
            # Correction isn't available until its own receipt, then all affected
            # averages and historical markers must be recomputed from that state.
            source = START + timedelta(minutes=4, seconds=10)
            with ObservationStore(database) as store:
                store.record(dict(id='AAPL', time=int(source.timestamp()*1000), price=1,
                                  day_volume=1040, test_data=True), START + timedelta(minutes=8),
                             source_time_utc=source.isoformat(), supersedes_id=5)
            replay = Replay(database, 'AAPL', bounds['start'], (START+timedelta(minutes=8)).isoformat(),
                            short_window=2, long_window=3)
            try:
                for _ in range(8):
                    prior = replay.step()
                self.assertEqual(prior['moving_averages']['rows'], batch)
                revised = replay.step()['moving_averages']['rows']
                self.assertIsNone(revised[4]['signal'])
                self.assertEqual(revised[6]['signal'], 'up')
                self.assertEqual(revised[6]['long'], 3)
            finally:
                replay.close()
