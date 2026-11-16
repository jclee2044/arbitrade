"""Assignment contract: pixels/context only, typed choices, no ledger access."""
import base64
import json
from pathlib import Path
from contextlib import closing
import sqlite3
import struct
import tempfile
import unittest
import zlib
from types import SimpleNamespace

from pydantic import ValidationError
from backend.classroom_decisions import ChartCapture, ClassroomDecisions, CHOICES, QUESTION, payload
from backend.decision_provider import MODEL, ProviderFailure


def png():
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    raw = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 64, 64, 8, 2, 0, 0, 0))
    raw += chunk(b'IDAT', zlib.compress(b''.join(b'\0' + bytes([y, 0, 0]) * 64 for y in range(64)))) + chunk(b'IEND', b'')
    return 'data:image/png;base64,' + base64.b64encode(raw).decode()


def capture():
    return dict(ticker='AAPL', interval='1m', captured_at='2026-11-12T16:00:10Z',
        candle_timestamp='2026-11-12T16:00:00Z', image=png(), visible_candles=20,
        last_quote_at=None, last_source_at=None, is_stale=True, volume_status='unavailable')


def answer(choice='wait'):
    return dict(model=MODEL, answers=[dict(name=QUESTION, type='choice', choice=choice)])


class Provider:
    name, model, mode, timeout = 'controlled-classroom', MODEL, 'controlled', .1
    def __init__(self): self.received = []; self.response = answer(); self.failure = None
    def post(self, body):
        self.received.append(body)
        if self.failure: raise self.failure
        return self.response


class ClassroomTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'state.sqlite3'; self.provider = Provider()
        self.service = ClassroomDecisions(self.path, self.provider)
        with closing(sqlite3.connect(self.path)) as c, c:
            c.execute('CREATE TABLE paper_sentinel (cash TEXT)'); c.execute("INSERT INTO paper_sentinel VALUES ('1000')")

    async def test_all_choices_payload_and_durable_image_without_ledger_changes(self):
        for choice in CHOICES:
            self.provider.response = answer(choice)
            result = await self.service.decide(ChartCapture.model_validate(capture()))
            self.assertEqual((result['status'], result['choice']), ('valid', choice))
            self.assertEqual(result, self.service.get(result['id']))
            self.assertEqual(self.service.image(result['id']), base64.b64decode(capture()['image'].split(',')[1]))
            self.assertFalse(result['paper_order_eligible'])
        body = self.provider.received[0]; content = body['input'][0]['content']
        self.assertEqual([part['type'] for part in content], ['input_text', 'input_json', 'input_image'])
        self.assertEqual(set(content[1]['data']), {'ticker','interval','captured_at','candle_timestamp','visible_candles','is_stale','volume_status'})
        self.assertEqual([c['value'] for c in body['questions'][0]['choices']], list(CHOICES))
        self.assertEqual(content[2]['image_url'], capture()['image'])
        with closing(sqlite3.connect(self.path)) as c, c:
            self.assertEqual(c.execute('SELECT * FROM paper_sentinel').fetchall(), [('1000',)])
            self.assertEqual(c.execute('SELECT COUNT(*) FROM classroom_decisions').fetchone()[0], 3)

    async def test_reject_extra_data_and_invalid_png_before_provider(self):
        for key in ['candles','account','indicators','crossover','snapshot_id']:
            with self.assertRaises(ValidationError): ChartCapture.model_validate(dict(capture(), **{key: []}))
        with self.assertRaises(ProviderFailure):
            await self.service.decide(ChartCapture.model_validate(dict(capture(), image='data:image/png;base64,!!!!')))
        self.assertEqual(self.provider.received, [])
        for fields in [dict(visible_candles=0), dict(is_stale='false'), dict(captured_at='2026-11-12'), dict(candle_timestamp='2027-01-01T00:00:00Z')]:
            with self.assertRaises(ValidationError): ChartCapture.model_validate(dict(capture(), **fields))

    async def test_errors_never_invent_wait(self):
        for response in [answer('buy'), {}, dict(model=MODEL, answers=[]), dict(model=MODEL, answers=[dict(name=QUESTION,type='refusal')])]:
            self.provider.response = response
            result = await self.service.decide(ChartCapture.model_validate(capture()))
            self.assertIn(result['status'], ('malformed_answer','refused')); self.assertIsNone(result['choice'])
        for status in ['timeout','missing_credentials','provider_error']:
            self.provider.failure = ProviderFailure(status, 'controlled_error')
            result = await self.service.decide(ChartCapture.model_validate(capture()))
            self.assertEqual(result['status'], status); self.assertIsNone(result['choice'])

    async def test_probabilities_optional_and_validated(self):
        self.provider.response = answer('long')
        self.provider.response['answers'][0].update(confidence=.8, probabilities=[dict(value='long',probability=.8)])
        result = await self.service.decide(ChartCapture.model_validate(capture()))
        self.assertEqual(result['answer']['confidence'], .8)
        self.provider.response['answers'][0]['probabilities'][0]['probability'] = float('nan')
        result = await self.service.decide(ChartCapture.model_validate(capture()))
        self.assertEqual(result['status'], 'malformed_answer'); self.assertIsNone(result['choice'])

    async def test_http_dispatch_and_validation(self):
        from backend.main import app
        previous = getattr(app.state, 'classroom_decisions', None)
        app.state.classroom_decisions = self.service
        try:
            class Client:
                async def request(self, method, path, data=None):
                    body = json.dumps(data).encode() if data is not None else b''
                    messages = []
                    async def receive(): return dict(type='http.request', body=body, more_body=False)
                    async def send(message): messages.append(message)
                    await app(dict(type='http', method=method, path=path, query_string=b'',
                        headers=[(b'content-type', b'application/json')], server=('test', 80),
                        client=('127.0.0.1', 1234), scheme='http', root_path='', http_version='1.1'), receive, send)
                    status = next(m['status'] for m in messages if m['type']=='http.response.start')
                    content = b''.join(m.get('body', b'') for m in messages if m['type']=='http.response.body')
                    return SimpleNamespace(status_code=status, content=content, json=lambda: json.loads(content))
                async def post(self, path, json): return await self.request('POST', path, json)
                async def get(self, path): return await self.request('GET', path)
            client = Client()
            response = await client.post('/api/decisions', json=dict(capture=capture()))
            self.assertEqual(response.status_code, 200); record = response.json()
            self.assertEqual((await client.get('/api/decisions/'+record['id'])).json(), record)
            # Image route also checks the legacy table before the classroom table.
            with closing(sqlite3.connect(self.path)) as c, c: c.execute('CREATE TABLE decision_images (decision_id TEXT, png BLOB)')
            old = getattr(app.state, 'decisions', None)
            app.state.decisions = SimpleNamespace(path=self.path)
            try:
                self.assertEqual((await client.get(record['image_url'])).content, self.service.image(record['id']))
            finally: app.state.decisions = old
            response = await client.post('/api/decisions', json=dict(capture=dict(capture(), candles=[])))
            self.assertEqual(response.status_code, 422)
            response = await client.post('/api/decisions', json=dict(capture=capture(), candles=[]))
            self.assertEqual(response.status_code, 422)
        finally: app.state.classroom_decisions = previous
