"""Read-only voice context distinguishes proposals, orders and recorded fills."""
from contextlib import closing
import io
import json
import os
import sqlite3
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from backend import test_automation as fixture
from backend.chart_decisions import decide_image
from backend.voice import summary,records,configuration,LiveVoice
from backend.decision_provider import ProviderFailure


class VoiceTests(unittest.IsolatedAsyncioTestCase):
    setUp=fixture.AutomationTests.setUp
    quote=fixture.AutomationTests.quote
    claim=fixture.AutomationTests.claim
    capture=fixture.AutomationTests.capture
    approved=fixture.AutomationTests.approved

    def stored(self):
        with closing(sqlite3.connect(self.state)) as c:
            tables=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            return {t:c.execute('SELECT * FROM '+t+' ORDER BY rowid').fetchall() for t in tables}

    async def test_manual_no_trade_summary_read_only_and_missing_review(self):
        claim=self.claim();decision=await decide_image(self.ds,claim['snapshot']['snapshot']['snapshot_id'],self.capture(claim))
        before=self.stored();r=summary(self.state,decision['id'])
        self.assertEqual(r['analyst']['proposal'],'buy');self.assertEqual(r['reviewer']['verdict'],'accept')
        self.assertEqual(r['symbol'],'AAPL');self.assertEqual(r['indicators']['crossover'],'up')
        self.assertFalse(r['paper_outcome']['trade_recorded']);self.assertIsNone(r['paper_outcome']['order'])
        self.assertEqual(r['current_recorded_account']['cash'],'1000');self.assertEqual(before,self.stored())
        self.assertIn(decision['id'],[d['id'] for d in records(self.state)])
        with closing(sqlite3.connect(self.state)) as c,c:c.execute('DELETE FROM decision_reviews WHERE decision_id=?',(decision['id'],))
        self.assertIsNone(summary(self.state,decision['id'])['reviewer'])
        with self.assertRaisesRegex(ValueError,'not found'):summary(self.state,'unknown')

    async def test_pending_and_filled_outcomes_match_fill_pnl_and_frozen_balances(self):
        a=await self.approved();r=summary(self.state,a['decision_id'])
        self.assertEqual(r['paper_outcome']['order']['status'],'pending');self.assertFalse(r['paper_outcome']['trade_recorded'])
        self.quote('2026-11-10T15:09:10Z',20);before=self.stored();r=summary(self.state,a['decision_id'])
        self.assertTrue(r['paper_outcome']['trade_recorded'])
        self.assertEqual(r['paper_outcome']['fill']['quantity'],4);self.assertEqual(r['paper_outcome']['fill']['price'],'20')
        self.assertEqual(r['paper_outcome']['fill_account']['cash'],'920');self.assertEqual(r['paper_outcome']['fill_account']['shares'],4)
        self.assertEqual(r['frozen_account']['cash'],'1000');self.assertEqual(r['current_recorded_account']['cash'],'920')
        self.assertEqual(before,self.stored())
        self.assertNotIn('source_database',json.dumps(r));self.assertNotIn('payload_json',json.dumps(r))

    async def test_provider_body_private_key_and_typed_webrtc_answer(self):
        claim=self.claim();d=await decide_image(self.ds,claim['snapshot']['snapshot']['snapshot_id'],self.capture(claim));r=summary(self.state,d['id'])
        config=configuration(r);self.assertEqual(config['model'],'gpt-live-1');self.assertFalse(config['store'])
        self.assertNotIn('tools',config);self.assertIn('No trading',config['instructions'])
        self.assertEqual(json.loads(config['input'][0]['content'][0]['text'].split('\n',1)[1])['decision_id'],d['id'])
        reply={'session':{'id':'live_keep_opaque'},'transport':{'type':'webrtc','sdp':'v=0\r\nanswer'},'unexpected':'must_not_return'}
        with patch.dict(os.environ,{'OPENAI_API_KEY':'unit-placeholder-only'}),patch('backend.voice.urlopen',return_value=io.BytesIO(json.dumps(reply).encode())) as post:
            result=LiveVoice().create('v=0\r\nm=audio 9 RTP/AVP 0',r)
        self.assertEqual(result['session']['id'],'live_keep_opaque');self.assertNotIn('unexpected',result)
        body=json.loads(post.call_args.args[0].data);self.assertEqual(body['session'],config);self.assertEqual(body['transport']['type'],'webrtc')
        self.assertNotIn('unit-placeholder-only',json.dumps(body))

    async def test_provider_failures_are_sanitized_and_do_not_write_records(self):
        before=self.stored()
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(ProviderFailure) as e:LiveVoice().create('v=0',{})
            self.assertEqual(e.exception.status,'missing_credentials')
        for failure,code in [(TimeoutError('private error'),'voice_provider_timeout'),
            (HTTPError('https://api.openai.com/v1/live/sessions',401,'secret echo',{},None),'voice_http_401')]:
            with patch.dict(os.environ,{'OPENAI_API_KEY':'unit-placeholder-only'}),patch('backend.voice.urlopen',side_effect=failure):
                with self.assertRaises(ProviderFailure) as e:LiveVoice().create('v=0',{})
                self.assertEqual(str(e.exception),code)
        with patch.dict(os.environ,{'OPENAI_API_KEY':'unit-placeholder-only'}),patch('backend.voice.urlopen',return_value=io.BytesIO(b'{}')):
            with self.assertRaises(ProviderFailure) as e:LiveVoice().create('v=0',{})
            self.assertEqual(e.exception.status,'malformed_answer')
        self.assertEqual(before,self.stored())
