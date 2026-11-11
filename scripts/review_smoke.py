"""Analyst and reviewer browser check with immutable inputs and ledger audit."""

import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import tempfile

from scripts.smoke_test import ROOT, stop, wait_ready


def paper_records(path):
    with closing(sqlite3.connect(path)) as c:
        tables=[row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'paper_%' ORDER BY name")]
        return {table:c.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall() for table in tables}


def verify(output):
    output.mkdir(parents=True,exist_ok=True)
    for port in (18000,15173):
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);probe.bind(('127.0.0.1',port))
    backend=frontend=None
    report=dict(result='FAIL',model_call_kind='controlled',market_data_kind='constructed')
    with tempfile.TemporaryDirectory(prefix='arbitrade-decisions-') as directory,tempfile.TemporaryFile(mode='w+') as logs:
        state=Path(directory)/'state.sqlite3';market=Path(directory)/'observations.sqlite3'
        environment=dict(os.environ,ARBITRADE_CONFIG_DATABASE=str(state),ARBITRADE_DATABASE=str(market),
                         ARBITRADE_LIVE_FEED='off',ARBITRADE_PAPER_ORDER_SIZE='100',ARBITRADE_BACKEND_PORT='18000',ARBITRADE_FRONTEND_PORT='15173',
                         PYTHONPATH=str(ROOT/'backend/.packages'))
        # Fixture imports don't load backend/.env, and cannot make live provider calls.
        environment.pop('OPENAI_API_KEY',None)
        def launch(command):return subprocess.Popen(command,cwd=ROOT,env=environment,stdout=logs,stderr=logs,start_new_session=True)
        try:
            backend=launch(['/usr/bin/python','-m','uvicorn','scripts.review_fixture:app','--host','127.0.0.1','--port','18000'])
            wait_ready(backend,'http://127.0.0.1:18000/api/health')
            before=paper_records(state)
            frontend=launch(['npm','--prefix','frontend','run','dev']);wait_ready(frontend,'http://127.0.0.1:15173')
            result=subprocess.run(['node','scripts/review_smoke.mjs',str(output)],cwd=ROOT,capture_output=True,text=True,timeout=120)
            (output/'browser.log').write_text(result.stderr)
            if result.returncode:raise AssertionError(result.stdout+result.stderr)
            assert before==paper_records(state),'Decision path changed paper ledger'
            with closing(sqlite3.connect(state)) as c:
                c.row_factory=sqlite3.Row
                saved=[dict(row) for row in c.execute('SELECT * FROM decisions ORDER BY created_at')]
                reviews=[dict(row) for row in c.execute('SELECT * FROM decision_reviews ORDER BY rowid')]
                calls=[dict(row) for row in c.execute('SELECT * FROM fixture_role_receipts ORDER BY id')]
                snapshots=[dict(row) for row in c.execute('SELECT id,payload_json,payload_sha256 FROM decision_snapshots')]
            assert [row['status'] for row in saved]==['valid','review_rejected','invalid_proposal','review_timeout','review_malformed_answer']
            assert saved[0]['proposal']=='hold' and not any(row['paper_order_eligible'] for row in saved)
            assert len(calls)==10
            browser=json.loads(result.stdout)
            for index,review in enumerate(reviews):
                saved_review=json.loads(review['payload_json'])
                assert saved_review==browser['decisions'][index]['review']
                a,b=calls[index*2:index*2+2]
                assert [a['role'],b['role']]==['analyst','reviewer']
                assert a['snapshot_sha256']==b['snapshot_sha256']==saved_review['snapshot_sha256']
                assert json.loads(b['evidence_json'])['analyst']['proposal']==saved_review['analyst']['proposal']
            report.update(result='PASS',role_calls=calls,reviews=reviews,**json.loads(result.stdout),saved_decisions=saved,snapshots=snapshots,paper_ledger_unchanged=True)
        except BaseException as failure:
            report['failure']=str(failure);logs.seek(0);(output/'services.log').write_text(logs.read());raise
        finally:
            stop(frontend);stop(backend)
            (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
            print(json.dumps({key:report[key] for key in ('result','checks','failure') if key in report},indent=2))
            print('Stopped controlled decision services/browser; removed disposable databases.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,default=Path('/tmp/arbitrade-review-results'))
    args=parser.parse_args();verify(args.output.resolve())
