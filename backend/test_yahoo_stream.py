"""Offline subscription lifecycle checks; these do not contact Yahoo."""

import asyncio
import unittest

from backend.yahoo_stream import check_subscription


class FakeClient:
    def __init__(self, message=None, connection_error=False):
        self.message = message
        self.connection_error = connection_error
        self.closed = False

    async def subscribe(self, symbols):
        if self.connection_error:
            raise ConnectionError('simulated handshake failure')
        assert symbols == ['AAPL']

    async def listen(self, handler):
        if self.message is not None:
            handler(self.message)
        await asyncio.Event().wait()

    async def close(self):
        self.closed = True


class SubscriptionTests(unittest.IsolatedAsyncioTestCase):
    async def test_received_quote_preserves_time_and_volume(self):
        client = FakeClient({'id': 'AAPL', 'price': 101, 'time': '1794234660000', 'day_volume': '850'})
        result = await check_subscription(client_factory=lambda **kwargs: client)
        self.assertTrue(result['connection_opened'])
        self.assertTrue(result['receipt_verified'])
        update = result['update']
        self.assertEqual(update['source_time_utc'], '2026-11-09T14:31:00+00:00')
        self.assertEqual(update['volume_fields']['day_volume']['value'], '850')
        self.assertEqual(update['price'], 101)
        self.assertTrue(client.closed)

    async def test_open_connection_without_quote_is_unverified(self):
        client = FakeClient()
        result = await check_subscription(timeout=0.02, client_factory=lambda **kwargs: client)
        self.assertTrue(result['connection_opened'])
        self.assertFalse(result['receipt_verified'])
        self.assertTrue(result['status'].startswith('timeout'))
        self.assertTrue(client.closed)

    async def test_handshake_failure_does_not_claim_connection(self):
        client = FakeClient(connection_error=True)
        result = await check_subscription(client_factory=lambda **kwargs: client)
        self.assertFalse(result['connection_opened'])
        self.assertFalse(result['receipt_verified'])
        self.assertTrue(client.closed)

    async def test_other_ticker_does_not_verify_requested_ticker(self):
        client = FakeClient({'id': 'MSFT', 'price': 101})
        result = await check_subscription(timeout=0.02, client_factory=lambda **kwargs: client)
        self.assertFalse(result['receipt_verified'])
        self.assertTrue(client.closed)
