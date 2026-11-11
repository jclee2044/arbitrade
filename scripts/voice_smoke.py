"""Read-only voice browser WebRTC check with immutable inputs and ledger audit."""

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
        tables=[row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
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
                         ARBITRADE_LIVE_FEED='off',ARBITRADE_BACKEND_PORT='18000',ARBITRADE_FRONTEND_PORT='15173',
                         PYTHONPATH=str(ROOT/'backend/.packages'))
        # Fixture imports don't load backend/.env, and cannot make live provider calls.
        environment.pop('OPENAI_API_KEY',None)
        def launch(command):return subprocess.Popen(command,cwd=ROOT,env=environment,stdout=logs,stderr=logs,start_new_session=True)
        try:
            backend=launch(['/usr/bin/python','-m','uvicorn','scripts.voice_fixture:app','--host','127.0.0.1','--port','18000'])
            wait_ready(backend,'http://127.0.0.1:18000/api/health')
            before=paper_records(state)
            frontend=launch(['npm','--prefix','frontend','run','dev']);wait_ready(frontend,'http://127.0.0.1:15173')
            result=subprocess.run(['node','scripts/voice_smoke.mjs',str(output)],cwd=ROOT,capture_output=True,text=True,timeout=120)
            (output/'browser.log').write_text(result.stderr)
            if result.returncode:raise AssertionError(result.stdout+result.stderr)
            assert before==paper_records(state),'Decision path changed paper ledger'
            report.update(result='PASS',**json.loads(result.stdout),all_sqlite_records_unchanged=True,live_microphone_speaker_check='PENDING; mock captions and fake microphone are not live speech')
        except BaseException as failure:
            report['failure']=str(failure);logs.seek(0);(output/'services.log').write_text(logs.read());raise
        finally:
            stop(frontend);stop(backend)
            (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
            print(json.dumps({key:report[key] for key in ('result','checks','failure') if key in report},indent=2))
            print('Stopped controlled decision services/browser; removed disposable databases.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,default=Path('/tmp/arbitrade-voice-results'))
    args=parser.parse_args();verify(args.output.resolve())
