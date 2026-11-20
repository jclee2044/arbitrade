"""Assignment chart reading. No candle/account lookup, reviewer or execution path."""
import asyncio
from contextlib import closing
from datetime import UTC, datetime
import json
import math
import sqlite3
import uuid

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import Literal

from backend.chart_decisions import decode_png
from backend.daily_strategy import RULES, VERSION, capture_facts
from backend.decision_provider import MODEL, OpenAIDecisions, ProviderFailure

CHOICES = ('long', 'short', 'wait')
QUESTION = 'chart_action'


class ChartCapture(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    ticker: str = Field(min_length=1, max_length=16, pattern=r'^[A-Z][A-Z0-9.\-^=]*$')
    interval: Literal['1m', '5m', '15m', '30m', '1h', '1d', '1w', '1mo']
    captured_at: AwareDatetime
    candle_timestamp: AwareDatetime
    image: str = Field(max_length=8_000_000)
    visible_candles: int = Field(ge=1, le=100_000)
    last_quote_at: AwareDatetime | None = None
    last_source_at: AwareDatetime | None = None
    is_stale: bool
    volume_status: Literal['visible', 'loading', 'unavailable']

    @field_validator('captured_at', 'candle_timestamp', 'last_quote_at', 'last_source_at', mode='before')
    @classmethod
    def timestamp(cls, value):
        # HTTP JSON timestamps, also used by model_validate for the legacy envelope.
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace('Z', '+00:00'))
        return value

    @model_validator(mode='after')
    def chronological(self):
        if self.candle_timestamp > self.captured_at:
            raise ValueError('Candle timestamp must not follow capture time')
        return self


def payload(capture):
    context = capture.model_dump(mode='json', exclude={'image'}, exclude_none=True)
    return dict(model=MODEL, input=[dict(role='user', content=[
        dict(type='input_text', text='Evaluate this captured chart using the supplied context. '
             'The chart contains observed partial quote candles; provider volume can lag or be unavailable. '
             'The last_source_at time is inferred from the provider time field and is not independently verified.'),
        dict(type='input_json', data=context),
        dict(type='input_image', image_url=capture.image),
    ])], questions=[dict(type='choice', name=QUESTION,
        instructions='For a hypothetical chart-reading exercise, which action is best supported by the visible evidence? '
        'Choose wait when evidence is insufficient, unclear, or stale. The image is a limited snapshot, not complete market context.',
        choices=[dict(value='long', description='A hypothetical long position is best supported by the visible chart.'),
                 dict(value='short', description='A hypothetical short position is best supported by the visible chart.'),
                 dict(value='wait', description='Wait because the chart does not support either directional choice clearly.')])])


STRATEGY_QUESTION = 'daily_strategy_action'
STRATEGY_CHOICES = {'buy': 'Signal a one-share entry.', 'close': 'Signal exit of the open share.',
                    'hold': 'Keep the simulated share.', 'wait': 'Stay flat.'}


def strategy_payload(capture, facts):
    body = payload(capture)
    parts = body['input'][0]['content']
    parts[0]['text'] = ('Assess the selected daily simulation at the evidence cutoff, using the '
                        'bound chart and frozen strategy facts. The chart may use a different interval. '
                        'State your own assessment of the rule action. Future fills are unknown.')
    parts.insert(2, dict(type='input_json', data=facts))
    body['questions'] = [dict(type='choice', name=STRATEGY_QUESTION, instructions=RULES,
        choices=[dict(value=value, description=description) for value, description in STRATEGY_CHOICES.items()])]
    return body


def assessment_scope(mode, selection=None):
    return f'{mode}/{VERSION}/{selection.variant}' if selection else mode


def validate_historical_image(facts, binding):
    expected = {key: facts[key] for key in ('ticker', 'variant', 'dataset_id', 'cutoff', 'rule_version')}
    if binding != dict(expected, kind='daily_strategy'):
        raise ProviderFailure('invalid_image', 'historical_chart_binding_mismatch')


def normalize(response, question=QUESTION, choices=CHOICES):
    if not isinstance(response, dict) or response.get('model') != MODEL:
        raise ProviderFailure('malformed_answer', 'provider_model_mismatch')
    answers = response.get('answers')
    if not isinstance(answers, list) or len(answers) != 1 or not isinstance(answers[0], dict):
        raise ProviderFailure('malformed_answer', 'expected_one_named_answer')
    answer = answers[0]
    if answer.get('name') != question:
        raise ProviderFailure('malformed_answer', 'wrong_question_name')
    if answer.get('type') == 'refusal':
        raise ProviderFailure('refused', 'provider_refusal')
    if answer.get('type') != 'choice' or answer.get('choice') not in choices:
        raise ProviderFailure('malformed_answer', 'invalid_chart_choice')
    result = dict(name=question, type='choice', choice=answer['choice'])
    def probability(v):
        return type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1
    if 'confidence' in answer:
        if not probability(answer['confidence']):
            raise ProviderFailure('malformed_answer', 'invalid_probability_metadata')
        result['confidence'] = answer['confidence']
    if 'probabilities' in answer:
        values = answer['probabilities']; seen = set(); cleaned = []
        if not isinstance(values, list):
            raise ProviderFailure('malformed_answer', 'invalid_probability_metadata')
        for item in values:
            if (not isinstance(item, dict) or not isinstance(item.get('value'), str)
                    or item['value'] not in choices or item['value'] in seen or not probability(item.get('probability'))):
                raise ProviderFailure('malformed_answer', 'invalid_probability_metadata')
            seen.add(item['value']); cleaned.append(dict(value=item['value'], probability=item['probability']))
        result['probabilities'] = cleaned
    return result


