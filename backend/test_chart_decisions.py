"""Image/cutoff binding, durable answers and execution-ineligibility rules."""
import base64
from contextlib import closing
import json
import sqlite3
import struct
import zlib
from unittest.mock import patch

from backend.chart_decisions import decide_image,decode_png,manifest,questions
from backend.decision_provider import MODEL,OpenAIDecisions
from backend import test_decisions as existing


def png(binding):
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    data=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',64,64,8,2,0,0,0))
    data+=chunk(b'tEXt',b'arbitrade_snapshot\x00'+json.dumps(binding).encode())
    data+=chunk(b'IDAT',zlib.compress(b''.join(b'\0'+bytes([y,0,0])*64 for y in range(64))))+chunk(b'IEND',b'')
    return 'data:image/png;base64,'+base64.b64encode(data).decode()


def answers(visual='up',evidence='sufficient'):
    choices=dict(action='hold',crossover=visual,evidence=evidence)
    return dict(model=MODEL,answers=[dict(type='choice',name=q['name'],choice=choices[q['name']],confidence=1,
        probabilities=[dict(value=v['value'],probability=int(v['value']==choices[q['name']])) for v in q['choices']]) for q in questions()])


# Reuse fixture utilities, without inheriting/rerunning the old tests.
class ChartDecisionTests(existing.DecisionTests.__bases__[0]):
    setUp=existing.DecisionTests.setUp
    freeze=existing.DecisionTests.freeze
    paper_records=existing.DecisionTests.paper_records

    def capture(self):
        snapshot=self.freeze();saved=self.service.get_snapshot(snapshot['snapshot_id']);binding=manifest(saved)
        return snapshot['snapshot_id'],dict(image_url=png(binding),manifest=binding)

    async def test_saved_png_answers_by_name_and_no_ledger_changes(self):
        sid,capture=self.capture();before=self.paper_records()
        received=[]
        def call(snapshot,image_url,qs):
            received.append((snapshot,image_url,qs))
            response=answers();response['answers'].reverse();return response
        self.provider.decide_image=call
        result=await decide_image(self.service,sid,capture)
        self.assertEqual(result['status'],'valid');self.assertEqual(result['proposal'],'hold')
        self.assertEqual(result['image_analysis']['comparison'],'match')
        self.assertEqual(set(result['image_analysis']['answers']),{'action','crossover','evidence'})
        self.assertEqual(result,self.service.get_decision(result['id']))
        self.assertFalse(result['paper_order_eligible'])
        with closing(sqlite3.connect(self.state)) as c:
            raw=c.execute('SELECT png FROM decision_images WHERE decision_id=?',(result['id'],)).fetchone()[0]
        self.assertEqual(raw,decode_png(received[0][1])[0]);self.assertEqual(before,self.paper_records())
        with patch.object(OpenAIDecisions,'post',return_value=answers()) as post:
            OpenAIDecisions().decide_image(received[0][0],received[0][1],received[0][2])
        body=post.call_args.args[0];self.assertEqual(len(body['input']),1)
        self.assertEqual(body['input'][0]['role'],'user')
        self.assertEqual(body['input'][0]['content'][0]['image_url'],capture['image_url'])
        self.assertEqual(body['input'][0]['content'][1]['data']['snapshot_id'],sid)

    async def test_bad_png_and_snapshot_swap_never_reach_provider(self):
        sid,capture=self.capture();self.provider.decide_image=lambda *args:self.fail('Provider should not be reached')
        for url in ['data:image/png;base64,!!!!',capture['image_url'][:-8], 'https://example.com/chart.png']:
            result=await decide_image(self.service,sid,dict(capture,image_url=url))
            self.assertEqual(result['status'],'invalid_image');self.assertFalse(result['paper_order_eligible'])
        binding=dict(capture['manifest'],snapshot_id='different-id')
        result=await decide_image(self.service,sid,dict(image_url=png(binding),manifest=binding))
        self.assertEqual(result['status'],'snapshot_mismatch')
        self.assertIn('recapture',result['error_code'])
        result=await decide_image(self.service,'missing',capture);self.assertEqual(result['status'],'missing_input')

    async def test_conflict_insufficient_and_unreadable_are_ineligible(self):
        sid,capture=self.capture();before=self.paper_records()
        for visual,evidence,status in [('down','sufficient','conflicting_signal'),('unreadable','sufficient','unreadable_image'),
                                      ('up','insufficient','insufficient_evidence'),('up','unreadable','unreadable_image')]:
            self.provider.decide_image=lambda *args:answers(visual,evidence)
            result=await decide_image(self.service,sid,capture)
            self.assertEqual(result['status'],status);self.assertFalse(result['paper_order_eligible'])
            self.assertEqual(result['image_analysis']['answers']['crossover']['choice'],visual)
        self.assertEqual(before,self.paper_records())

    async def test_missing_duplicate_and_invalid_named_answers(self):
        sid,capture=self.capture()
        for mutation in ['missing','duplicate','invalid']:
            response=answers()
            if mutation=='missing':response['answers'].pop()
            if mutation=='duplicate':response['answers'][2]=response['answers'][1]
            if mutation=='invalid':response['answers'][1]['choice']='sideways'
            self.provider.decide_image=lambda *args:response
            result=await decide_image(self.service,sid,capture)
            self.assertEqual(result['status'],'malformed_answer');self.assertFalse(result['paper_order_eligible'])

    async def test_range_and_named_indicator_frozen_with_cutoff(self):
        with self.assertRaisesRegex(ValueError,'outside the visible range'):
            self.freeze(chart_end='2026-11-10T15:02:00Z')
        from backend.indicator_store import IndicatorStore
        store=IndicatorStore(self.state);store.create('AAPL','1m','Range 2','price_range',{'window':2})
        snapshot=self.freeze(chart_start='2026-11-10T15:02:00Z',instances=store.list('AAPL','1m'))
        self.assertEqual(snapshot['chart']['candles'][0]['timestamp'],'2026-11-10T15:02:00Z')
        self.assertEqual(snapshot['chart']['candles'][-1]['timestamp'],'2026-11-10T15:04:00Z')
        self.assertEqual(len(snapshot['chart']['indicators'][0]['rows']),3)
