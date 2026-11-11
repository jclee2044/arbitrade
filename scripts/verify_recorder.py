"""Repeatable recorder verification with labelled test data and process restart."""

import argparse
import asyncio
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=['write', 'reopen'])
    parser.add_argument('--database', type=Path)
    args = parser.parse_args()
    if args.phase:
        # Imports follow the normal backend module path from the project root.
        from backend.observations import ObservationStore
        from backend.yahoo_stream import check_subscription
        if args.database is None:
            parser.error('--phase requires --database')
        with ObservationStore(args.database) as store:
            if args.phase == 'write':
                message = {'id': 'AAPL', 'time': '1794234660000', 'price': 101,
                           'day_volume': '850', 'test_data': True}

                class TestClient:
                    def __init__(self, payload):
                        self.payload = payload

                    async def subscribe(self, symbols):
                        assert symbols == ['AAPL']

                    async def listen(self, handler):
                        handler(self.payload)
                        await asyncio.Event().wait()

                    async def close(self):
                        pass

                async def write():
                    for payload in (message, dict(message), {**message, 'price': 102}):
                        result = await check_subscription(
                            client_factory=lambda **kwargs: TestClient(payload), recorder=store,
                        )
                        assert result['receipt_verified'], result
                asyncio.run(write())
            print(json.dumps(store.snapshot()))
        return

    if args.database is not None:
        parser.error('Default verification creates its own disposable database')
    directory = Path(tempfile.mkdtemp(prefix='arbitrade-recorder-verification-'))
    database = directory / 'test-observations.sqlite3'
    snapshots = []
    for phase in ('write', 'reopen'):
        command = [sys.executable, '-m', 'scripts.verify_recorder', '--phase', phase, '--database', str(database)]
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=15)
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)
        snapshots.append(json.loads(result.stdout))
    before, after = snapshots
    assert before == after, 'Persisted rows changed after receiver process restart'
    assert len(after['observations']) == 2 and len(after['receipts']) == 3
    assert [r['observation_id'] for r in after['receipts']] == [1, 1, 2]
    assert [r['source_fields']['price'] for r in after['observations']] == [101, 102]
    assert all(r['source_fields']['test_data'] for r in after['observations'])
    assert all(r['supersedes_observation_id'] is None for r in after['observations'])
    print('CONSTRUCTED TEST DATA; no Yahoo connection was made.')
    print(json.dumps(after, indent=2))
    print('PASS: repeat -> same observation; changed value -> new observation; three receipts.')
    print('PASS: receiver process exited; new process reopened identical persisted records.')
    print('Disposable database retained under /tmp for inspection.')


if __name__ == '__main__':
    main()
