"""One Yahoo subscription per feed; durable quotes precede derived chart updates."""

import asyncio
import json
from contextlib import suppress
from datetime import UTC, datetime

from backend.history import history_response
from backend.indicators import with_averages
from backend.observations import DEFAULT_DATABASE, ObservationStore
from backend.provider_history import ProviderHistory
from backend.yahoo_stream import describe_update, listen_continuously


class LiveFeed:
    def __init__(self, database=DEFAULT_DATABASE, client_factory=None, *, symbol='AAPL'):
        self.database = database
        self.symbol = symbol
        self.client_factory = client_factory
        self.client = None
        self.task = None
        self.status = 'connecting'
        self.latest = None
        self.recording = None
        self.error = None
        self.on_record = None
        self.source = 'Yahoo Finance · stored observations'
        self.history = None

    def accept(self, message, store):
        if message.get('id') != self.symbol or 'price' not in message:
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
                    await asyncio.wait_for(self.client.subscribe([self.symbol]), timeout=15)
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
                        # WebSockets transport and recreate the subscription.
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
                "WHERE o.ticker=? AND o.provider='yahoo' ORDER BY r.id DESC LIMIT 1",
                (self.symbol,),
            ).fetchone()
            if row:
                self.latest = describe_update(json.loads(row[0]), datetime.fromisoformat(row[1]))
                self.recording = {'observation_id': row[2], 'receipt_id': row[3]}
        self.task = asyncio.create_task(self.run())

    async def stop(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        self.status = 'disconnected'

    def snapshot(self, timeframe='1m'):
        def observed(frame):
            return history_response(self.symbol, frame, source='observations',
                                    calendar='NASDAQ', database=self.database)

        result = observed(timeframe)
        if self.history is not None:
            daily = observed('1d') if timeframe in ('1w', '1mo') else result
            source_time = self.latest.get('source_time_utc') if self.latest else None
            result = with_averages(self.history.merge(result, daily, timeframe, datetime.now(UTC),
                datetime.fromisoformat(source_time) if source_time else None))
        return {**result, 'type': 'snapshot', 'interval': timeframe,
                'source': result['source'] if self.history is not None else self.source,
                'feed': dict(self.feed_state(), historical=result.get('historical'))}


class LiveSubscriptions:
    """Share each subscription between its charts and the live paper account."""

    def __init__(self, default):
        self.default = default
        self.feeds = {}
        self.viewers = {}
        self.paper_symbols = set()

    async def _feed(self, symbol):
        if symbol not in self.feeds:
            feed = LiveFeed(self.default.database, self.default.client_factory, symbol=symbol)
            if self.default.task is not None:
                path = feed.database.with_name(f'{feed.database.stem}-{symbol}.history.json')
                feed.history = ProviderHistory(path, background=True, symbol=symbol)
                await feed.start()
            else:
                feed.status = 'disabled'
            self.feeds[symbol] = feed
        return self.feeds[symbol]

    async def open_chart(self, symbol):
        if symbol == self.default.symbol:
            return self.default
        feed = await self._feed(symbol)
        self.viewers[symbol] = self.viewers.get(symbol, 0) + 1
        return feed

    async def close_chart(self, symbol):
        if symbol == self.default.symbol:
            return
        self.viewers[symbol] -= 1
        if self.viewers[symbol] == 0:
            del self.viewers[symbol]
            await self._close_unused(symbol)

    async def _close_unused(self, symbol):
        if symbol not in self.viewers and symbol not in self.paper_symbols:
            feed = self.feeds.pop(symbol, None)
            if feed is not None:
                await feed.stop()

    async def track_paper(self, symbols):
        self.paper_symbols = symbols - {self.default.symbol}
        for symbol in sorted(self.paper_symbols):
            await self._feed(symbol)
        for symbol in tuple(self.feeds):
            await self._close_unused(symbol)

    async def stop(self):
        await asyncio.gather(self.default.stop(), *(feed.stop() for feed in self.feeds.values()))
