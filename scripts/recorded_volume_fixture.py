"""Read-only source copy for a saved-Yahoo volume browser check; no live feed."""
from contextlib import asynccontextmanager
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sqlite3
from unittest.mock import patch

from backend.main import app, setup_paper
from backend.indicator_store import IndicatorStore
from backend.live import LiveFeed
from backend.observations import ObservationStore

AS_OF = datetime(2026, 11, 16, 15, 18, 43, tzinfo=UTC)
TARGET = '2026-11-16T15:17:00+00:00'


class Feed(LiveFeed):
    def snapshot(self, timeframe='1m'):
        with patch('backend.history.datetime') as clock:
            clock.now.return_value = AS_OF
            result = super().snapshot(timeframe)
        result['source'] = 'Yahoo Finance · recorded observations · frozen verification'
        return result


@asynccontextmanager
async def lifespan(application):
    market = Path(os.environ['ARBITRADE_DATABASE'])
    assert not market.exists(), 'Verification requires disposable storage'
    capture = Path(__file__).resolve().parent.parent / 'docs/evidence/volume-2026-11-16/source-observations.json'
    saved = json.loads(capture.read_text())
    with ObservationStore(market) as destination:
        with destination.connection:
            for row in saved['observations']:
                destination.connection.execute('INSERT INTO observations VALUES (?,?,?,?,?,?,?)',
                    tuple(row[k] for k in ('id', 'provider', 'ticker', 'source_time_json',
                                          'source_time_utc', 'payload_json', 'supersedes_observation_id')))
            for row in saved['receipts']:
                destination.connection.execute('INSERT INTO receipts VALUES (?,?,?)',
                    (row['id'], row['observation_id'], row['received_at_utc']))
    application.state.feed = Feed(market)
    application.state.feed.status = 'disabled'
    application.state.indicator_store = IndicatorStore(Path(os.environ['ARBITRADE_CONFIG_DATABASE']))
    setup_paper(application)
    try:
        yield
    finally:
        await application.state.feed.stop()


app.router.lifespan_context = lifespan


@app.get('/api/verification/volume-evidence')
def expected():
    # Independently read the final counters on each side of the minute boundary.
    sql = """SELECT o.id AS observation_id, o.source_time_utc,
        json_extract(o.payload_json, '$.price') AS price,
        CAST(json_extract(o.payload_json, '$.day_volume') AS INTEGER) AS day_volume,
        min(r.id) AS first_receipt_id, min(r.received_at_utc) AS received_at_utc
        FROM observations o JOIN receipts r ON r.observation_id=o.id
        WHERE o.ticker='AAPL' AND o.provider='yahoo' AND o.source_time_utc >= ?
        AND o.source_time_utc < ? AND r.received_at_utc <= ?
        GROUP BY o.id ORDER BY o.source_time_utc DESC, first_receipt_id DESC LIMIT 1"""
    with sqlite3.connect(application_database().as_uri() + '?mode=ro', uri=True) as connection:
        connection.row_factory = sqlite3.Row
        def read(start, end):
            return dict(connection.execute(sql, (start, end, AS_OF.isoformat())).fetchone())
        baseline = read('2026-11-16T15:16:00+00:00', TARGET)
        last = read(TARGET, '2026-11-16T15:18:00+00:00')
    assert baseline['day_volume'] <= last['day_volume']
    return dict(input='ACTUAL saved Yahoo; copied database; not a new live capture',
                timestamp=TARGET.replace('+00:00', 'Z'), as_of=AS_OF.isoformat(),
                baseline=baseline, last=last, expected_volume=last['day_volume']-baseline['day_volume'], sql=sql)


def application_database():
    return Path(app.state.feed.database).resolve()
