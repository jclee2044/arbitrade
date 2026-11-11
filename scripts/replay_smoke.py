"""Start feed-off services, exercise replay in Chromium, verify storage, clean up."""
import argparse
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import tempfile
from datetime import datetime

from backend.observations import DEFAULT_DATABASE, ObservationStore
from scripts.smoke_test import ROOT, stop, wait_ready


def counts(path):
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as connection:
        return [connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                for table in ('observations', 'receipts')]


def verify(output, constructed=False):
    output.mkdir(parents=True, exist_ok=True)
    for port in (18000, 15173):
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(('127.0.0.1', port))
    backend = frontend = None
    with tempfile.TemporaryDirectory(prefix='arbitrade-replay-') as directory, tempfile.TemporaryFile(mode='w+') as logs:
        database = Path(directory) / 'test.sqlite3' if constructed else DEFAULT_DATABASE
        if constructed:
            with ObservationStore(database) as store:
                for source, received, price, total, parent in [
                    ('14:59:59', '14:59:59', 99, 1000, None),
                    ('15:00:10', '15:00:11', 100, 1004, None),
                    ('15:00:40', '15:00:41', 103, 1011, None),
                    ('15:00:10', '15:01:01', 98, 1004, 2),
                    ('15:00:40', '15:01:02', 103, 1011, None),
                ]:
                    source = '2026-11-10T' + source + '+00:00'
                    store.record(dict(id='AAPL', time=source, price=price, day_volume=total, test_data=True),
                                 datetime.fromisoformat('2026-11-10T' + received + '+00:00'),
                                 source_time_utc=source, supersedes_id=parent)
            selection = dict(start='2026-11-10T14:59:59+00:00', end='2026-11-10T15:01:02+00:00',
                             close='103', volume='11 shares', total=5, constructed=True)
        else:
            # First captured receipt is the actual regular-session interval identified
            # during inspection. Expected price is read directly from its SQL payload.
            with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as connection:
                received, payload, source = connection.execute('''
                    SELECT r.received_at_utc,o.payload_json,o.source_time_utc
                    FROM receipts r JOIN observations o ON o.id=r.observation_id
                    WHERE o.provider='yahoo' AND o.ticker='AAPL' ORDER BY r.id LIMIT 1
                ''').fetchone()
            selection = dict(start=received, end=received, close=str(json.loads(payload)['price']),
                             volume='Unknown', total=1, source_time=source, constructed=False)
        before = counts(database)
        environment = dict(os.environ, ARBITRADE_DATABASE=str(database), ARBITRADE_LIVE_FEED='off',
                           ARBITRADE_CONFIG_DATABASE=str(Path(directory) / 'chart-config.sqlite3'),
                           ARBITRADE_BACKEND_PORT='18000', ARBITRADE_FRONTEND_PORT='15173')
        environment['PYTHONPATH'] = str(ROOT / 'backend/.packages')
        def launch(command):
            return subprocess.Popen(command, cwd=ROOT, env=environment, stdout=logs, stderr=logs, start_new_session=True)
        try:
            backend = launch(['/usr/bin/python', '-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', '18000'])
            wait_ready(backend, 'http://127.0.0.1:18000/api/health')
            frontend = launch(['npm', '--prefix', 'frontend', 'run', 'dev'])
            wait_ready(frontend, 'http://127.0.0.1:15173')
            result = subprocess.run(['node', 'scripts/replay_smoke.mjs', str(output), json.dumps(selection)],
                                    cwd=ROOT, capture_output=True, text=True, timeout=90)
            (output / 'browser.log').write_text(result.stderr)
            assert result.returncode == 0, result.stdout + result.stderr
            after = counts(database)
            assert before == after, (before, after)
            report = dict(result='PASS', input='CONSTRUCTED test_data=true' if constructed else 'ACTUAL recorded Yahoo',
                          selection=selection, before=before, after=after, checks=json.loads(result.stdout))
            (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
            print(json.dumps(report, indent=2))
        except BaseException:
            logs.seek(0)
            print(logs.read())
            raise
        finally:
            stop(frontend)
            stop(backend)
            print('Stopped replay SmokeTest services and browser.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--constructed', action='store_true')
    parser.add_argument('--output', type=Path, default=Path('/tmp/arbitrade-replay-results'))
    args = parser.parse_args()
    verify(args.output.resolve(), args.constructed)
