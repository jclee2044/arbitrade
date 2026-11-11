"""Test-only labeled app with a controlled market clock; no injection routes."""

from contextlib import asynccontextmanager
from datetime import datetime
import os
from pathlib import Path

from backend.history import history_response
from backend.indicator_store import IndicatorStore
from backend.live import LiveFeed
from backend.main import app, setup_paper


class PnlFeed(LiveFeed):
    def __init__(self, database, clock):
        super().__init__(database)
        self.clock = clock
        self.source = 'CONSTRUCTED P&L fixture · test_data=true · not live Yahoo'
        self.status = 'disabled'

    def snapshot(self, timeframe='1m'):
        result = history_response(source='observations', database=self.database, timeframe=timeframe, as_of=self.clock())
        return dict(result, type='snapshot', interval=timeframe, source=self.source, feed=self.feed_state())


@asynccontextmanager
async def fixture_lifespan(application):
    clock_file = Path(os.environ['ARBITRADE_PNL_CLOCK'])
    application.state.paper_clock = lambda: datetime.fromisoformat(clock_file.read_text().strip())
    application.state.indicator_store = IndicatorStore(os.environ['ARBITRADE_CONFIG_DATABASE'])
    application.state.feed = PnlFeed(Path(os.environ['ARBITRADE_DATABASE']), application.state.paper_clock)
    setup_paper(application)
    try:
        yield
    finally:
        await application.state.feed.stop()


app.router.lifespan_context = fixture_lifespan
