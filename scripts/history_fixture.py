"""Disposable multi-day chart fixture; never loaded by production."""
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path

from backend.main import app, setup_paper
from backend.indicator_store import IndicatorStore
from backend.observations import ObservationStore
from scripts.automation_fixture import Feed


@asynccontextmanager
async def lifespan(application):
    market = Path(os.environ['ARBITRADE_DATABASE'])
    state = Path(os.environ['ARBITRADE_CONFIG_DATABASE'])
    assert not market.exists() and not state.exists()
    with ObservationStore(market) as store:
        for day in (9, 10, 11):
            start = datetime(2026, 11, day, 15, tzinfo=UTC)
            for minute in range(120):
                now = start + timedelta(minutes=minute, seconds=10)
                store.record(dict(id='AAPL', time=int(now.timestamp()*1000),
                                  price=100 + day + minute / 100, day_volume=1000 + minute*10,
                                  test_data=True), now, source_time_utc=now.isoformat())
        for minute, price in enumerate((400, 403)):
            now = datetime(2026, 11, 11, 15, minute, 10, tzinfo=UTC)
            store.record(dict(id='MSFT', time=int(now.timestamp()*1000), price=price,
                              day_volume=2000 + minute*15, test_data=True), now, source_time_utc=now.isoformat())
    application.state.fixture_now = [datetime(2026, 11, 11, 17, tzinfo=UTC)]
    application.state.feed = Feed(market)
    application.state.feed.status = 'disabled'
    application.state.indicator_store = IndicatorStore(state)
    application.state.paper_clock = lambda: application.state.fixture_now[0]
    setup_paper(application)
    try:
        yield
    finally:
        await application.state.feed.stop()


app.router.lifespan_context = lifespan


@app.post('/fixture/rollover')
def rollover():
    now = app.state.fixture_now[0] + timedelta(minutes=1)
    app.state.fixture_now[0] = now
    with ObservationStore(app.state.feed.database) as store:
        store.record(dict(id='AAPL', time=int(now.timestamp()*1000), price=115,
                          day_volume=2500, test_data=True), now, source_time_utc=now.isoformat())
    return {'timestamp': now.isoformat()}
