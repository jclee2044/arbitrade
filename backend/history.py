"""Read the local one-minute candle source using the standard library."""

import csv
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sqlite3

from backend.candles import form_candles, utc_datetime
from backend.indicators import with_averages, DEFAULT_SHORT, DEFAULT_LONG
from backend.observations import DEFAULT_DATABASE
from backend.timeframes import MinuteVersion, derive_timeframe

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SUPPLIED_CSV = PROJECT_ROOT / "prompts" / "data" / "sample-candles.csv"
SAMPLE_CSV = Path(__file__).resolve().parent / "data" / "sample-candles.csv"
FIELDS = ["timestamp", "open", "high", "low", "close", "volume"]


def load_history(path: Path | None = None) -> list[dict[str, str | float | int]]:
    """Return numeric candles ordered by their UTC minute-start timestamps.

    Prefer a supplied prompt data file; otherwise use the synthetic sample.
    Each candle covers [timestamp, timestamp + one minute). No aggregation is
    performed here; these one-minute rows are the source for future timeframes.
    """
    if path is None:
        path = SUPPLIED_CSV if SUPPLIED_CSV.is_file() else SAMPLE_CSV

    candles = []
    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != FIELDS:
            raise ValueError(f"Expected CSV fields: {','.join(FIELDS)}")
        for row in reader:
            candles.append({
                "timestamp": row["timestamp"],
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row["volume"]),
            })

    return sorted(candles, key=lambda candle: datetime.fromisoformat(candle["timestamp"]))


def history_response(symbol='AAPL', timeframe='1m', *, as_of=None, source='sample',
                     calendar=None, database=DEFAULT_DATABASE, sessions=None,
                     short_window=DEFAULT_SHORT, long_window=DEFAULT_LONG, receipt_limit=None):
    now = utc_datetime(as_of) if as_of is not None else datetime.now(UTC)
    symbol = symbol.strip().upper()
    if not symbol:
        raise ValueError('Symbol is required')
    if calendar is None:
        if symbol != 'AAPL':
            raise ValueError('Specify an exchange calendar for symbols other than AAPL')
        calendar = 'NASDAQ'
    if source == 'sample':
        if symbol != 'AAPL':
            raise ValueError('The synthetic sample is labelled AAPL only')
        versions = [MinuteVersion(c, utc_datetime(c['timestamp']) + timedelta(minutes=1)) for c in load_history()]
        unbucketed = []
    elif source == 'observations':
        path = Path(database)
        if not path.is_file():
            raise ValueError('Observation database does not exist')
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as connection:
            base = form_candles(connection, symbol, as_of=now, available_at=now, receipt_limit=receipt_limit)
        # Snapshot is already filtered to receipts and source ticks visible at now.
        versions = [MinuteVersion(c, now) for c in base['candles']]
        unbucketed = base['unbucketed_observation_ids']
    else:
        raise ValueError('Unsupported history source')
    result = derive_timeframe(versions, timeframe, as_of=now, calendar=calendar, sessions=sessions)
    if source == 'observations':
        for status in result['coverage']:
            status.update(volume_provenance='yahoo_quote_counter',
                          volume_scope='Observed cumulative-volume change; not Yahoo reported bar volume')
    result.update(symbol=symbol, source=source, unbucketed_observation_ids=unbucketed)
    return with_averages(result, short_window, long_window)
