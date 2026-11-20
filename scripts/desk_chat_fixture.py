"""Disposable chart and controlled providers for the chat SmokeTest."""
from contextlib import asynccontextmanager
from datetime import datetime
import os
import json
import sqlite3
from hashlib import sha256
from base64 import b64decode
from zoneinfo import ZoneInfo

from backend import desk_agent
from backend.classroom_decisions import ClassroomDecisions, QUESTION
from backend.decision_provider import MODEL, ProviderFailure
from scripts.decision_fixture import app, lifespan as chart_lifespan


def eastern_cutoff(facts):
    cutoff = datetime.fromisoformat(facts['cutoff']).astimezone(ZoneInfo('America/New_York'))
    return f'{cutoff:%Y-%m-%d %H:%M} ET'


class DecisionProvider:
    name, model, mode, timeout = 'controlled-chat', MODEL, 'controlled', 2
    calls = 0

    def post(self, body):
        self.calls += 1
        if body['questions'][0]['name'] == 'daily_strategy_action':
            parts = body['input'][0]['content']
            facts = parts[2]['data']
            assert parts[1]['data']['ticker'] == facts['ticker']
            assert 'orders' not in facts and 'fill_price' not in facts
            png_hash = sha256(b64decode(parts[-1]['image_url'].split(',')[1])).hexdigest()
            with sqlite3.connect(os.environ['ARBITRADE_CONFIG_DATABASE']) as db:
                db.execute('CREATE TABLE IF NOT EXISTS strategy_payloads (facts TEXT, png_hash TEXT)')
                db.execute('INSERT INTO strategy_payloads VALUES (?,?)', (json.dumps(facts), png_hash))
            if self.calls == 3:
                raise ProviderFailure('timeout', 'controlled_strategy_timeout')
            # A deliberate disagreement verifies that AI cannot replace the deterministic verdict.
            return dict(model=MODEL, answers=[dict(name='daily_strategy_action', type='choice', choice='buy',
                probabilities=[dict(value='buy', probability=.65)])])
        if self.calls == 2 and os.environ.get('ARBITRADE_CHAT_CONVERSATION') == '1':
            return dict(model=MODEL, answers=[dict(name=QUESTION, type='choice', choice='short',
                probabilities=[dict(value='short', probability=.64)])])
        if self.calls == 2:
            raise ProviderFailure('timeout', 'controlled_chart_timeout')
        return dict(model=MODEL, answers=[dict(name=QUESTION, type='choice', choice='long',
            probabilities=[dict(value='long', probability=.72)])])


