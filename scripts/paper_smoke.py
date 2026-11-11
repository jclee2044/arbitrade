"""Browser-operated paper account reference, actual backend restart and SQL audit."""

from contextlib import closing
import argparse
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import tempfile

from backend.observations import ObservationStore
from scripts.smoke_test import ROOT, stop, wait_ready


def sql_state(database):
    with closing(sqlite3.connect(database)) as c:
        c.row_factory = sqlite3.Row
        return dict(
            cash=c.execute("SELECT cash FROM paper_accounts WHERE id='live'").fetchone()[0],
            shares=c.execute("SELECT COALESCE(SUM(shares),0) FROM paper_positions WHERE account_id='live'").fetchone()[0],
            orders=[dict(row) for row in c.execute("SELECT * FROM paper_orders WHERE account_id='live' ORDER BY id")],
            fills=[dict(row) for row in c.execute("SELECT f.* FROM paper_fills f JOIN paper_orders o ON o.id=f.order_id WHERE o.account_id='live' ORDER BY f.id")],
            total_fills=c.execute('SELECT COUNT(*) FROM paper_fills').fetchone()[0])


def verify(output):
    output.mkdir(parents=True, exist_ok=True)
    for port in (18000, 15173):
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(('127.0.0.1', port))
    backend = frontend = driver = None
    report = dict(result='FAIL', input='CONSTRUCTED test_data=true; disposable SQLite account, $1000 starting cash', phases={})
    with tempfile.TemporaryDirectory(prefix='arbitrade-paper-') as directory, tempfile.TemporaryFile(mode='w+') as logs:
        market = Path(directory)/'observations.sqlite3'
        state = Path(directory)/'chart-config.sqlite3'
        with ObservationStore(market):
            pass
        environment = dict(os.environ, ARBITRADE_DATABASE=str(market), ARBITRADE_CONFIG_DATABASE=str(state),
                           ARBITRADE_LIVE_FEED='off', ARBITRADE_BACKEND_PORT='18000', ARBITRADE_FRONTEND_PORT='15173',
                           PYTHONPATH=str(ROOT/'backend/.packages'))
        def launch(command):
            return subprocess.Popen(command, cwd=ROOT, env=environment, stdout=logs, stderr=logs, start_new_session=True)
        def start_backend():
            process = launch(['/usr/bin/python', '-m', 'uvicorn', 'scripts.paper_fixture:app', '--host', '127.0.0.1', '--port', '18000'])
            wait_ready(process, 'http://127.0.0.1:18000/api/health')
            return process
        prices = iter([100, 110, 105])
        quote_index = 0
        try:
            backend = start_backend()
            report['initial_backend_pid'] = backend.pid
            frontend = launch(['npm', '--prefix', 'frontend', 'run', 'dev'])
            wait_ready(frontend, 'http://127.0.0.1:15173')
            driver = subprocess.Popen(['node','scripts/paper_smoke.mjs', str(output)], cwd=ROOT,
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=logs,
                                      text=True, bufsize=1, start_new_session=True)
            while line := driver.stdout.readline():
                command = json.loads(line)
                action = command['action']
                if action == 'done':
                    report['checks'] = command['checks']
                    break
                if action == 'failed':
                    raise AssertionError(command['reason'])
                if action == 'price':
                    price = next(prices)
                    assert command['price'] == price
                    quote_index += 1
                    # Fixed regular-session source times; receipt really occurs
                    # after the UI order. These are labeled late fixture arrivals.
                    source = datetime(2026,11,10,15,tzinfo=UTC)+timedelta(seconds=quote_index*10)
                    with ObservationStore(market) as store:
                        store.record(dict(id='AAPL',time=int(source.timestamp()*1000),price=price,test_data=True),
                                     datetime.now(UTC), source_time_utc=source.isoformat())
                elif action == 'restart':
                    stop(backend)
                    backend = start_backend()
                    report['restarted_backend_pid'] = backend.pid
                    assert backend.pid != report['initial_backend_pid']
                elif action != 'snapshot':
                    raise ValueError('Unexpected browser action')
                result = sql_state(state)
                report['phases'][command.get('phase', action)] = result
                driver.stdin.write(json.dumps(result)+'\n'); driver.stdin.flush()
            assert driver.wait(timeout=10) == 0
            assert report.get('checks'), 'Driver did not finish its UI checks'
            final = sql_state(state)
            assert (final['cash'], final['shares'], final['total_fills']) == ('1025',0,3)
            assert len(final['orders']) == 4 and final['orders'][-1]['status']=='rejected'
            assert [fill['price'] for fill in final['fills']] == ['100','110','105']
            assert [fill['quantity'] for fill in final['fills']] == [4,1,3]
            with ObservationStore(market) as store:
                saved = store.snapshot()
            assert len(saved['observations']) == len(saved['receipts']) == 3
            report.update(result='PASS', final_sql=final, observations=saved)
        except BaseException as failure:
            report['failure'] = str(failure)
            logs.seek(0); (output/'services.log').write_text(logs.read())
            raise
        finally:
            stop(driver); stop(frontend); stop(backend)
            (output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
            print(json.dumps({key:report[key] for key in ('result','checks','failure') if key in report}, indent=2))
            print('Stopped paper SmokeTest services/browser; removed disposable account/observations.')


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('/tmp/arbitrade-paper-results'))
    args=parser.parse_args()
    verify(args.output.resolve())
