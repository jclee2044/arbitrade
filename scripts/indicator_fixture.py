"""Clearly labeled three-candle high/low fixture, never production observations."""

from datetime import UTC, datetime, timedelta
from backend.observations import ObservationStore


def create_fixture(database):
    start = datetime(2026, 11, 10, 15, tzinfo=UTC)
    with ObservationStore(database) as store:
        for index, (high, low) in enumerate([(12, 9), (15, 10), (13, 11)]):
            minute = start + timedelta(minutes=index)
            for offset, price in [(10, low), (40, high)]:
                source = minute + timedelta(seconds=offset)
                received = minute + timedelta(seconds=11) if offset == 10 else minute + timedelta(minutes=1)
                store.record(dict(id='AAPL', time=int(source.timestamp()*1000), price=price,
                                  test_data=True), received, source_time_utc=source.isoformat())
    return dict(start=(start+timedelta(seconds=11)).isoformat(),
                end=(start+timedelta(minutes=3)).isoformat())
