"""Isolated historical-download UI fixture; prices are constructed, not Yahoo."""
from contextlib import asynccontextmanager
from datetime import timedelta
import os
from pathlib import Path
from unittest.mock import patch

from backend.main import app, setup_paper
from backend.indicator_store import IndicatorStore
from backend.live import LiveFeed
from backend.observations import ObservationStore
from backend.provider_history import ProviderHistory
from backend.test_provider_history import NOW, fixture_rows
from backend.timeframes import TIMEFRAMES


class Feed(LiveFeed):
    def snapshot(self, timeframe='1m'):
        with patch('backend.live.datetime') as clock, patch('backend.history.datetime') as history_clock:
            clock.now.return_value = history_clock.now.return_value = NOW
            return super().snapshot(timeframe)


@asynccontextmanager
async def lifespan(application):
    market = Path(os.environ['ARBITRADE_DATABASE'])
    with ObservationStore(market) as store:
        now = NOW - timedelta(minutes=1)
        store.record(dict(id='AAPL', time=int(now.timestamp()*1000), price=230, day_volume=2000,
                          test_data=True), now, source_time_utc=now.isoformat())
    application.state.feed = Feed(market)
    application.state.feed.history = ProviderHistory(market.with_suffix('.history.json'), fixture_rows)
    for timeframe, duration in TIMEFRAMES.items():
        if duration:
            rows = [dict(timestamp=stamp, open=100, high=103, low=99, close=101, volume=20)
                    for stamp in ('2026-08-12T13:30:00Z', '2026-11-12T14:30:00Z')]
            application.state.feed.history.intraday[timeframe] = ProviderHistory(
                market.with_suffix(f'.{timeframe}.history.json'), lambda: rows, timeframe=timeframe)
    application.state.feed.status = 'disabled'
    application.state.indicator_store = IndicatorStore(Path(os.environ['ARBITRADE_CONFIG_DATABASE']))
    setup_paper(application)
    try:
        yield
    finally:
        await application.state.feed.stop()


app.router.lifespan_context = lifespan


@app.post('/fixture/history-failure')
def fail():
    history = app.state.feed.history
    history.next_attempt = 0
    history.fetched_at = NOW - timedelta(minutes=10)
    def unavailable():
        raise TimeoutError('constructed outage')
    history.downloader = unavailable
    return {'status': 'failure on next refresh'}
