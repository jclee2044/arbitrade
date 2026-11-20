"""Exercise the real Agents SDK runner against a controlled model and Decisions provider."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from backend.classroom_decisions import ChartCapture, ClassroomDecisions
from backend.decision_provider import ProviderFailure, STRATEGY_RULES
from backend.desk_agent import DeskAgentRequest, build_desk_agent, run_desk_agent
from backend.test_classroom_decisions import Provider, capture
from scripts.swing_knowledge import search

try:
    from agents import Model, ModelResponse, Usage
    from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText
except ModuleNotFoundError as error:
    if error.name not in {'agents', 'openai'}:
        raise
    raise unittest.SkipTest('Requires backend/requirements-openai.txt') from error


class ControlledModel(Model):
    def __init__(self, calls):
        self.calls = calls
        self.inputs = []

    async def get_response(self, system_instructions, input, model_settings, tools, output_schema,
                           handoffs, tracing, **kwargs):
        self.inputs.append(input)
        if len(self.inputs) == 1:
            output = [
                ResponseFunctionToolCall(name=name, type='function_call',
                                         call_id=f'call_{index}', arguments=json.dumps(args))
                for index, (name, args) in enumerate(self.calls)
            ]
        else:
            output = [ResponseOutputMessage(
                id='msg_controlled', type='message', role='assistant', status='completed',
                content=[ResponseOutputText(type='output_text', text='Controlled answer', annotations=[])],
            )]
        return ModelResponse(output=output, usage=Usage(), response_id=None)

    def stream_response(self, *args, **kwargs):
        raise AssertionError('The desk agent should use the nonstreaming runner')


class DeskAgentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.provider = Provider()
        self.decisions = ClassroomDecisions(Path(directory.name) / 'state.sqlite3', self.provider)

    async def run_controlled(self, calls, chart=None):
        model = ControlledModel(calls)
        request = DeskAgentRequest(question='Explain the rules and assess the chart.', capture=chart)
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'offline-placeholder'}), patch(
            'backend.desk_agent.build_desk_agent', return_value=build_desk_agent(model)
        ):
            result = await run_desk_agent(request, self.decisions)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['answer'], 'Controlled answer')
        self.assertNotIn('data:image', json.dumps(model.inputs))
        return result['tool_results']

    def test_tool_contract(self):
        rules, chart = build_desk_agent().tools
        self.assertEqual(rules.name, 'lookup_trading_rules')
        self.assertIn('Read and explain', rules.description)
        self.assertEqual(rules.params_json_schema['required'], ['topic'])
        self.assertEqual(rules.params_json_schema['properties']['topic']['type'], 'string')
        self.assertEqual(set(rules.params_json_schema['properties']), {'topic'})
        self.assertEqual(chart.name, 'assess_visible_chart')
        self.assertIn('Request a new Decision API assessment', chart.description)
        self.assertIn('browser snapshot', chart.description)
        self.assertEqual(chart.params_json_schema['properties'], {})
        self.assertEqual(chart.params_json_schema['required'], [])
        for tool in (rules, chart):
            self.assertFalse(tool.params_json_schema['additionalProperties'])

    async def test_runner_returns_original_results_and_reuses_each_request_capture(self):
        chart = capture()
        calls = [('lookup_trading_rules', {'topic': 'overnight gap'}),
                 ('assess_visible_chart', {}), ('assess_visible_chart', {})]
        results = await self.run_controlled(calls, chart)
        by_tool = {entry['name']: entry['result'] for entry in results}
        self.assertEqual(by_tool['lookup_trading_rules']['paper_strategy_rules'], STRATEGY_RULES)
        self.assertEqual(by_tool['lookup_trading_rules']['lessons'], search('overnight gap'))
        decision = by_tool['assess_visible_chart']
        self.assertEqual(decision, self.decisions.get(decision['id']))
        self.assertFalse(decision['paper_order_eligible'])
        self.assertEqual(len(self.provider.received), 1)
        self.assertEqual(self.provider.received[0]['input'][0]['content'][-1]['image_url'], chart['image'])
        self.assertEqual(sum(entry['result'] == decision for entry in results), 2)

    async def test_runner_preserves_tool_failures(self):
        call = [('assess_visible_chart', {})]
        missing = (await self.run_controlled(call))[0]['result']
        self.assertEqual(missing, {'status': 'missing_capture', 'error_code': 'chart_capture_required'})
        invalid = (await self.run_controlled(call, dict(capture(), image='bad image')))[0]['result']
        self.assertEqual(invalid['status'], 'invalid_image')
        self.assertTrue(invalid['error_code'])
        self.assertEqual(self.provider.received, [])
        self.provider.failure = ProviderFailure('timeout', 'controlled_timeout')
        failure = (await self.run_controlled(call, capture()))[0]['result']
        self.assertEqual((failure['status'], failure['error_code'], failure['choice']),
                         ('timeout', 'controlled_timeout', None))
        self.assertEqual(failure, self.decisions.get(failure['id']))
        bad_args = (await self.run_controlled([('lookup_trading_rules', {})]))[0]['result']
        self.assertEqual(bad_args, {'status': 'tool_error', 'error_code': 'invalid_tool_arguments'})

    async def test_previous_assessment_is_scoped_and_survives_a_failed_decision(self):
        identifier = str(uuid4())
        chart = ChartCapture.model_validate(capture())
        live = await self.decisions.decide(chart, conversation_id=identifier, data_mode='live')
        replay = await self.decisions.decide(chart, conversation_id=identifier, data_mode='replay')
        await self.decisions.decide(chart.model_copy(update={'ticker': 'MSFT'}),
                                    conversation_id=identifier, data_mode='replay')
        self.provider.failure = ProviderFailure('timeout', 'controlled_timeout')
        await self.decisions.decide(chart, conversation_id=identifier, data_mode='replay')
        self.assertEqual(self.decisions.previous_assessment(identifier, 'AAPL', 'replay'), replay)
        self.assertEqual(self.decisions.previous_assessment(identifier, 'AAPL', 'live'), live)
        self.assertIsNone(self.decisions.previous_assessment(str(uuid4()), 'AAPL', 'replay'))

    async def test_strategy_comparisons_use_same_variant_and_an_earlier_chart(self):
        from backend.classroom_decisions import STRATEGY_QUESTION
        from backend.daily_strategy import StrategySelection

        self.provider.response = dict(model=self.provider.model, answers=[
            dict(name=STRATEGY_QUESTION, type='choice', choice='hold')])
        chat = uuid4()
        async def turn(variant, stamp, calls):
            model = ControlledModel(calls)
            request = DeskAgentRequest(question='Assess and compare this strategy session.',
                capture=dict(capture(), candle_timestamp=stamp, last_quote_at=stamp),
                conversation_id=chat, data_mode='replay', strategy=StrategySelection(variant=variant))
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'offline-placeholder'}), patch(
                    'backend.desk_agent.build_desk_agent', return_value=build_desk_agent(model, strategy=True)):
                result = await run_desk_agent(request, self.decisions)
            self.assertEqual(result['status'], 'ok')
            return result, model.inputs[0]

        at = '2025-06-09T14:00:00Z'
        later = '2025-06-10T14:00:00Z'
        first, messages = await turn('sma200', at, [('assess_visible_chart', {})])
        self.assertEqual([m['role'] for m in messages], ['user'])
        decision = first['tool_results'][0]['result']
        self.assertEqual(first['previous_assessment'], None)
        self.assertEqual(self.provider.received[0]['input'][0]['content'][2]['data'], decision['strategy_facts'])
        self.assertEqual(decision['strategy_facts']['cutoff'], '2025-06-06T20:00:00Z')
        self.assertEqual(decision['status'], 'valid')
        second, messages = await turn('sma200', later, [('assess_visible_chart', {})])
        self.assertEqual([m['role'] for m in messages], ['user', 'assistant', 'user'])
        self.assertIn('2025-06-09T14:00', messages[0]['content'])
        self.assertEqual(messages[1]['content'], first['answer'])
        self.assertEqual(second['previous_assessment'], decision)
        self.assertEqual(second['tool_results'][0]['result']['strategy_facts']['cutoff'], '2025-06-09T20:00:00Z')
        earlier, messages = await turn('sma200', at, [('read_strategy_facts', {})])
        self.assertEqual(len(messages), 3)
        self.assertNotIn('2025-06-10', json.dumps(messages))
        self.assertEqual(earlier['previous_assessment'], decision)
        self.assertEqual(earlier['tool_results'][0]['result']['strategy_facts'], decision['strategy_facts'])
        unrelated, messages = await turn('ema200', later, [('read_strategy_facts', {})])
        self.assertEqual(len(messages), 1)
        self.assertIsNone(unrelated['previous_assessment'])
        self.assertEqual(len(self.provider.received), 2)
