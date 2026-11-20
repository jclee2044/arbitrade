"""Offline Yahoo transport for the production lifespan and paper tracker."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
import json
import os
from types import SimpleNamespace
from unittest.mock import patch

from backend.main import app, lifespan
from backend.paper import PaperBroker


class Clock(datetime):
    value = datetime(2026, 11, 10, 15, tzinfo=UTC)

    @classmethod
    def now(cls, tz=None):
        return cls.value.astimezone(tz)


class Transport:
    def __init__(self):
        self.state = SimpleNamespace(name='OPEN')
        self.messages = asyncio.Queue()

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self.messages.get()


class ConstructedYahoo:
    def __init__(self, verbose=False):
        self._ws = Transport()
        self.symbol = None

    async def subscribe(self, symbols):
        self.symbol, = symbols
        assert self.symbol not in app.state.upstream
        app.state.upstream[self.symbol] = self

    async def close(self):
        if app.state.upstream.get(self.symbol) is self:
            del app.state.upstream[self.symbol]

    @staticmethod
    def _decode_message(message):
        return message


@asynccontextmanager
async def fixture_lifespan(application):
    application.state.upstream = {}
    application.state.paper_clock = Clock.now
    # Leave a durable pending order for startup to discover in the existing ledger.
    saved = PaperBroker(os.environ['ARBITRADE_CONFIG_DATABASE'], os.environ['ARBITRADE_DATABASE'], clock=Clock.now)
    saved.create_account()
    saved.execute('live', request_id='startup-ibm', action='buy', symbol='IBM', quantity=1)
    with (patch.dict(os.environ, {'ARBITRADE_LIVE_FEED': 'on'}),
          patch('backend.live.datetime', Clock),
          patch('yfinance.AsyncWebSocket', ConstructedYahoo),
          patch('backend.provider_history.download_daily', return_value=[]),
          patch('backend.provider_history.download_intraday', return_value=[])):
        async with lifespan(application):
            yield
    assert not application.state.upstream


app.router.lifespan_context = fixture_lifespan


@app.get('/fixture/subscriptions')
async def subscriptions():
    manager = app.state.subscriptions
    return {'upstream': sorted(app.state.upstream), 'viewers': manager.viewers,
            'paper': sorted(manager.paper_symbols)}


@app.post('/fixture/market')
async def market(timestamp: datetime, symbol: str | None = None, price: int | None = None, currency: str = 'USD'):
    assert timestamp >= Clock.value
    Clock.value = timestamp
    if symbol is not None:
        client = app.state.upstream[symbol]
        message = dict(id=symbol, price=price, time=int(timestamp.timestamp()*1000),
                       quote_type=8, currency=currency, test_data=True)
        await client._ws.messages.put(json.dumps({'message': message}))
    return {'timestamp': timestamp}
