"""One call per role, immutable shared evidence and Python's final veto."""
import asyncio
from contextlib import closing
import json
import sqlite3
import threading
from unittest.mock import patch

from backend import test_decisions as existing
from backend.chart_decisions import decide_image,manifest
from backend.decision_provider import OpenAIDecisions,ProviderFailure
from backend.decision_review import review_question
from backend.test_chart_decisions import png,answers
from scripts.decision_fixture import answer,review_answer


class ReviewTests(existing.DecisionTests.__bases__[0]):
    setUp=existing.DecisionTests.setUp
    freeze=existing.DecisionTests.freeze
    paper_records=existing.DecisionTests.paper_records

    def calls(self,choice='hold',verdict='accept',failure=None):
        calls=[]
        def analyze(snapshot):
            calls.append(('analyst',json.loads(json.dumps(snapshot))))
            snapshot['account']['cash']='999999' # Mutation must not reach review or SQLite.
            return answer(choice)
        def review(evidence,image_url,question):
            calls.append(('reviewer',evidence,image_url,question))
            if failure:raise failure
            return review_answer(verdict)
        self.provider.decide=analyze;self.provider.review=review
        return calls

    def saved_review(self,result):
        with closing(sqlite3.connect(self.state)) as c:
            r=json.loads(c.execute('SELECT payload_json FROM decision_reviews WHERE decision_id=?',(result['id'],)).fetchone()[0])
        self.assertEqual(r,result['review'])
        self.assertEqual(result,self.service.get_decision(result['id']))
        return r

    async def test_agreed_eligible_hold_same_snapshot_and_read_only(self):
        s=self.freeze();before=self.paper_records();calls=self.calls()
        result=await self.service.decide(s['snapshot_id']);r=self.saved_review(result)
        self.assertEqual([c[0] for c in calls],['analyst','reviewer'])
        self.assertEqual(calls[0][1],calls[1][1]['snapshot'])
        self.assertEqual(calls[1][1]['snapshot'],s)
        self.assertEqual(calls[1][1]['analyst']['proposal'],'hold')
        self.assertEqual(calls[1][1]['supporting_facts']['cash'],'948')
        self.assertEqual(calls[1][3]['name'],'review_verdict')
        self.assertTrue(r['final_check']['passed']);self.assertEqual(result['status'],'valid')
        self.assertFalse(result['paper_order_eligible']) # hold is a valid decision, never an order.
        self.assertEqual(before,self.paper_records())

    async def test_reviewer_rejection_preserves_actual_proposal(self):
        s=self.freeze();calls=self.calls(verdict='reject_unsupported_signal')
        result=await self.service.decide(s['snapshot_id']);r=self.saved_review(result)
        self.assertEqual(result['status'],'review_rejected');self.assertEqual(result['proposal'],'hold')
        self.assertEqual(r['reviewer']['verdict'],'reject_unsupported_signal')
        self.assertFalse(result['paper_order_eligible']);self.assertEqual(len(calls),2)

    async def test_unaffordable_buy_accepted_by_both_is_rejected(self):
        self.broker.order_size=100;s=self.freeze();before=self.paper_records();calls=self.calls(choice='buy')
        result=await self.service.decide(s['snapshot_id']);r=self.saved_review(result)
        self.assertEqual(r['analyst']['proposal'],'buy');self.assertEqual(r['reviewer']['verdict'],'accept')
        self.assertEqual(r['supporting_facts']['configured_buy_cost'],'1900')
        self.assertEqual(r['supporting_facts']['cash'],'948')
        self.assertTrue(r['supporting_facts']['strategy_passed'])
        self.assertFalse(r['supporting_facts']['account_passed'])
        self.assertEqual(result['status'],'invalid_proposal');self.assertFalse(r['final_check']['passed'])
        self.assertFalse(result['paper_order_eligible']);self.assertEqual(len(calls),2)
        self.assertEqual(before,self.paper_records())

    async def test_reviewer_accept_cannot_override_strategy(self):
        s=self.service.freeze(candle_timestamp='2026-11-10T15:03:00Z',short_window=2,long_window=3)['snapshot']
        self.calls(choice='buy');result=await self.service.decide(s['snapshot_id']);r=self.saved_review(result)
        self.assertTrue(r['supporting_facts']['account_passed']);self.assertFalse(r['supporting_facts']['strategy_passed'])
        self.assertEqual(result['status'],'unsupported_signal');self.assertFalse(result['paper_order_eligible'])

    async def test_timeout_invalid_reply_and_skipped_role_no_retries(self):
        s=self.freeze()
        for failure in [ProviderFailure('timeout','controlled_review_timeout'),ProviderFailure('provider_error','controlled_review_error')]:
            calls=self.calls(failure=failure);result=await self.service.decide(s['snapshot_id']);r=self.saved_review(result)
            self.assertEqual(result['status'],'review_'+failure.status);self.assertFalse(result['paper_order_eligible']);self.assertEqual(len(calls),2)
        calls=self.calls();self.provider.review=lambda *args:{'model':self.provider.model,'answers':[]}
        result=await self.service.decide(s['snapshot_id']);self.assertEqual(result['status'],'review_malformed_answer')
        self.assertFalse(result['paper_order_eligible'])
        calls=self.calls();self.provider.decide=lambda *args:{'model':self.provider.model,'answers':[]}
        result=await self.service.decide(s['snapshot_id']);r=self.saved_review(result)
        self.assertEqual(r['reviewer']['status'],'skipped');self.assertFalse(calls)

    async def test_chart_reviewer_receives_exact_same_image_and_named_answers(self):
        s=self.freeze();saved=self.service.get_snapshot(s['snapshot_id']);binding=manifest(saved)
        capture=dict(image_url=png(binding),manifest=binding);seen=[]
        self.provider.decide_image=lambda snapshot,url,qs:(seen.append((snapshot,url)) or answers())
        def review(evidence,url,question):
            seen.append((evidence['snapshot'],url));self.assertEqual(set(evidence['analyst']['answers']),{'action','crossover','evidence'})
            return review_answer()
        self.provider.review=review
        result=await decide_image(self.service,s['snapshot_id'],capture);self.saved_review(result)
        self.assertEqual(seen[0],seen[1]);self.assertEqual(seen[1][1],capture['image_url'])
        with patch.object(OpenAIDecisions,'post',return_value=review_answer()) as post:
            OpenAIDecisions().review({'snapshot':s},capture['image_url'],review_question())
        body=post.call_args.args[0];self.assertEqual(body['questions'][0]['name'],'review_verdict')
        self.assertEqual(body['input'][0]['content'][0]['image_url'],capture['image_url'])

    async def test_pending_review_is_ineligible_and_bounded_without_retry(self):
        import time
        s=self.freeze();entered=threading.Event();calls=self.calls()
        self.provider.timeout=0.01
        def slow_review(*args):
            calls.append(('reviewer',));entered.set();time.sleep(1.1);return review_answer()
        self.provider.review=slow_review
        task=asyncio.create_task(self.service.decide(s['snapshot_id']))
        self.assertTrue(await asyncio.to_thread(entered.wait,1))
        with closing(sqlite3.connect(self.state)) as c:
            identifier=c.execute('SELECT id FROM decisions ORDER BY created_at DESC LIMIT 1').fetchone()[0]
        pending=self.service.get_decision(identifier)
        self.assertEqual(pending['status'],'review_pending');self.assertFalse(pending['paper_order_eligible'])
        result=await task
        self.assertEqual(result['status'],'review_timeout');self.assertFalse(result['paper_order_eligible'])
        self.assertEqual([c[0] for c in calls],['analyst','reviewer'])