def build_controlled_agent(*, strategy=False):
    from backend.test_desk_agent import ControlledModel
    from agents import ModelResponse, Usage
    from openai.types.responses import ResponseOutputMessage, ResponseOutputText

    class ChatModel(ControlledModel):
        async def get_response(self, system_instructions, input, *args, **kwargs):
            if not self.inputs:
                self.question = input if isinstance(input, str) else input[-1]['content']
                assert 'An attached chart alone does not request an assessment.' in system_instructions
                assert 'America/New_York, YYYY-MM-DD HH:MM ET' in system_instructions
                if strategy:
                    session = json.loads(system_instructions.split('\nSelected session: ')[1].split('\n')[0])
                    assert session['strategy_facts']['ticker'] == 'AAPL'
                    if self.question == 'this particular signal':
                        assert input[-3]['role'] == 'user' and 'why was it worthwhile as a buy signal?' in input[-3]['content']
                        assert input[-2]['role'] == 'assistant' and eastern_cutoff(session['strategy_facts']) in input[-2]['content']
                    if self.question == 'Which session is selected?':
                        assert len(input) == 1
                    name = ('assess_visible_chart' if self.question.startswith('Assess') else
                            'lookup_trading_rules' if self.question.startswith('Explain') else 'read_strategy_facts')
                    self.calls = [(name, {'topic': 'wait'} if name == 'lookup_trading_rules' else {})]
                    return await super().get_response(system_instructions, input, *args, **kwargs)
                if self.question != 'Should I wait?':
                    self.calls = ([('lookup_trading_rules', {'topic': 'wait'})]
                                  if self.question.startswith(('Explain', 'What does WAIT')) else [('assess_visible_chart', {})])
                    return await super().get_response(system_instructions, input, *args, **kwargs)
            if strategy:
                tool = next(item for item in input if isinstance(item, dict) and item.get('type') == 'function_call_output')
                import ast
                # The SDK accepts dict tool outputs and serializes them for the model.
                raw = tool['output']
                try:
                    result = json.loads(raw)
                except ValueError:
                    result = ast.literal_eval(raw)
                facts = result.get('strategy_facts')
                if result.get('error_code'):
                    text = 'Assessment failed: ' + result['error_code']
                elif facts:
                    cutoff = eastern_cutoff(facts)
                    text = (f"{facts['ticker']} {facts['variant']} at {cutoff}: {facts['verdict']}, "
                            f"{facts['reason']}. Close {facts['close']:.2f}, SMA 200 {facts['sma200']:.2f}.")
                    if result.get('choice'):
                        text += f" Model: {result['choice']} at {result['answer']['probabilities'][0]['probability']:.0%}."
                    elif facts['variant'] == 'baseline' and facts['verdict'] == 'buy':
                        text = (f"{facts['ticker']} at {cutoff}: the account was flat and the 20-day "
                                f"average ({facts['sma20']:.2f}) crossed above the 50-day average "
                                f"({facts['sma50']:.2f}). That triggered the baseline buy. The later return "
                                "was unknown at the signal close.")
                else:
                    text = result['daily_strategy_rules']
            elif self.question == 'Should I wait?':
                text = 'Would you like the wait rule explained or a new chart assessment?'
            elif self.question.startswith(('Explain', 'What does WAIT')):
                text = 'Wait remains flat.'
            elif 'controlled_chart_timeout' in str(input):
                text = 'The chart assessment timed out.'
            elif 'compare' in self.question:
                marker = '\nEarlier assessment evidence: '
                if marker in system_instructions:
                    prior = system_instructions.split(marker, 1)[1]
                    assert '"choice":"long"' in prior and '15:00' in prior and '0.72' in prior
                    assert 'short' in str(input) and '0.64' in str(input)
                    text = 'AAPL at 2026-11-10 10:00 ET was long at 72%. At 2026-11-10 10:01 ET it is short at 64%.'
                else:
                    text = 'The new assessment was long at 72%. There is no earlier assessment in this chat.'
            else:
                assert '0.72' in str(input)
                text = 'The assessment returned long with 72% probability.'
            return ModelResponse(output=[ResponseOutputMessage(
                id='msg_chat', type='message', role='assistant', status='completed',
                content=[ResponseOutputText(type='output_text', text=text, annotations=[])],
            )], usage=Usage(), response_id=None)

    return build_agent(ChatModel([]), strategy=strategy)


build_agent = desk_agent.build_desk_agent


@asynccontextmanager
async def lifespan(application):
    async with chart_lifespan(application):
        if os.environ.get('ARBITRADE_CHAT_SMOKE_PROVIDER') == 'live':
            from dotenv import load_dotenv
            from scripts.smoke_test import ROOT
            load_dotenv(ROOT / '.env', override=False, interpolate=False)
            load_dotenv(ROOT / 'backend/.env', override=False, interpolate=False)
            yield
        else:
            os.environ['OPENAI_API_KEY'] = 'offline-placeholder'
            desk_agent.build_desk_agent = build_controlled_agent
            application.state.classroom_decisions = ClassroomDecisions(
                application.state.paper.path, DecisionProvider())
            try:
                yield
            finally:
                desk_agent.build_desk_agent = build_agent


app.router.lifespan_context = lifespan
