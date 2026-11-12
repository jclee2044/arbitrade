"""Check local services; default mode also guides a human browser check."""

import argparse
import csv
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
import webbrowser

ROOT = Path(__file__).resolve().parent.parent
BACKEND = "http://127.0.0.1:8000"
FRONTEND = "http://127.0.0.1:5173"


def request(url):
    try:
        with urlopen(url, timeout=3) as response:
            return response.status, response.read().decode()
    except HTTPError as error:
        return error.code, error.read().decode()


def wait_ready(process, url):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Service exited with {process.returncode}: {url}")
        try:
            if request(url)[0] == 200:
                return
        except (URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(0.1)
    raise RuntimeError(f"Service did not become ready: {url}")


def stop(process):
    if process is not None and process.poll() is None:
        os.killpg(process.pid, signal.SIGINT)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--http-only', action='store_true', help='Skip manual browser observation; not a full UI SmokeTest')
    args = parser.parse_args()
    for port in (8000, 5173):
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(('127.0.0.1', port))  # Fail rather than interfere with existing services.

    backend = frontend = None
    with tempfile.TemporaryDirectory(prefix='arbitrade-smoke-') as directory, tempfile.TemporaryFile(mode='w+') as logs:
        def launch(command):
            environment = dict(os.environ)
            environment['ARBITRADE_DATABASE'] = str(Path(directory) / 'observations.sqlite3')
            environment['ARBITRADE_CONFIG_DATABASE'] = str(Path(directory) / 'chart-config.sqlite3')
            environment['PYTHONPATH'] = os.pathsep.join(filter(None, [
                str(ROOT / 'backend' / '.packages'), environment.get('PYTHONPATH'),
            ]))
            return subprocess.Popen(command, cwd=ROOT, env=environment, stdout=logs, stderr=logs, start_new_session=True)

        def start_backend():
            process = launch([sys.executable, '-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', '8000'])
            return process

        try:
            backend = start_backend()
            wait_ready(backend, BACKEND + '/api/health')
            frontend = launch(['npm', '--prefix', 'frontend', 'run', 'dev'])
            wait_ready(frontend, FRONTEND)
            direct = request(BACKEND + '/api/health')
            proxied = request(FRONTEND + '/api/health')
            assert direct == proxied == (200, '{"status":"ok"}'), (direct, proxied)
            print('PASS: direct and proxied health:', direct, flush=True)

            direct_history = request(BACKEND + '/api/history')
            proxied_history = request(FRONTEND + '/api/history')
            assert direct_history == proxied_history and direct_history[0] == 200
            data = json.loads(proxied_history[1])
            assert len(data) == 3
            assert [c['timestamp'] for c in data] == sorted(c['timestamp'] for c in data)
            source = ROOT / 'prompts/data/sample-candles.csv'
            if not source.is_file():
                source = ROOT / 'backend/data/sample-candles.csv'
            with source.open(newline='') as file:
                row = next(r for r in csv.DictReader(file) if r['timestamp'] == '2026-11-09T14:31:00Z')
            expected = {key: value if key == 'timestamp' else float(value) for key, value in row.items()}
            actual = next(c for c in data if c['timestamp'] == row['timestamp'])
            assert actual == expected, actual
            print('PASS: direct/proxied history HTTP 200; second candle:', json.dumps(actual), flush=True)

            stop(backend)
            backend = None
            failed = request(FRONTEND + '/api/health')
            assert 500 <= failed[0] < 600, failed
            print('PASS: backend stopped; proxied health:', failed, flush=True)
            backend = start_backend()
            wait_ready(backend, BACKEND + '/api/health')
            recovered = request(FRONTEND + '/api/health')
            assert recovered == direct, recovered
            print('PASS: backend restarted; proxy recovered:', recovered, flush=True)

            if not args.http_only:
                if not webbrowser.open(FRONTEND):
                    raise RuntimeError(f'No browser could be opened. Open {FRONTEND} manually and rerun with a browser available.')
                print('In the browser: open Feed details and click Check connection; confirm Backend connected.')
                print('Confirm default AAPL / 1m, Yahoo source, FastAPI connection, feed status and changing source age.')
                print('Switch through 5m, 15m, 1h, Daily, then return to 1m; inspect a candle and aligned volume.')
                input('Once observations appear, press Enter to select a stored candle for comparison: ')
                observed = json.loads(request(BACKEND + '/api/history?source=observations')[1])
                assert observed, 'No in-session observations; live UI check remains pending'
                target = observed[0]
                print('Choose this candle under Inspect candle, then open Candle details:', target['timestamp'])
                values = input('Enter displayed open high low close and volume (unknown if absent), separated by spaces: ').split()
                assert len(values) == 5
                expected = [target[key] for key in ('open', 'high', 'low', 'close', 'volume')]
                actual = [None if value.lower() == 'unknown' else float(value.replace(',', '')) for value in values]
                assert actual == expected, (actual, expected)
                assert input('Did connection, timeframe switching, forming/ended labels and aligned volume pass? [yes/no] ').strip().lower() == 'yes'
                print('PASS: interactive UI SmokeTest (human observation).')
            else:
                print('PASS: HTTP checks only; UI observation not performed.')
        except BaseException:
            logs.seek(0)
            print(logs.read(), file=sys.stderr)
            raise
        finally:
            stop(frontend)
            stop(backend)
            print('Stopped test services.', flush=True)


if __name__ == '__main__':
    main()