class ClassroomDecisions:
    def __init__(self, path, provider=None):
        self.path = path
        self.provider = provider or OpenAIDecisions()
        with closing(sqlite3.connect(path)) as c, c:
            c.execute('''CREATE TABLE IF NOT EXISTS classroom_decisions (
                id TEXT PRIMARY KEY, result_json TEXT NOT NULL, png BLOB NOT NULL)''')
            c.execute('''CREATE TABLE IF NOT EXISTS desk_assessments (
                decision_id TEXT PRIMARY KEY REFERENCES classroom_decisions(id),
                conversation_id TEXT NOT NULL, ticker TEXT NOT NULL, data_mode TEXT NOT NULL)''')
            c.execute('''CREATE INDEX IF NOT EXISTS desk_assessment_scope
                ON desk_assessments(conversation_id, ticker, data_mode)''')
            c.execute('''CREATE TABLE IF NOT EXISTS desk_chat_turns (
                scope TEXT NOT NULL, chart_time TEXT NOT NULL, question TEXT NOT NULL, answer TEXT NOT NULL)''')
            c.execute('CREATE INDEX IF NOT EXISTS desk_chat_scope ON desk_chat_turns(scope, chart_time)')

    def recent_chat_messages(self, scope, chart_time):
        with closing(sqlite3.connect(self.path)) as c:
            turns = c.execute('''SELECT chart_time, question, answer FROM desk_chat_turns
                WHERE scope = ? AND chart_time <= ? ORDER BY rowid DESC LIMIT 12''',
                (scope, chart_time)).fetchall()
        messages = []
        for stamp, question, answer in reversed(turns):
            messages.append(dict(role='user', content=f'[Chart {stamp}] {question}' if stamp else question))
            messages.append(dict(role='assistant', content=answer))
        return messages

    def save_chat_turn(self, scope, chart_time, question, answer):
        with closing(sqlite3.connect(self.path)) as c, c:
            c.execute('INSERT INTO desk_chat_turns(scope, chart_time, question, answer) VALUES (?,?,?,?)',
                      (scope, chart_time, question, answer))

    def previous_assessment(self, conversation_id, ticker, data_mode, *, facts=None, chart_time=None):
        with closing(sqlite3.connect(self.path)) as c:
            row = c.execute('''SELECT d.result_json FROM desk_assessments AS h
                JOIN classroom_decisions AS d ON d.id = h.decision_id
                WHERE h.conversation_id = ? AND h.ticker = ? AND h.data_mode = ?
                  AND (? IS NULL OR (json_extract(d.result_json, '$.strategy_facts.cutoff') <= ?
                       AND json_extract(d.result_json, '$.strategy_facts.dataset_id') = ?))
                  AND (? IS NULL OR julianday(json_extract(d.result_json, '$.context.candle_timestamp')) <= julianday(?))
                ORDER BY h.rowid DESC LIMIT 1''', (conversation_id, ticker, data_mode,
                    facts and facts['cutoff'], facts and facts['cutoff'], facts and facts['dataset_id'], chart_time, chart_time)).fetchone()
        return json.loads(row[0]) if row else None

    def get(self, identifier):
        with closing(sqlite3.connect(self.path)) as c:
            row = c.execute('SELECT result_json FROM classroom_decisions WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise ValueError('Decision does not exist')
        return json.loads(row[0])

    def image(self, identifier):
        with closing(sqlite3.connect(self.path)) as c:
            row = c.execute('SELECT png FROM classroom_decisions WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise ValueError('Decision does not exist')
        return row[0]

    async def decide(self, capture, *, conversation_id=None, data_mode=None, strategy=None):
        # Validate pixels before any outbound request; never accept embedded snapshot data.
        raw, binding, metadata = await asyncio.to_thread(decode_png, capture.image)
        if binding is not None and not (strategy and data_mode == 'backtest'):
            raise ProviderFailure('invalid_image', 'use_visible_chart_capture')
        facts = await asyncio.to_thread(capture_facts, capture, strategy, data_mode) if strategy else None
        if strategy and data_mode == 'backtest':
            validate_historical_image(facts, binding)
        body = strategy_payload(capture, facts) if strategy else payload(capture)
        identifier = str(uuid.uuid4())
        result = dict(id=identifier, kind='classroom_chart', created_at=datetime.now(UTC).isoformat(),
            provider=self.provider.name, model=self.provider.model, model_call_kind=self.provider.mode,
            context=body['input'][0]['content'][1]['data'], questions=body['questions'],
            status='pending', choice=None, answer=None, error_code=None,
            paper_order_eligible=False, image_url=f'/api/decisions/{identifier}/image', image=metadata)
        if strategy:
            result.update(kind='daily_strategy', strategy_facts=facts, agrees_with_strategy=None)
        try:
            response = await asyncio.wait_for(asyncio.to_thread(self.provider.post, body), self.provider.timeout + 1)
            result['answer'] = normalize(response, STRATEGY_QUESTION, STRATEGY_CHOICES) if strategy else normalize(response)
            result.update(status='valid', choice=result['answer']['choice'])
            if strategy:
                result['agrees_with_strategy'] = result['choice'] == facts['verdict']
        except ProviderFailure as error:
            result.update(status=error.status, error_code=error.code)
        except TimeoutError:
            result.update(status='timeout', error_code='provider_timeout')
        except Exception:
            result.update(status='provider_error', error_code='provider_failed')
        with closing(sqlite3.connect(self.path)) as c, c:
            c.execute('INSERT INTO classroom_decisions VALUES (?,?,?)', (identifier, json.dumps(result), raw))
            if conversation_id and data_mode and result['status'] == 'valid':
                c.execute('INSERT INTO desk_assessments VALUES (?,?,?,?)',
                          (identifier, conversation_id, capture.ticker, assessment_scope(data_mode, strategy)))
        return result
