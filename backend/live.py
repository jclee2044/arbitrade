"""One shared Yahoo subscription; durable quotes precede derived chart updates."""

import asyncio
import json
from contextlib import suppress
from datetime import UTC, datetime

from backend.history import history_response
from backend.observations import DEFAULT_DATABASE, ObservationStore
from backend.yahoo_stream import describe_update, listen_continuously


class LiveFeed:
    def __init__(self, database=DEFAULT_DATABASE, client_factory=None):
        self.database = database
        self.client_factory = client_factory
        self.client = None
        self.task = None
        self.status = 'connecting'
        self.latest = None
        self.recording = None
        self.error = None
        self.on_record = None
        self.source = 'Yahoo Finance · stored observations'

    def accept(self, message, store):
        if message.get('id') != 'AAPL' or 'price' not in message:
            return
        received = datetime.now(UTC)
        update = describe_update(message, received)
        self.recording = store.record(message, received, source_time_utc=update['source_time_utc'])
        self.latest = update
        self.error = None
        self.status = 'live'
        if self.on_record:
            self.on_record()

    def feed_state(self):
        source_time = self.latest['source_time_utc'] if self.latest else None
        age = max(0, (datetime.now(UTC) - datetime.fromisoformat(source_time)).total_seconds()) if source_time else None
        status = self.status
        if status == 'live' and (age is None or age > 30):
            status = 'stale'
        return {'status': status, 'source_time_utc': source_time,
                'source_age_seconds': age, 'latest_observation': self.latest,
                'recording': self.recording, 'error': self.error}

    async def run(self):
        factory = self.client_factory
        if factory is None:
            from yfinance import AsyncWebSocket
            factory = AsyncWebSocket
        with ObservationStore(self.database) as store:
            while True:
                listener = None
                self.status = 'connecting'
                self.client = factory(verbose=False)
                try:
                    await asyncio.wait_for(self.client.subscribe(['AAPL']), timeout=15)
                    self.status = 'waiting'

                    def on_message(message):
                        try:
                            self.accept(message, store)
                        except Exception as error:
                            self.status = 'error'
                            self.error = type(error).__name__

                    listener = asyncio.create_task(listen_continuously(self.client, on_message))
                    while True:
                        await asyncio.sleep(0.25)
                        # yfinance 1.8.0 hides reconnect failures. Observe its pinned
                        # websockets 17.4 transport and recreate the subscription.
                        transport = getattr(self.client, '_ws', None)
                        if listener.done() or transport is None or transport.state.name != 'OPEN':
                            raise ConnectionError('Upstream disconnected')
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    self.status = 'disconnected'
                    self.error = type(error).__name__
                finally:
                    if listener is not None:
                        listener.cancel()
                    with suppress(Exception):
                        await asyncio.wait_for(self.client.close(), timeout=3)
                    if listener is not None:
                        with suppress(asyncio.CancelledError, Exception):
                            await asyncio.wait_for(listener, timeout=3)
                await asyncio.sleep(3)

    async def start(self):
        with ObservationStore(self.database) as store:
            row = store.connection.execute(
                "SELECT o.payload_json, r.received_at_utc, o.id, r.id "
                "FROM receipts r JOIN observations o ON o.id=r.observation_id "
                "WHERE o.ticker='AAPL' AND o.provider='yahoo' ORDER BY r.id DESC LIMIT 1"
            ).fetchone()
            if row:
                self.latest = describe_update(json.loads(row[0]), datetime.fromisoformat(row[1]))
                self.recording = {'observation_id': row[2], 'receipt_id': row[3]}
        self.task = asyncio.create_task(self.run())

    async def stop(self):
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
        self.status = 'disconnected'

    def snapshot(self, timeframe='1m'):
        result = history_response('AAPL', timeframe, source='observations', database=self.database)
        return {**result, 'type': 'snapshot', 'interval': timeframe,
                'source': self.source, 'feed': self.feed_state()}
