"""Feed-off Chromium SmokeTest for completed-candle SMAs; constructed SQLite only."""

import argparse
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import tempfile

from scripts.sma_fixture import create_fixture, reference_rows
from scripts.smoke_test import ROOT, stop, wait_ready


def verify(output):
    output.mkdir(parents=True, exist_ok=True)
    for port in (18000, 15173):
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(('127.0.0.1', port))
    backend = frontend = None
    report = dict(result='FAIL', input='CONSTRUCTED test_data=true; separate disposable SQLite')
    with tempfile.TemporaryDirectory(prefix='arbitrade-sma-') as directory, tempfile.TemporaryFile(mode='w+') as logs:
        database = Path(directory) / 'constructed.sqlite3'
        bounds = create_fixture(database)
        before = database.read_bytes()
        environment = dict(os.environ, ARBITRADE_DATABASE=str(database), ARBITRADE_LIVE_FEED='off',
                           ARBITRADE_CONFIG_DATABASE=str(Path(directory) / 'chart-config.sqlite3'),
                           ARBITRADE_BACKEND_PORT='18000', ARBITRADE_FRONTEND_PORT='15173',
                           PYTHONPATH=str(ROOT / 'backend/.packages'))
        def launch(command):
            return subprocess.Popen(command, cwd=ROOT, env=environment, stdout=logs, stderr=logs, start_new_session=True)
        try:
            backend = launch(['/usr/bin/python', '-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', '18000'])
            wait_ready(backend, 'http://127.0.0.1:18000/api/health')
            frontend = launch(['npm', '--prefix', 'frontend', 'run', 'dev'])
            wait_ready(frontend, 'http://127.0.0.1:15173')
            data = dict(bounds, expected=reference_rows())
            result = subprocess.run(['node', 'scripts/sma_smoke.mjs', str(output), json.dumps(data)],
                                    cwd=ROOT, capture_output=True, text=True, timeout=120)
            (output / 'browser.log').write_text(result.stderr)
            if result.returncode:
                raise AssertionError(result.stdout + result.stderr)
            assert database.read_bytes() == before, 'Replay changed the recorded fixture file'
            with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as connection:
                observation_count = connection.execute('SELECT COUNT(*) FROM observations').fetchone()[0]
                receipt_count = connection.execute('SELECT COUNT(*) FROM receipts').fetchone()[0]
            assert (observation_count, receipt_count) == (7, 8)
            report.update(result='PASS', **json.loads(result.stdout), stored_observations=observation_count,
                          stored_receipts=receipt_count, stored_database_unchanged=True)
        except BaseException as error:
            report['failure'] = str(error)
            logs.seek(0)
            (output / 'services.log').write_text(logs.read())
            raise
        finally:
            (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
            stop(frontend)
            stop(backend)
            print(json.dumps({key: report[key] for key in ('result', 'checks', 'failure') if key in report}, indent=2))
            print('Stopped SMA SmokeTest services; browser closed; disposable test database removed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('/tmp/arbitrade-sma-results'))
    args = parser.parse_args()
    verify(args.output.resolve())
