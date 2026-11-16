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


def normalize(response):
    if not isinstance(response, dict) or response.get('model') != MODEL:
        raise ProviderFailure('malformed_answer', 'provider_model_mismatch')
    answers = response.get('answers')
    if not isinstance(answers, list) or len(answers) != 1 or not isinstance(answers[0], dict):
        raise ProviderFailure('malformed_answer', 'expected_one_named_answer')
    answer = answers[0]
    if answer.get('name') != QUESTION:
        raise ProviderFailure('malformed_answer', 'wrong_question_name')
    if answer.get('type') == 'refusal':
        raise ProviderFailure('refused', 'provider_refusal')
    if answer.get('type') != 'choice' or answer.get('choice') not in CHOICES:
        raise ProviderFailure('malformed_answer', 'invalid_chart_choice')
    result = dict(name=QUESTION, type='choice', choice=answer['choice'])
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
                    or item['value'] not in CHOICES or item['value'] in seen or not probability(item.get('probability'))):
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

    async def decide(self, capture):
        # Validate pixels before any outbound request; never accept embedded snapshot data.
        raw, binding, metadata = await asyncio.to_thread(decode_png, capture.image)
        if binding is not None:
            raise ProviderFailure('invalid_image', 'use_visible_chart_capture')
        body = payload(capture)
        identifier = str(uuid.uuid4())
        result = dict(id=identifier, kind='classroom_chart', created_at=datetime.now(UTC).isoformat(),
            provider=self.provider.name, model=self.provider.model, model_call_kind=self.provider.mode,
            context=body['input'][0]['content'][1]['data'], questions=body['questions'],
            status='pending', choice=None, answer=None, error_code=None,
            paper_order_eligible=False, image_url=f'/api/decisions/{identifier}/image', image=metadata)
        try:
            response = await asyncio.wait_for(asyncio.to_thread(self.provider.post, body), self.provider.timeout + 1)
            result['answer'] = normalize(response)
            result.update(status='valid', choice=result['answer']['choice'])
        except ProviderFailure as error:
            result.update(status=error.status, error_code=error.code)
        except TimeoutError:
            result.update(status='timeout', error_code='provider_timeout')
        except Exception:
            result.update(status='provider_error', error_code='provider_failed')
        with closing(sqlite3.connect(self.path)) as c, c:
            c.execute('INSERT INTO classroom_decisions VALUES (?,?,?)', (identifier, json.dumps(result), raw))
        return result
