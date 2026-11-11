"""Test-only labeled feed-off app. Production exposes no price injection route."""

from contextlib import asynccontextmanager
import os
from pathlib import Path

from backend.indicator_store import IndicatorStore
from backend.live import LiveFeed
from backend.main import app, setup_paper


@asynccontextmanager
async def fixture_lifespan(application):
    application.state.indicator_store = IndicatorStore(os.environ['ARBITRADE_CONFIG_DATABASE'])
    application.state.feed = LiveFeed(Path(os.environ['ARBITRADE_DATABASE']))
    application.state.feed.source = 'CONSTRUCTED paper fixture · test_data=true · not live Yahoo'
    application.state.feed.status = 'disabled'
    setup_paper(application)
    try:
        yield
    finally:
        await application.state.feed.stop()


app.router.lifespan_context = fixture_lifespan
