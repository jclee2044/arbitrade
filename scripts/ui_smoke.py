"""Automated Chromium UI SmokeTest; requires separately approved playwright-core.

Default input is explicitly labeled constructed replay data. --live uses actual
Yahoo quotes. All storage is disposable and services/browser are cleaned up.
"""

import argparse
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
import json
from pathlib import Path
import socket
import subprocess
import tempfile

import uvicorn

from backend.history import history_response
from backend.live import LiveFeed
from backend.main import app, setup_paper
from backend.indicator_store import IndicatorStore
from backend.observations import ObservationStore
from backend.yahoo_stream import describe_update
from scripts.smoke_test import ROOT, stop, wait_ready


class ReplayFeed(LiveFeed):
    def __init__(self, database):
        super().__init__(database)
        self.evaluation = '2026-11-10T15:00:30+00:00'
        self.source = 'CONSTRUCTED replay · test_data=true · not live Yahoo'
        self.status = 'waiting'

    def add(self, timestamp, price, total):
        received = datetime.fromisoformat(timestamp)
        message = {'id': 'AAPL', 'time': int(received.timestamp() * 1000),
                   'price': price, 'day_volume': total, 'test_data': True}
        with ObservationStore(self.database) as store:
            self.latest = describe_update(message, received)
            self.recording = store.record(message, received, source_time_utc=self.latest['source_time_utc'])
        self.status = 'live'

    def snapshot(self, timeframe='1m'):
        result = history_response(source='observations', database=self.database,
                                  timeframe=timeframe, as_of=self.evaluation)
        return {**result, 'type': 'snapshot', 'interval': timeframe,
                'source': self.source, 'feed': self.feed_state()}


async def verify(live, output):
    package = ROOT / 'frontend/node_modules/playwright-core/package.json'
    if not package.is_file():
        raise RuntimeError('playwright-core is missing. Obtain AGENTS.md dependency approval before installing it.')
    for port in (8000, 5173):
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(('127.0.0.1', port))
    output.mkdir(parents=True, exist_ok=True)
    frontend = driver = None
    with tempfile.TemporaryDirectory(prefix='arbitrade-ui-') as directory, tempfile.TemporaryFile(mode='w+') as logs:
        database = Path(directory) / 'observations.sqlite3'
        feed = LiveFeed(database) if live else ReplayFeed(database)
        with ObservationStore(database):
            pass

        @asynccontextmanager
        async def lifespan(application):
            application.state.feed = feed
            application.state.indicator_store = IndicatorStore(Path(directory) / 'chart-config.sqlite3')
            setup_paper(application)
            if live:
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
                        raise RuntimeError('Backend exited before startup')
                    await asyncio.sleep(0.05)
            frontend = subprocess.Popen(['npm', '--prefix', 'frontend', 'run', 'dev'], cwd=ROOT,
                                        stdout=logs, stderr=logs, start_new_session=True)
            await asyncio.to_thread(wait_ready, frontend, 'http://127.0.0.1:5173')
            driver = await asyncio.create_subprocess_exec(
                'node', str(ROOT / 'scripts/ui_smoke.mjs'), str(output), 'live' if live else 'recorded',
                cwd=ROOT, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=logs,
            )
            report = {'input': 'ACTUAL Yahoo' if live else 'CONSTRUCTED replay test_data=true', 'checks': [], 'phases': {}}
            async with asyncio.timeout(150):
                while line := await driver.stdout.readline():
                    command = json.loads(line)
                    action = command['action']
                    if action == 'failed':
                        report.update(result='FAIL', checks=command['checks'], reason=command['reason'])
                        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
                        break
                    if action == 'pending':
                        report.update(result='PENDING', checks=command['checks'], reason=command['reason'],
                                      latest_observation=feed.latest, recording=feed.recording,
                                      feed_status=feed.feed_state()['status'])
                        break
                    if action == 'done':
                        report['checks'] = command['checks']
                        break
                    if action == 'seed':
                        if live:
                            async with asyncio.timeout(45):
                                while not feed.latest or not feed.snapshot()['candles']:
                                    await asyncio.sleep(0.2)
                            # Freeze the actual recorded input after the open page
                            # has received quotes, so inspector comparison is exact.
                            await feed.stop()
                            with ObservationStore(database) as store:
                                row = store.connection.execute(
                                    'SELECT source_time_utc,payload_json FROM observations WHERE id=?',
                                    (feed.recording['observation_id'],),
                                ).fetchone()
                            report['stored_observation'] = {
                                'recording': feed.recording, 'source_time_utc': row[0],
                                'payload': json.loads(row[1]),
                            }
                            last = feed.snapshot()['candles'][-1]
                            source = datetime.fromisoformat(row[0]).replace(second=0, microsecond=0)
                            assert datetime.fromisoformat(last['timestamp']) == source, 'Latest quote is outside the chart session'
                            assert last['close'] == report['stored_observation']['payload']['price']
                        else:
                            feed.add('2026-11-10T14:59:59+00:00', 99, 1000)
                            feed.add('2026-11-10T15:00:01+00:00', 100, 1004)
                            feed.add('2026-11-10T15:00:20+00:00', 103, 1011)
                    elif action == 'same':
                        assert not live
                        feed.evaluation = '2026-11-10T15:00:50+00:00'
                        feed.add('2026-11-10T15:00:40+00:00', 101, 1013)
                    elif action == 'rollover':
                        assert not live
                        feed.evaluation = '2026-11-10T15:01:10+00:00'
                        feed.add('2026-11-10T15:01:01+00:00', 102, 1016)
                    elif action == 'disconnect':
                        await feed.stop()
                    elif action != 'snapshots':
                        raise ValueError(f'Unexpected test action: {action}')
                    snapshots = {interval: feed.snapshot(interval) for interval in ('1m', '5m', '15m', '1h', '1d')}
                    report['phases'][action] = snapshots
                    driver.stdin.write((json.dumps(snapshots) + '\n').encode())
                    await driver.stdin.drain()
                assert await driver.wait() == 0, 'Browser driver failed; see service/driver output below'
                assert report['checks'], 'Browser driver did not report completed UI checks'
            report.setdefault('result', 'PASS')
            with ObservationStore(database) as store:
                report['stored_records'] = store.snapshot()
            (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
            print(json.dumps({key: value for key, value in report.items() if key not in ('phases', 'stored_records')}, indent=2), flush=True)
        except BaseException:
            logs.seek(0)
            print(logs.read(), flush=True)
            raise
        finally:
            if driver is not None and driver.returncode is None:
                driver.terminate()
                try:
                    await asyncio.wait_for(driver.wait(), timeout=5)
                except TimeoutError:
                    driver.kill()
                    await driver.wait()
            stop(frontend)
            server.should_exit = True
            await asyncio.wait_for(server_task, timeout=10)
            print('Stopped UI test services/browser; disposable SQLite storage removed.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--output', type=Path, default=Path('/tmp/arbitrade-ui-results'))
    args = parser.parse_args()
    asyncio.run(verify(args.live, args.output.resolve()))
