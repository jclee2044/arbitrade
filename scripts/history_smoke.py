"""Start isolated services, verify history in Chromium, then clean up."""
import argparse
import json
import os
import socket
from pathlib import Path
import subprocess
import tempfile

from scripts.smoke_test import ROOT, stop, wait_ready


def verify(output, fixture='scripts.history_fixture:app', driver='scripts/history_smoke.mjs',
           data='constructed three-day history'):
    output.mkdir(parents=True, exist_ok=True)
    backend_port, frontend_port = 18152, 15252
    for port in (backend_port, frontend_port):
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(('127.0.0.1', port))
    processes = []
    report = dict(result='FAIL', data=data)
    with tempfile.TemporaryDirectory(prefix='arbitrade-history-') as directory, (output/'services.log').open('w') as logs:
        env = dict(os.environ, ARBITRADE_DATABASE=str(Path(directory)/'market.sqlite3'),
                   ARBITRADE_CONFIG_DATABASE=str(Path(directory)/'state.sqlite3'),
                   ARBITRADE_LIVE_FEED='off', ARBITRADE_BACKEND_PORT=str(backend_port),
                   ARBITRADE_FRONTEND_PORT=str(frontend_port), PYTHONPATH=str(ROOT/'backend/.packages'))
        env.pop('OPENAI_API_KEY', None)
        def launch(command):
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=logs, stderr=logs, start_new_session=True)
            processes.append(process)
            return process
        try:
            server = launch(['/usr/bin/python', '-m', 'uvicorn', fixture, '--host', '127.0.0.1', '--port', str(backend_port)])
            wait_ready(server, f'http://127.0.0.1:{backend_port}/api/health')
            frontend = launch(['npm', '--prefix', 'frontend', 'run', 'dev'])
            wait_ready(frontend, f'http://127.0.0.1:{frontend_port}')
            result = subprocess.run(['node', driver, str(output)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=90)
            (output/'browser.log').write_text(result.stdout + result.stderr)
            assert result.returncode == 0, 'Browser failed: see browser.log and failure.png'
            report.update(json.loads(result.stdout), result='PASS')
        finally:
            for process in reversed(processes):
                stop(process)
            report['processes_stopped'] = all(p.poll() is not None for p in processes)
            (output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
            print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('/tmp/arbitrade-history-smoke'))
    verify(parser.parse_args().output.resolve())
