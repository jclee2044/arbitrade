"""One-command assignment browser SmokeTest, with payload/storage/paper audit."""
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
from scripts.chart_smoke import paper_records


def verify(output):
    output.mkdir(parents=True, exist_ok=True)
    for port in (18162, 15262):
        with socket.socket() as probe: probe.bind(('127.0.0.1', port))
    backend = frontend = None
    report = dict(result='FAIL', provider='controlled', market_data='constructed')
    with tempfile.TemporaryDirectory(prefix='arbitrade-classroom-') as directory, tempfile.TemporaryFile(mode='w+') as logs:
        state = Path(directory)/'state.sqlite3'
        env = dict(os.environ, ARBITRADE_CONFIG_DATABASE=str(state), ARBITRADE_DATABASE=str(Path(directory)/'market.sqlite3'),
            ARBITRADE_LIVE_FEED='off', ARBITRADE_BACKEND_PORT='18162', ARBITRADE_FRONTEND_PORT='15262', PYTHONPATH=str(ROOT/'backend/.packages'))
        env.pop('OPENAI_API_KEY', None)
        def launch(command): return subprocess.Popen(command, cwd=ROOT, env=env, stdout=logs, stderr=logs, start_new_session=True)
        try:
            backend = launch(['/usr/bin/python','-m','uvicorn','scripts.classroom_fixture:app','--host','127.0.0.1','--port','18162'])
            wait_ready(backend,'http://127.0.0.1:18162/api/health')
            before = paper_records(state)
            frontend = launch(['npm','--prefix','frontend','run','dev']); wait_ready(frontend,'http://127.0.0.1:15262')
            result = subprocess.run(['node','scripts/classroom_smoke.mjs',str(output)], cwd=ROOT, capture_output=True, text=True, timeout=90)
            (output/'browser.log').write_text(result.stderr)
            if result.returncode: raise AssertionError(result.stderr)
            assert paper_records(state) == before, 'Classroom decisions changed paper ledger'
            with closing(sqlite3.connect(state)) as c:
                rows = c.execute('SELECT id,result_json,png FROM classroom_decisions').fetchall()
                receipts = [json.loads(r[0]) for r in c.execute('SELECT body FROM classroom_receipts')]
                assert c.execute('SELECT COUNT(*) FROM decisions').fetchone()[0] == 0
                assert c.execute('SELECT COUNT(*) FROM automation_attempts').fetchone()[0] == 0
            assert len(rows) == len(receipts) == 6
            for (_, saved, png), body in zip(rows, receipts):
                import base64
                record = json.loads(saved); parts = body['input'][0]['content']
                assert set(parts[1]['data']) <= {'ticker','interval','captured_at','candle_timestamp','visible_candles','last_quote_at','last_source_at','is_stale','volume_status'}
                assert [v['value'] for v in body['questions'][0]['choices']] == ['long','short','wait']
                assert parts[1]['data'] == record['context']
                assert base64.b64decode(parts[2]['image_url'].split(',')[1]) == png
            report.update(json.loads(result.stdout), result='PASS', paper_ledger_unchanged=True, outgoing_payload_checked=True)
        except BaseException as error:
            report['failure'] = str(error); logs.seek(0); (output/'services.log').write_text(logs.read()); raise
        finally:
            stop(frontend); stop(backend)
            (output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
            print(json.dumps(report, indent=2))
            print('Stopped disposable services/browser and removed test databases.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('/tmp/arbitrade-classroom-results'))
    verify(parser.parse_args().output.resolve())
