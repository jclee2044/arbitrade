"""Disposable browser automation reference with SQLite audit and actual restart."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import tempfile
from scripts.smoke_test import ROOT,stop,wait_ready


def audit(path):
    with closing(sqlite3.connect(path)) as c:
        c.row_factory=sqlite3.Row
        account=c.execute("SELECT * FROM paper_accounts WHERE mode='test'").fetchone()
        assert account is not None
        identifier=account['id'];fills=[dict(r) for r in c.execute('''SELECT f.*,a.decision_id FROM paper_fills f
            JOIN automation_attempts a ON a.fill_id=f.id WHERE a.account_id=?''',(identifier,))]
        shares=c.execute('SELECT shares FROM paper_positions WHERE account_id=?',(identifier,)).fetchone()[0]
        assert account['cash']=='920' and shares==4 and len(fills)==1
        assert c.execute('SELECT COUNT(*) FROM paper_orders WHERE account_id=?',(identifier,)).fetchone()[0]==1
        linked=c.execute('SELECT cash,shares,total FROM paper_pnl_history WHERE fill_id=?',(fills[0]['id'],)).fetchone()
        assert tuple(linked)==('920',4,'0')
        assert c.execute("SELECT cash FROM paper_accounts WHERE id='live'").fetchone()[0]=='948'
        assert c.execute("SELECT shares FROM paper_positions WHERE account_id='live'").fetchone()[0]==4
        captures=c.execute('SELECT snapshot_id,png FROM fixture_captures').fetchall()
        for row in captures:
            saved=c.execute('SELECT i.png FROM decision_images i JOIN decisions d ON d.id=i.decision_id WHERE d.snapshot_id=?',(row[0],)).fetchone()
            assert saved[0]==row[1]
        return dict(account_id=identifier,cash=account['cash'],shares=shares,fills=fills,captures_match=True)


def verify(output):
    output.mkdir(parents=True,exist_ok=True)
    for port in (18000,15173):
        with socket.socket() as s:s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind(('127.0.0.1',port))
    backend=frontend=driver=None;report=dict(result='FAIL',provider_responses='controlled/mocked',market_data='constructed recorded fixture')
    with tempfile.TemporaryDirectory(prefix='arbitrade-automation-') as directory,tempfile.TemporaryFile(mode='w+') as log:
        state=Path(directory)/'state.sqlite3';market=Path(directory)/'market.sqlite3'
        env=dict(os.environ,ARBITRADE_CONFIG_DATABASE=str(state),ARBITRADE_DATABASE=str(market),ARBITRADE_PAPER_ORDER_SIZE='4',
            ARBITRADE_LIVE_FEED='off',ARBITRADE_BACKEND_PORT='18000',ARBITRADE_FRONTEND_PORT='15173',PYTHONPATH=str(ROOT/'backend/.packages'))
        env.pop('OPENAI_API_KEY',None)
        def launch(cmd):return subprocess.Popen(cmd,cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
        def start_backend():
            p=launch(['/usr/bin/python','-m','uvicorn','scripts.automation_fixture:app','--host','127.0.0.1','--port','18000'])
            wait_ready(p,'http://127.0.0.1:18000/api/health');return p
        try:
            backend=start_backend();report['initial_backend_pid']=backend.pid
            frontend=launch(['npm','--prefix','frontend','run','dev']);wait_ready(frontend,'http://127.0.0.1:15173')
            driver=subprocess.Popen(['node','scripts/automation_smoke.mjs',str(output)],cwd=ROOT,env=env,
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,text=True,start_new_session=True)
            for line in driver.stdout:
                command=json.loads(line)
                if command['action']=='done':report.update(result='PASS',**{k:v for k,v in command.items() if k!='action'});break
                if command['action']=='failed':raise AssertionError(command['reason'])
                if command['action']=='audit':report.setdefault('audits',[]).append(audit(state))
                elif command['action']=='restart':
                    stop(backend);backend=start_backend();report['restarted_backend_pid']=backend.pid
                else:raise AssertionError('Unexpected driver command')
                driver.stdin.write('{}\n');driver.stdin.flush()
            driver.wait(timeout=10);assert driver.returncode==0 and report['result']=='PASS'
            report['final_audit']=audit(state)
            with closing(sqlite3.connect(state)) as c:
                c.row_factory=sqlite3.Row
                report['attempts']=[dict(r) for r in c.execute('SELECT * FROM automation_attempts ORDER BY rowid')]
        except BaseException as failure:
            report['failure']=str(failure);log.seek(0);(output/'services.log').write_text(log.read());raise
        finally:
            stop(driver);stop(frontend);stop(backend)
            (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
            print(json.dumps({k:report[k] for k in ('result','checks','failure') if k in report},indent=2))
            print('Stopped automation test services/browser; removed disposable databases.')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,default=Path('/tmp/arbitrade-automation-results'))
    verify(parser.parse_args().output.resolve())
