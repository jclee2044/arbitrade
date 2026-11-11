"""Explicitly constructed observations for the seven-close SMA reference."""

from datetime import UTC, datetime, timedelta

from backend.observations import ObservationStore

CLOSES = [13, 10, 7, 13, 19, 7, 1]
# Independent hand calculation: timestamp added by reference_rows below.
EXPECTED = [(None, None, None), (11.5, None, None), (8.5, 10, None),
            (10, 10, None), (16, 13, 'up'), (13, 13, None), (4, 9, 'down')]
START = datetime(2026, 11, 10, 15, tzinfo=UTC)


def reference_rows():
    return [dict(timestamp=(START + timedelta(minutes=i)).isoformat().replace('+00:00', 'Z'),
                 short=short, long=long, signal=signal)
            for i, (short, long, signal) in enumerate(EXPECTED)]


def create_fixture(database):
    with ObservationStore(database) as store:
        for index, price in enumerate(CLOSES):
            minute = START + timedelta(minutes=index)
            source = minute + timedelta(seconds=10)
            # First six arrive at minute end. The seventh first appears forming.
            received = source if index == 6 else minute + timedelta(minutes=1)
            message = dict(id='AAPL', time=int(source.timestamp() * 1000), price=price,
                           day_volume=1000 + index * 10, test_data=True)
            store.record(message, received, source_time_utc=source.isoformat())
        # Repeat advances recorded evaluation time without adding an eighth candle.
        store.record(message, START + timedelta(minutes=7), source_time_utc=source.isoformat())
    return dict(start=(START + timedelta(minutes=1)).isoformat(),
                end=(START + timedelta(minutes=7)).isoformat())
