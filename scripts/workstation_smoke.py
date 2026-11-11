"""One offline UI/SQLite SmokeTest; no installs, source edits, or live connections."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile

from scripts.smoke_test import ROOT, stop, wait_ready


def audit(path):
    with closing(sqlite3.connect(path)) as c:
        c.row_factory = sqlite3.Row
        accounts = c.execute("SELECT * FROM paper_accounts WHERE mode='test'").fetchall()
        assert len(accounts) == 1
        account = accounts[0]
        fills = [dict(r) for r in c.execute('SELECT f.* FROM paper_fills f JOIN paper_orders o ON o.id=f.order_id WHERE o.account_id=? ORDER BY f.id', (account['id'],))]
        assert [(f['quantity'], f['price'], f['fees']) for f in fills] == [(4, '100', '0'), (1, '110', '0'), (3, '105', '0')]
        assert account['cash'] == '1025'
        assert c.execute('SELECT shares FROM paper_positions WHERE account_id=?', (account['id'],)).fetchone()[0] == 0
        pnl = dict(c.execute('SELECT * FROM paper_pnl_history WHERE account_id=? ORDER BY id DESC LIMIT 1', (account['id'],)).fetchone())
        assert (pnl['cash'], pnl['shares'], pnl['realized'], pnl['unrealized']) == ('1025', 0, '25', '0')
        assert c.execute('SELECT COUNT(*) FROM paper_orders WHERE account_id=?', (account['id'],)).fetchone()[0] == 3
        assert c.execute('SELECT COUNT(*) FROM automation_runs WHERE enabled=1').fetchone()[0] == 0
        captures = c.execute('SELECT * FROM smoke_payloads').fetchall()
        assert len(captures) >= 6
        for row in captures:
            image = c.execute('SELECT i.png FROM decision_images i JOIN decisions d ON i.decision_id=d.id WHERE d.snapshot_id=?', (row['snapshot_id'],)).fetchone()
            assert image is not None and image[0] == row['png']
        assert c.execute("SELECT COUNT(*) FROM decisions WHERE status='provider_error'").fetchone()[0] == 1
        assert c.execute("SELECT COUNT(*) FROM decisions WHERE status='review_rejected'").fetchone()[0] >= 1
        assert c.execute("SELECT cash FROM paper_accounts WHERE id='live'").fetchone()[0] == '1000'
        assert c.execute("SELECT settings_json FROM chart_indicators WHERE name='Smoke SMA'").fetchone()[0] == '{"window": 3}'
        return dict(account_id=account['id'], cash=account['cash'], shares=0, realized=pnl['realized'], unrealized=pnl['unrealized'], fills=fills, matching_payloads=len(captures))


def verify(output):
    output.mkdir(parents=True, exist_ok=True)
    report = dict(result='FAIL', market='offline deterministic', model='stubbed analyst/reviewer', checks=[])
    processes = []
    def interrupted(signum, frame):
        raise KeyboardInterrupt('SmokeTest interrupted')
    previous = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        for port in (18000, 15173):
            with socket.socket() as probe:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                probe.bind(('127.0.0.1', port))
        with tempfile.TemporaryDirectory(prefix='arbitrade-workstation-') as directory, (output/'services.log').open('w') as logs:
            state = Path(directory)/'state.sqlite3'
            env = dict(os.environ, ARBITRADE_CONFIG_DATABASE=str(state), ARBITRADE_DATABASE=str(Path(directory)/'market.sqlite3'),
                       ARBITRADE_LIVE_FEED='off', ARBITRADE_PAPER_ORDER_SIZE='4', ARBITRADE_BACKEND_PORT='18000',
                       ARBITRADE_FRONTEND_PORT='15173', PYTHONPATH=str(ROOT/'backend/.packages'))
            env.pop('OPENAI_API_KEY', None)
            def launch(command, **kwargs):
                process = subprocess.Popen(command, cwd=ROOT, env=env, start_new_session=True, **kwargs)
                processes.append(process)
                return process
            try:
                backend = launch([sys.executable, '-m', 'uvicorn', 'scripts.workstation_fixture:app', '--host', '127.0.0.1', '--port', '18000'], stdout=logs, stderr=logs)
                wait_ready(backend, 'http://127.0.0.1:18000/api/health')
                frontend = launch(['npm', '--prefix', 'frontend', 'run', 'dev'], stdout=logs, stderr=logs)
                wait_ready(frontend, 'http://127.0.0.1:15173')
                driver = launch(['node', 'scripts/workstation_smoke.mjs', str(output)], stdout=subprocess.PIPE, stderr=logs, text=True)
                stdout, _ = driver.communicate(timeout=180)
                (output/'browser.json').write_text(stdout)
                assert driver.returncode == 0, 'Browser failed: see browser.json, services.log and failure.png'
                report.update(json.loads(stdout))
                report['sqlite'] = audit(state)
                report['result'] = 'PASS'
            finally:
                for process in reversed(processes):
                    stop(process)
                report['processes_stopped'] = all(p.poll() is not None for p in processes)
    except BaseException as failure:
        report['result'] = 'FAIL'
        report['failure'] = str(failure)
        raise
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        (output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('/tmp/arbitrade-workstation-smoke'))
    verify(parser.parse_args().output.resolve())
