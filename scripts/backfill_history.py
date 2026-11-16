"""Refresh the chart caches and report the actual dates returned by Yahoo."""
from datetime import UTC, datetime
import os
from pathlib import Path

from backend.observations import DEFAULT_DATABASE
from backend.provider_history import ProviderHistory
from backend.timeframes import TIMEFRAMES


def main():
    path = Path(os.environ.get('ARBITRADE_DATABASE', DEFAULT_DATABASE))
    history = ProviderHistory(path.with_suffix('.history.json'))
    now = datetime.now(UTC)
    empty = dict(candles=[], coverage=[])
    for frame in TIMEFRAMES:
        snapshot = history.merge(empty, empty, frame, now)
        candles = snapshot['candles']
        dates = (candles[0]['timestamp'], candles[-1]['timestamp']) if candles else ()
        print(frame, snapshot['historical']['status'], len(candles), *dates, flush=True)


if __name__ == '__main__':
    main()
