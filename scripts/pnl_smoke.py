"""Browser P&L reference, direct SQLite comparison, dedup and backend restart."""

import argparse
from contextlib import closing
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


def sql_state(path):
    with closing(sqlite3.connect(path)) as c:
        c.row_factory=sqlite3.Row
        return dict(cash=c.execute("SELECT cash FROM paper_accounts WHERE id='live'").fetchone()[0],
                    shares=c.execute("SELECT COALESCE(SUM(shares),0) FROM paper_positions WHERE account_id='live'").fetchone()[0],
                    fills=c.execute('SELECT COUNT(*) FROM paper_fills').fetchone()[0],
                    history=[dict(row) for row in c.execute("SELECT * FROM paper_pnl_history WHERE account_id='live' ORDER BY id")])


def verify(output):
    output.mkdir(parents=True,exist_ok=True)
    for port in (18000,15173):
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1); probe.bind(('127.0.0.1',port))
    backend=frontend=driver=None
    report=dict(result='FAIL',input='CONSTRUCTED P&L test_data=true; disposable database and simulated clock',phases={})
    with tempfile.TemporaryDirectory(prefix='arbitrade-pnl-') as directory, tempfile.TemporaryFile(mode='w+') as logs:
        market=Path(directory)/'observations.sqlite3'; state=Path(directory)/'chart-config.sqlite3'
        clock_file=Path(directory)/'clock.txt'; start=datetime(2026,11,10,15,tzinfo=UTC)
        def clock(seconds):
            temporary=clock_file.with_suffix('.new')
            temporary.write_text((start+timedelta(seconds=seconds)).isoformat())
            temporary.replace(clock_file)
        clock(0)
        with ObservationStore(market):pass
        environment=dict(os.environ,ARBITRADE_DATABASE=str(market),ARBITRADE_CONFIG_DATABASE=str(state),
                         ARBITRADE_PNL_CLOCK=str(clock_file),ARBITRADE_LIVE_FEED='off',
                         ARBITRADE_BACKEND_PORT='18000',ARBITRADE_FRONTEND_PORT='15173',PYTHONPATH=str(ROOT/'backend/.packages'))
        def launch(command):
            return subprocess.Popen(command,cwd=ROOT,env=environment,stdout=logs,stderr=logs,start_new_session=True)
        def start_backend():
            process=launch(['/usr/bin/python','-m','uvicorn','scripts.pnl_fixture:app','--host','127.0.0.1','--port','18000'])
            wait_ready(process,'http://127.0.0.1:18000/api/health'); return process
        quotes=iter([(100,10),(110,40),(110,70),(95,100),(105,130)])
        advances=iter([60,120])
        try:
            backend=start_backend(); report['initial_backend_pid']=backend.pid
            frontend=launch(['npm','--prefix','frontend','run','dev']); wait_ready(frontend,'http://127.0.0.1:15173')
            driver=subprocess.Popen(['node','scripts/pnl_smoke.mjs',str(output)],cwd=ROOT,stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE,stderr=logs,text=True,bufsize=1,start_new_session=True)
            while line:=driver.stdout.readline():
                command=json.loads(line); action=command['action']
                if action=='done':report['checks']=command['checks']; break
                if action=='failed':raise AssertionError(command['reason'])
                if action=='price':
                    price,seconds=next(quotes)
                    assert (command['price'],command['seconds'])==(price,seconds)
                    timestamp=start+timedelta(seconds=seconds)
                    with ObservationStore(market) as store:
                        store.record(dict(id='AAPL',time=int(timestamp.timestamp()*1000),price=price,test_data=True),
                                     timestamp,source_time_utc=timestamp.isoformat())
                    clock(seconds)
                elif action=='advance':
                    seconds=next(advances); assert seconds==command['seconds']; clock(seconds)
                elif action=='restart':
                    stop(backend); backend=start_backend(); report['restarted_backend_pid']=backend.pid
                    assert backend.pid!=report['initial_backend_pid']
                elif action!='snapshot':raise ValueError('Unexpected browser action')
                result=sql_state(state); report['phases'][command.get('phase',action)]=result
                driver.stdin.write(json.dumps(result)+'\n'); driver.stdin.flush()
            assert driver.wait(timeout=10)==0 and report.get('checks')
            final=sql_state(state)
            expected=[('600',4,'0','0','0'),('600',4,'0','40','40'),('710',3,'10','30','40'),
                      ('710',3,'10','-15','-5'),('1025',0,'25','0','25')]
            assert [(r['cash'],r['shares'],r['realized'],r['unrealized'],r['total']) for r in final['history']]==expected
            assert final['fills']==3 and (final['cash'],final['shares'])==('1025',0)
            assert report['phases']['before-restart']['history']==report['phases']['after-backend-restart']['history']==final['history']
            report.update(result='PASS',expected=expected,final_sql=final)
        except BaseException as failure:
            report['failure']=str(failure); logs.seek(0); (output/'services.log').write_text(logs.read()); raise
        finally:
            stop(driver); stop(frontend); stop(backend)
            (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
            print(json.dumps({key:report[key] for key in ('result','checks','failure') if key in report},indent=2))
            print('Stopped P&L SmokeTest services/browser; removed disposable databases and fixture clock.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('/tmp/arbitrade-pnl-results'))
    args=parser.parse_args(); verify(args.output.resolve())
