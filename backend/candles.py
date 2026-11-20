"""Recompute UTC one-minute candles from distinct saved source observations."""

import argparse
from collections import defaultdict
from contextlib import closing
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
import json
import math
from pathlib import Path
import sqlite3

from backend.observations import DEFAULT_DATABASE


def utc_datetime(value):
    result = datetime.fromisoformat(value) if isinstance(value, str) else value
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('A timezone-aware time is required')
    return result.astimezone(UTC)


def utc_label(value):
    return value.isoformat().replace('+00:00', 'Z')


def cumulative_volume(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
        if number.is_finite() and number >= 0 and number == number.to_integral_value():
            return int(number)
    except (InvalidOperation, ValueError):
        pass
    return None


def minute_volume(baseline, rows):
    if baseline is None:
        return None, 'missing cumulative-volume baseline before minute'
    minute = rows[0]['time'].replace(second=0, microsecond=0)
    if baseline['time'] < minute - timedelta(minutes=1):
        return None, 'no cumulative-volume baseline in immediately preceding minute'
    sequence = [baseline, *rows]
    session_ids = [row['payload'].get('session_id') for row in sequence]
    if any(value is not None for value in session_ids):
        if any(value is None for value in session_ids) or any(value != session_ids[0] for value in session_ids):
            return None, 'session changed or session identity is incomplete'
    elif any(row['time'].date() != rows[0]['time'].date() for row in sequence):
        return None, 'baseline crosses UTC date without an explicit shared session id'
    totals = [cumulative_volume(row['payload'].get('day_volume')) for row in sequence]
    if any(total is None for total in totals):
        return None, 'missing or invalid cumulative-volume value'
    # Several received updates can share the provider's source timestamp.
    # A nondecreasing counter still has an unambiguous observed delta; no
    # observation is superseded, and this is not exchange-reported bar volume.
    if any(current < previous for previous, current in zip(totals, totals[1:])):
        return None, 'cumulative total reset or decreased'
    return totals[-1] - totals[0], 'last cumulative total minus pre-minute baseline'


def form_candles(connection, ticker, *, as_of=None, provider='yahoo', available_at=None, receipt_limit=None,
                 quote_filter=None):
    """Return six-field candles plus separate status metadata.

    as_of evaluates minute end. By default all saved rows are considered;
    available_at additionally restricts receipts, source times, and effective
    correction links for replay. receipt_limit additionally caps arrival IDs,
    including when receipts share timestamps. The history service sets its cutoff.
    quote_filter can restrict which decoded observations contribute to the candles.
    """
    now = utc_datetime(as_of) if as_of is not None else datetime.now(UTC)
    cursor = connection.execute('''
        SELECT o.id, o.source_time_utc, o.payload_json, o.supersedes_observation_id,
               (SELECT MIN(r.id) FROM receipts r WHERE r.observation_id = o.id AND (? IS NULL OR r.id <= ?)) AS first_receipt,
               (SELECT MIN(r.received_at_utc) FROM receipts r WHERE r.observation_id = o.id AND (? IS NULL OR r.id <= ?)) AS first_received
        FROM observations o
        WHERE o.ticker = ? AND o.provider = ?
    ''', (receipt_limit, receipt_limit, receipt_limit, receipt_limit, ticker, provider))
    columns = [column[0] for column in cursor.description]
    rows = []
    unbucketed = []
    visible = []
    cutoff = utc_datetime(available_at) if available_at is not None else None
    for values in cursor:
        row = dict(zip(columns, values))
        if receipt_limit is not None and row['first_receipt'] is None:
            continue
        if cutoff is not None:
            if row['first_received'] is None or utc_datetime(row['first_received']) > cutoff:
                continue
            if row['source_time_utc'] is not None and utc_datetime(row['source_time_utc']) > cutoff:
                continue
        row['payload'] = json.loads(row['payload_json'])
        if quote_filter is None or quote_filter(row['payload']):
            visible.append(row)
    superseded = {row['supersedes_observation_id'] for row in visible}
    for row in visible:
        if row['id'] in superseded:
            continue
        if row['source_time_utc'] is None:
            unbucketed.append(row['id'])
            continue
        row['time'] = utc_datetime(row['source_time_utc'])
        price = row['payload'].get('price')
        if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price):
            raise ValueError(f"Invalid price in observation {row['id']}")
        rows.append(row)
    rows.sort(key=lambda row: (row['time'], row['first_receipt'] or row['id'], row['id']))
    buckets = defaultdict(list)
    totals_by_time = defaultdict(list)
    for row in rows:
        buckets[row['time'].replace(second=0, microsecond=0)].append(row)
        totals_by_time[row['time']].append(cumulative_volume(row['payload'].get('day_volume')))

    candles = []
    statuses = []
    baseline = None
    for minute, bucket in sorted(buckets.items()):
        prices = [row['payload']['price'] for row in bucket]
        volume, reason = minute_volume(baseline, bucket)
        # Include all observations tied at the preceding baseline timestamp.
        if baseline is not None:
            tied = totals_by_time[baseline['time']]
            if (any(value is None for value in tied)
                    or any(current < previous for previous, current in zip(tied, tied[1:]))):
                volume, reason = None, 'ambiguous pre-minute cumulative-volume baseline'
        label = utc_label(minute)
        candles.append({
            'timestamp': label,
            'open': prices[0], 'high': max(prices), 'low': min(prices),
            'close': prices[-1], 'volume': volume,
        })
        prices_by_time = defaultdict(set)
        for row in bucket:
            prices_by_time[row['time']].add(row['payload']['price'])
        statuses.append({
            'timestamp': label,
            'ended': now >= minute + timedelta(minutes=1),
            'volume_known': volume is not None,
            'volume_reason': reason,
            'price_order_ambiguous': any(len(values) > 1 for values in prices_by_time.values()),
        })
        baseline = bucket[-1]
    return {
        'ticker': ticker, 'provider': provider, 'as_of': utc_label(now),
        'candles': candles, 'minute_status': statuses,
        'unbucketed_observation_ids': sorted(unbucketed),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ticker', default='AAPL')
    parser.add_argument('--database', type=Path, default=DEFAULT_DATABASE)
    parser.add_argument('--as-of', help='Timezone-aware ISO 8601 time used only to evaluate minute end')
    parser.add_argument('--provider', default='yahoo')
    args = parser.parse_args()
    if not args.database.is_file():
        parser.error('Database does not exist; initialize it with backend.observations first')
    # Aggregation never creates a database, migrates a schema, or writes candles.
    with closing(sqlite3.connect(args.database.resolve().as_uri() + '?mode=ro', uri=True)) as connection:
        try:
            result = form_candles(connection, args.ticker, as_of=args.as_of, provider=args.provider)
        except ValueError as error:
            parser.error(str(error))
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
