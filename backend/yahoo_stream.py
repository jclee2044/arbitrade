"""Bounded, one-ticker Yahoo subscription check (no credentials required)."""

import argparse
import asyncio
from datetime import UTC, datetime
from importlib.metadata import version
import json
import math
from pathlib import Path
import sqlite3

from backend.observations import DEFAULT_DATABASE, ObservationStore


def describe_update(message, received_at):
    """Keep provider values and distinguish quote volume from candle volume."""
    raw_time = message.get('time')
    source_utc = None
    unit = 'unknown'
    if raw_time is not None:
        numeric_time = int(raw_time)
        # Infer contemporary Unix units from magnitude and keep the raw value.
        if 10**12 <= numeric_time < 10**14:
            unit = 'milliseconds since Unix epoch (inferred from magnitude)'
            source_utc = datetime.fromtimestamp(numeric_time / 1000, UTC).isoformat()
        elif 10**9 <= numeric_time < 10**11:
            unit = 'seconds since Unix epoch (inferred from magnitude)'
            source_utc = datetime.fromtimestamp(numeric_time, UTC).isoformat()
    volumes = {}
    meanings = {
        'day_volume': 'Cumulative provider trading-day volume, in shares for stocks.',
        'last_size': 'Size of the last trade, in shares for stocks.',
        'vol_24hr': 'Provider 24-hour volume; instrument-specific units, not one-minute volume.',
        'vol_all_currencies': 'Provider volume across currencies; units not established here.',
    }
    for field, meaning in meanings.items():
        if field in message:
            volumes[field] = {'value': message[field], 'meaning': meaning}
    return {
        'ticker': message['id'],
        'price': message['price'],
        'source_time_raw': raw_time,
        'source_time_unit': unit,
        'source_time_utc': source_utc,
        'backend_received_at_utc': received_at.isoformat(),
        'backend_receipt_time_format': 'ISO 8601 UTC, with subsecond precision',
        'volume_fields': volumes,
    }


async def check_subscription(ticker='AAPL', timeout=30, client_factory=None, recorder=None):
    if not math.isfinite(timeout) or not 0 < timeout <= 60:
        raise ValueError('Timeout must be greater than zero and at most 60 seconds')
    if client_factory is None:
        from yfinance import AsyncWebSocket
        client_factory = AsyncWebSocket

    result = {'ticker': ticker, 'connection_opened': False, 'receipt_verified': False, 'timeout_seconds': timeout}
    client = client_factory(verbose=False)
    listener = None
    first = asyncio.get_running_loop().create_future()

    def on_message(message):
        received_at = datetime.now(UTC)
        if message.get('id') != ticker or 'price' not in message or first.done():
            return
        try:
            update = describe_update(message, received_at)
            if recorder is not None:
                update['recording'] = recorder.record(
                    message, received_at, source_time_utc=update['source_time_utc'],
                )
            first.set_result(update)
        except (ValueError, TypeError, OverflowError, OSError, sqlite3.Error) as error:
            first.set_exception(error)

    async def receive():
        nonlocal listener
        await client.subscribe([ticker])
        # subscribe opens the socket before sending the subscription.
        result['connection_opened'] = True
        listener = asyncio.create_task(client.listen(on_message))
        done, _ = await asyncio.wait([first, listener], return_when=asyncio.FIRST_COMPLETED)
        if first in done:
            return first.result()
        listener.result()
        raise RuntimeError('Listener stopped before a matching update arrived')

    try:
        result['update'] = await asyncio.wait_for(receive(), timeout=timeout)
        result['receipt_verified'] = True
    except TimeoutError:
        result['status'] = 'timeout; receipt unverified'
    except Exception as error:
        result['status'] = 'error; receipt unverified'
        result['error'] = f'{type(error).__name__}: {error}'
    finally:
        if listener is not None:
            listener.cancel()
        first.cancel()
        try:
            await asyncio.wait_for(client.close(), timeout=3)
            if listener is not None:
                await asyncio.wait_for(asyncio.gather(listener, return_exceptions=True), timeout=2)
        except Exception as error:
            result['cleanup_error'] = type(error).__name__
    return result


async def listen_continuously(client, handler):
    """Consume one subscribed connection; caller owns reconnect and status.

    yfinance 1.8.0's listen() hides failures and loops on clean close. Reuse
    its subscribed transport and decoder, but return when that socket ends.
    subscribe() already maintains the provider's heartbeat subscription.
    """
    async for frame in client._ws:
        message = json.loads(frame)
        if message.get('message'):
            handler(client._decode_message(message['message']))
    raise ConnectionError('Yahoo closed its connection')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ticker', default='AAPL')
    parser.add_argument('--timeout', type=float, default=30)
    parser.add_argument('--database', type=Path, default=DEFAULT_DATABASE)
    args = parser.parse_args()
    ticker = args.ticker.strip().upper()
    if not ticker or len(ticker) > 32:
        parser.error('Supply one nonempty ticker, at most 32 characters')
    if not math.isfinite(args.timeout) or not 0 < args.timeout <= 60:
        parser.error('--timeout must be greater than zero and at most 60 seconds')
    try:
        import yfinance
        from websockets.asyncio.client import connect  # Confirm the required client API.
        print(json.dumps({'yfinance_version': yfinance.__version__, 'websockets_version': version('websockets')}), flush=True)
    except ImportError as error:
        parser.exit(1, f'Missing Yahoo dependency: {error}. See docs/dependency-proposal.md.\n')
    with ObservationStore(args.database) as recorder:
        result = asyncio.run(check_subscription(ticker, args.timeout, recorder=recorder))
        result['database'] = str(recorder.path)
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result['receipt_verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
