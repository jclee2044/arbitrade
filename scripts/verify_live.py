"""Transport verification with disposable storage; --recorded uses labeled fixtures.

Default mode checks transport only; --browser requests human UI comparisons.
Starts/stops FastAPI and Vite.
"""

import argparse
import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import tempfile
import webbrowser

import uvicorn
from websockets.asyncio.client import connect

from backend.history import history_response
from backend.live import LiveFeed
from backend.main import app, setup_paper
from backend.indicator_store import IndicatorStore
from backend.observations import ObservationStore
from scripts.smoke_test import ROOT, stop, wait_ready


async def verify(recorded, browser=False):
    for port in (8000, 5173):
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(('127.0.0.1', port))
    frontend = None
    with tempfile.TemporaryDirectory(prefix='arbitrade-live-') as directory, tempfile.TemporaryFile(mode='w+') as logs:
        feed = LiveFeed(Path(directory) / 'observations.sqlite3')
        if recorded:
            feed.source = 'CONSTRUCTED test_data=true · not Yahoo live'
        # Schema exists before the server accepts requests.
        with ObservationStore(feed.database):
            pass

        @asynccontextmanager
        async def lifespan(application):
            application.state.feed = feed
            application.state.indicator_store = IndicatorStore(Path(directory) / 'chart-config.sqlite3')
            setup_paper(application)
            if not recorded:
                await feed.start()
            try:
                yield
            finally:
                await feed.stop()

        app.router.lifespan_context = lifespan
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=8000, log_level='error'))
        server_task = asyncio.create_task(server.serve())
        try:
            async with asyncio.timeout(15):
                while not server.started:
                    if server_task.done():
                        server_task.result()
                        raise RuntimeError('FastAPI exited before startup')
                    await asyncio.sleep(0.05)
            frontend = subprocess.Popen(['npm', '--prefix', 'frontend', 'run', 'dev'], cwd=ROOT,
                                        stdout=logs, stderr=logs, start_new_session=True)
            await asyncio.to_thread(wait_ready, frontend, 'http://127.0.0.1:5173')
            if browser:
                if not webbrowser.open('http://127.0.0.1:5173'):
                    raise RuntimeError('No browser could be opened; UI check pending')
                print('In the browser: click Check connection. Confirm AAPL / 1m and the source label.')
                assert (await asyncio.to_thread(input, 'Does the connection button show Backend connected? [yes/no] ')).strip().lower() == 'yes'
            async with connect('ws://127.0.0.1:5173/api/live?symbol=AAPL&timeframe=1m') as ws:
                initial = json.loads(await ws.recv())
                assert initial['type'] == 'snapshot' and initial['interval'] == '1m'
                if recorded:
                    with ObservationStore(feed.database) as store:
                        for timestamp, price, total in [('2026-11-10T14:59:59+00:00', 99, 1000),
                                                        ('2026-11-10T15:00:01+00:00', 100, 1004),
                                                        ('2026-11-10T15:00:20+00:00', 103, 1011)]:
                            feed.accept({'id': 'AAPL', 'time': int(datetime.fromisoformat(timestamp).timestamp() * 1000),
                                         'price': price, 'day_volume': total, 'test_data': True}, store)
                matched = None
                async with asyncio.timeout(35):
                    while matched is None:
                        message = json.loads(await ws.recv())
                        if (message['type'] == 'candle' and message['feed']['recording']
                                and (not recorded or message['candle']['timestamp'] == '2026-11-10T15:00:00Z')):
                            matched = message
                recording = matched['feed']['recording']
                with sqlite3.connect(feed.database) as connection:
                    row = connection.execute('SELECT source_time_utc,payload_json FROM observations WHERE id=?',
                                             (recording['observation_id'],)).fetchone()
                payload = json.loads(row[1])
                expected = history_response(source='observations', database=feed.database)
                candle = next(c for c in expected['candles'] if c['timestamp'] == matched['candle']['timestamp'])
                assert matched['candle'] == candle
                assert candle['close'] == payload['price']
                print(json.dumps({'input': 'CONSTRUCTED test_data=true' if recorded else 'ACTUAL Yahoo',
                                  'recording': recording, 'source_time_utc': row[0], 'source_price': payload['price'],
                                  'websocket_candle': candle, 'completion': matched['completion']}, indent=2), flush=True)

                if browser:
                    print('Select candle in Inspect candle:', candle['timestamp'])
                    print('Expected OHLCV:', candle)
                    assert (await asyncio.to_thread(input, 'Do the visible time and OHLCV match (null means Unknown)? [yes/no] ')).strip().lower() == 'yes'
                    assert (await asyncio.to_thread(input, 'Switch through all five timeframes and back to 1m. Do the chart, interval label and aligned volume update? [yes/no] ')).strip().lower() == 'yes'
                if recorded:
                    with ObservationStore(feed.database) as store:
                        feed.accept({'id': 'AAPL', 'time': int(datetime.fromisoformat('2026-11-10T15:00:40+00:00').timestamp() * 1000),
                                     'price': 101, 'day_volume': 1013, 'test_data': True}, store)
                    async with asyncio.timeout(3):
                        while True:
                            change = json.loads(await ws.recv())
                            if change['type'] == 'candle':
                                assert change['candle']['timestamp'] == candle['timestamp']
                                assert change['candle']['close'] == 101 and change['candle']['volume'] == 13
                                break
                    with ObservationStore(feed.database) as store:
                        feed.accept({'id': 'AAPL', 'time': int(datetime.fromisoformat('2026-11-10T15:01:01+00:00').timestamp() * 1000),
                                     'price': 102, 'day_volume': 1016, 'test_data': True}, store)
                    async with asyncio.timeout(3):
                        while True:
                            change = json.loads(await ws.recv())
                            if change['type'] == 'candle':
                                assert change['candle']['timestamp'] == '2026-11-10T15:01:00Z'
                                assert change['candle']['volume'] == 3
                                break
                    print('PASS: CONSTRUCTED same-minute close/volume replacement and next-minute rollover over WebSocket.', flush=True)
                    feed.status = 'disconnected'
                else:
                    await feed.client._ws.close()
                async with asyncio.timeout(3):
                    while True:
                        status = json.loads(await ws.recv())
                        if status.get('feed', {}).get('status') == 'disconnected':
                            break
                assert ws.state.name == 'OPEN'
                if browser:
                    # Hold the disconnected state for a human comparison.
                    await feed.stop()
                    assert (await asyncio.to_thread(input, 'Does the page show Feed: disconnected while Chart remains Connected to FastAPI? [yes/no] ')).strip().lower() == 'yes'
                    print('PASS: human-observed browser SmokeTest.', flush=True)
                print('PASS: upstream disconnected; same proxied FastAPI WebSocket remains OPEN and reports disconnected.', flush=True)

            for timeframe in ('1m', '5m', '15m', '1h', '1d'):
                async with connect(f'ws://127.0.0.1:5173/api/live?symbol=AAPL&timeframe={timeframe}') as ws:
                    snapshot = json.loads(await ws.recv())
                    expected = history_response(timeframe=timeframe, source='observations', database=feed.database)
                    assert snapshot['candles'] == expected['candles'] and snapshot['interval'] == timeframe
            print('PASS: all five timeframe snapshots equal backend observation aggregation through Vite.', flush=True)
            async with connect('ws://127.0.0.1:8000/api/live?timeframe=bad') as ws:
                assert json.loads(await ws.recv())['type'] == 'error'
                await ws.wait_closed()
                assert ws.close_code == 1008
            print('PASS: invalid timeframe rejected with 1008.', flush=True)
        except TimeoutError:
            print('PENDING: no matching in-session candle arrived within the verification deadline.', flush=True)
            raise
        finally:
            stop(frontend)
            server.should_exit = True
            await asyncio.wait_for(server_task, timeout=10)
            print('Stopped both verification services; disposable database removed.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recorded', action='store_true')
    parser.add_argument('--browser', action='store_true', help='Open browser and require human UI comparisons')
    args = parser.parse_args()
    asyncio.run(verify(args.recorded, args.browser))
