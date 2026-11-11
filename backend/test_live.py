"""Recorded fixtures are constructed data, never live Yahoo verification."""

import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend.live import LiveFeed
from backend.observations import ObservationStore
from backend.yahoo_stream import listen_continuously


class LiveTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.feed = LiveFeed(Path(self.directory.name) / 'quotes.sqlite3')

    def quote(self, time, price, volume):
        return {'id': 'AAPL', 'time': int(datetime.fromisoformat(time).timestamp() * 1000),
                'price': price, 'day_volume': volume, 'test_data': True}

    def accept(self, message, store):
        with patch('backend.live.datetime') as clock:
            clock.now.return_value = datetime.fromtimestamp(message['time'] / 1000, UTC)
            self.feed.accept(message, store)

    async def test_same_interval_volume_rollover_and_daily(self):
        with ObservationStore(self.feed.database) as store:
            self.accept(self.quote('2026-11-10T14:59:59+00:00', 99, 1000), store)
            self.accept(self.quote('2026-11-10T15:00:01+00:00', 100, 1004), store)
            with patch('backend.history.datetime') as clock:
                clock.now.return_value = datetime(2026, 11, 10, 15, 0, 10, tzinfo=UTC)
                first = self.feed.snapshot()
            self.assertEqual(first['candles'][-1]['volume'], 4)
            self.assertFalse(first['coverage'][-1]['ended'])
            self.accept(self.quote('2026-11-10T15:00:20+00:00', 103, 1011), store)
            revised = self.feed.snapshot()
            self.assertEqual(len(revised['candles']), 2)
            self.assertEqual(revised['candles'][-1], {
                'timestamp': '2026-11-10T15:00:00Z', 'open': 100,
                'high': 103, 'low': 100, 'close': 103, 'volume': 11})
            self.accept(self.quote('2026-11-10T15:01:01+00:00', 102, 1014), store)
            self.assertEqual(self.feed.snapshot()['candles'][-1]['volume'], 3)
            self.assertEqual(len(self.feed.snapshot()['candles']), 3)
            for interval in ('5m', '15m', '1h', '1d'):
                result = self.feed.snapshot(interval)
                self.assertEqual(result['interval'], interval)
                self.assertEqual(result['candles'][-1]['close'], 102)
            # Repeated payload remains one effective observation.
            self.accept(self.quote('2026-11-10T15:01:01+00:00', 102, 1014), store)
            self.assertEqual(len(store.snapshot()['observations']), 4)

    async def test_stale_and_disconnected_are_independent_of_browser(self):
        with ObservationStore(self.feed.database) as store:
            self.accept(self.quote('2026-11-09T15:00:01+00:00', 100, 1000), store)
        self.assertEqual(self.feed.feed_state()['status'], 'stale')
        self.feed.status = 'disconnected'
        self.assertEqual(self.feed.feed_state()['status'], 'disconnected')
        self.assertEqual(self.feed.snapshot()['feed']['status'], 'disconnected')

    async def test_clean_upstream_close_exits_instead_of_spinning(self):
        async def frames():
            yield json.dumps({'message': 'constructed'})
        client = SimpleNamespace(_ws=frames(), _decode_message=lambda frame: {'test_data': True})
        messages = []
        with self.assertRaises(ConnectionError):
            await listen_continuously(client, messages.append)
        self.assertEqual(messages, [{'test_data': True}])

    async def test_single_subscription_disconnect_and_shutdown(self):
        class Client:
            def __init__(self, **kwargs):
                self.closed = False
                self._ws = SimpleNamespace(state=SimpleNamespace(name='OPEN'))
            async def subscribe(self, symbols):
                self.symbols = symbols
            async def close(self):
                self.closed = True

        clients = []
        def factory(**kwargs):
            client = Client()
            clients.append(client)
            return client
        self.feed.client_factory = factory
        with ObservationStore(self.feed.database) as store:
            self.accept(self.quote('2026-11-10T15:00:01+00:00', 100, 1000), store)
        self.feed.latest = None
        async def receive(client, handler):
            await asyncio.Event().wait()
        with patch('backend.live.listen_continuously', receive):
            await self.feed.start()
            try:
                await asyncio.sleep(0.05)
                self.assertEqual(clients[0].symbols, ['AAPL'])
                self.assertEqual(self.feed.latest['price'], 100)
                self.assertEqual(self.feed.recording['observation_id'], 1)
                clients[0]._ws.state.name = 'CLOSED'
                await asyncio.sleep(0.3)
                self.assertEqual(self.feed.status, 'disconnected')
                self.assertTrue(clients[0].closed)
                self.assertEqual(len(clients), 1)
            finally:
                await self.feed.stop()
        self.assertTrue(self.feed.task.done())
