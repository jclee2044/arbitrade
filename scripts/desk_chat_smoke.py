"""Browser SmokeTest for the desk chat, with disposable chart and audit storage."""
import argparse
import os
import json
import sys
from hashlib import sha256
from pathlib import Path
import socket
import sqlite3
import subprocess
import tempfile
from contextlib import closing

from scripts.chart_smoke import paper_records
from scripts.smoke_test import ROOT, stop, wait_ready


def verify(output, live, conversation, strategy=False):
    output.mkdir(parents=True, exist_ok=True)
    for port in (18164, 15264):
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(('127.0.0.1', port))
    with tempfile.TemporaryDirectory(prefix='arbitrade-desk-chat-') as directory, (output / 'services.log').open('w') as log:
        state = Path(directory) / 'state.sqlite3'
        env = dict(os.environ, ARBITRADE_CONFIG_DATABASE=str(state),
                   ARBITRADE_DATABASE=str(Path(directory) / 'market.sqlite3'),
                   ARBITRADE_LIVE_FEED='off', ARBITRADE_BACKEND_PORT='18164', ARBITRADE_FRONTEND_PORT='15264',
                   PYTHONPATH=str(ROOT / 'backend/.packages'),
                   ARBITRADE_CHAT_SMOKE_PROVIDER='live' if live else 'controlled',
                   ARBITRADE_CHAT_CONVERSATION='1' if conversation else '0')
        if not live:
            env.pop('OPENAI_API_KEY', None)

        def launch(command):
            return subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=log, start_new_session=True)

        backend = frontend = None
        try:
            backend = launch([sys.executable, '-m', 'uvicorn', 'scripts.desk_chat_fixture:app', '--port', '18164'])
            wait_ready(backend, 'http://127.0.0.1:18164/api/health')
            before = paper_records(state)
            frontend = launch(['npm', '--prefix', 'frontend', 'run', 'dev'])
            wait_ready(frontend, 'http://127.0.0.1:15264')
            driver = 'scripts/daily_strategy_smoke.mjs' if strategy else 'scripts/desk_chat_smoke.mjs'
            subprocess.run(['node', driver, str(output), 'live' if live else 'controlled',
                            'conversation' if conversation else 'single'],
                           cwd=ROOT, check=True, timeout=200 if live else 60)
            after = paper_records(state)
            if strategy:
                assert after == before
                expected = 3
            elif conversation:
                for table in ('paper_orders', 'paper_fills'):
                    assert after[table] == before[table]
                expected = 2 if live else 3
            else:
                assert after == before
                expected = 1 if live else 3
            with closing(sqlite3.connect(state)) as db:
                assert db.execute('SELECT COUNT(*) FROM classroom_decisions').fetchone()[0] == expected
                if strategy:
                    evidence = json.loads((output / 'strategy.json').read_text())
                    facts = evidence['selected_facts']
                    payloads = db.execute('SELECT facts, png_hash FROM strategy_payloads ORDER BY rowid').fetchall()
                    saved = db.execute('SELECT result_json,png FROM classroom_decisions ORDER BY rowid').fetchall()
                    assert len(payloads) == len(saved) == 3
                    for (packet, digest), (record, png) in zip(payloads, saved):
                        assert json.loads(packet) == json.loads(record)['strategy_facts'] == facts
                        assert sha256(png).hexdigest() == digest
                    assert db.execute('SELECT COUNT(*) FROM desk_assessments').fetchone()[0] == 1
                    print('PASS: all provider input packets and PNG digests match the saved decision audits')
                elif conversation:
                    assert db.execute('SELECT COUNT(*) FROM desk_assessments WHERE data_mode = ?', ('replay',)).fetchone()[0] == expected
            print('PASS: expected chart audit rows; paper orders and fills unchanged')
        finally:
            stop(frontend)
            stop(backend)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('/tmp/arbitrade-desk-chat'))
    parser.add_argument('--live', action='store_true', help='Use backend credentials and real OpenAI calls with constructed chart data')
    parser.add_argument('--conversation', action='store_true', help='Compare two consecutive chart snapshots in one chat')
    parser.add_argument('--strategy', action='store_true', help='Verify frozen strategy evidence with controlled providers')
    args = parser.parse_args()
    if args.strategy and (args.live or args.conversation):
        parser.error('--strategy runs its own offline scenario')
    verify(args.output.resolve(), args.live, args.conversation, args.strategy)
