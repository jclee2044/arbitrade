"""Immutable candle-close snapshots and proposal-only decisions. No execution calls."""

import asyncio
from contextlib import closing
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import uuid

from backend.candles import form_candles, utc_datetime
from backend.decision_provider import OpenAIDecisions, ProviderFailure, parse_answer
from backend.indicators import with_averages, validate_windows, configured_indicators
from backend.timeframes import TIMEFRAMES, MinuteVersion, derive_timeframe, sessions_for_chart
from backend.pnl import money
from fractions import Fraction


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def candle_end(symbol, interval, timestamp):
    if symbol != 'AAPL' or interval not in TIMEFRAMES:
        raise ValueError('Choose AAPL and a supported interval')
    stamp = utc_datetime(timestamp)
    sessions = sessions_for_chart('NASDAQ', interval, stamp.date(), stamp.date())
    for session in sessions:
        if session.opened <= stamp < session.closed:
            duration = TIMEFRAMES[interval]
            offset = (stamp-session.opened).total_seconds()
            if (duration is None and stamp != session.opened) or (duration is not None and offset % (duration*60)):
                break
            return min(session.closed, stamp+timedelta(minutes=duration)) if duration else session.closed
    raise ValueError('Candle timestamp must be an aligned regular-session interval start')


class DecisionService:
    def __init__(self, state_database, market_database, broker, *, provider=None):
        self.path, self.market = Path(state_database).resolve(), Path(market_database).resolve()
        self.broker = broker
        self.provider = provider or OpenAIDecisions()
        with closing(sqlite3.connect(self.path)) as c, c:
            c.executescript('''
                CREATE TABLE IF NOT EXISTS decision_snapshots (
                    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL, evidence_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS decisions (
                    id TEXT PRIMARY KEY, snapshot_id TEXT REFERENCES decision_snapshots(id),
                    requested_snapshot_id TEXT, created_at TEXT NOT NULL, provider TEXT NOT NULL,
                    model TEXT NOT NULL, model_call_kind TEXT NOT NULL, market_data_kind TEXT,
                    status TEXT NOT NULL, validation_status TEXT NOT NULL, proposal TEXT,
                    quantity INTEGER, explanation TEXT, error_code TEXT, answer_json TEXT,
                    paper_order_eligible INTEGER NOT NULL DEFAULT 0
                );
            ''')
            from backend.chart_decisions import setup
            setup(c)
            from backend.decision_review import setup as setup_review
            setup_review(c)

    def save_snapshot(self, payload, evidence):
        identifier = str(uuid.uuid4())
        payload = dict(payload, snapshot_id=identifier)
        text = encoded(payload)
        digest = sha256(text.encode()).hexdigest()
        with closing(sqlite3.connect(self.path)) as c, c:
            c.execute('INSERT INTO decision_snapshots VALUES (?,?,?,?,?)',
                      (identifier, datetime.now(UTC).isoformat(), text, digest, encoded(evidence)))
        return dict(snapshot=payload, sha256=digest)

    def get_snapshot(self, identifier, *, evidence=False):
        with closing(sqlite3.connect(self.path)) as c:
            row = c.execute('SELECT payload_json,payload_sha256,evidence_json FROM decision_snapshots WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise ValueError('Snapshot does not exist')
        if sha256(row[0].encode()).hexdigest() != row[1]:
            raise ValueError('Snapshot integrity check failed')
        payload=json.loads(row[0])
        if sha256(row[2].encode()).hexdigest() != payload['provenance']['evidence_sha256']:
            raise ValueError('Snapshot evidence integrity check failed')
        return dict(snapshot=payload, sha256=row[1], **({'records': json.loads(row[2])} if evidence else {}))

    def freeze(self, *, account_id='live', symbol='AAPL', interval='1m', candle_timestamp,
               short_window=20, long_window=50, chart_start=None, chart_end=None, instances=(), replay=None):
        validate_windows(short_window, long_window)
        symbol = symbol.strip().upper()
        stamp = utc_datetime(candle_timestamp)
        cutoff = candle_end(symbol, interval, stamp)
        available = replay.evaluation if replay is not None else self.broker.clock()
        missing = []
        if cutoff > utc_datetime(available):
            missing.append('candle_not_completed_at_available_time')
        if account_id != 'live' and replay is None:
            with closing(sqlite3.connect(self.path)) as c:
                row=c.execute('SELECT mode FROM paper_accounts WHERE id=?',(account_id,)).fetchone()
            if not row or row[0]!='test':raise ValueError('Replay account must have its active replay session')
        if replay is not None and replay.symbol != symbol:
            raise ValueError('Replay symbol does not match requested symbol')
        boundary = min(cutoff, utc_datetime(available))
        # A consistent read transaction freezes all visible market records first.
        if replay is not None:
            market = replay.connection
            records = self._market_records(market, symbol, boundary)
        elif self.market.exists():
            with closing(sqlite3.connect(self.market.as_uri()+'?mode=ro', uri=True)) as market:
                market.execute('BEGIN')
                records = self._market_records(market, symbol, boundary)
        else:
            records = dict(observations=[], receipts=[])
        # Derive exclusively from these frozen records, never a later live query.
        with closing(sqlite3.connect(':memory:')) as market:
            market.executescript('''CREATE TABLE observations (id INTEGER,provider TEXT,ticker TEXT,
                source_time_json TEXT,source_time_utc TEXT,payload_json TEXT,supersedes_observation_id INTEGER);
                CREATE TABLE receipts (id INTEGER,observation_id INTEGER,received_at_utc TEXT);''')
            for row in records['observations']:
                market.execute('INSERT INTO observations VALUES (?,?,?,?,?,?,?)',
                    (row['id'],row['provider'],row['ticker'],row['source_time_json'],row['source_time_utc'],
                     encoded(row['source_fields']),row['supersedes_observation_id']))
            for row in records['receipts']:
                market.execute('INSERT INTO receipts VALUES (?,?,?)', (row['id'],row['observation_id'],row['received_at_utc']))
            base = form_candles(market, symbol, as_of=boundary, available_at=boundary)
        history = derive_timeframe([MinuteVersion(row,boundary) for row in base['candles']], interval, as_of=boundary)
        history = with_averages(history, short_window, long_window)
        target = next((i for i,row in enumerate(history['candles']) if utc_datetime(row['timestamp']) == stamp), None)
        candle, values, coverage = None, None, None
        if target is None:
            missing.append('recorded_candle_missing')
        else:
            candle, coverage = history['candles'][target], history['coverage'][target]
            values = history['moving_averages']['rows'][target]
            if not coverage['ended']: missing.append('candle_not_completed')
            if values['short'] is None: missing.append('short_sma_unavailable')
            if values['long'] is None: missing.append('long_sma_unavailable')
            if not all(row['coverage_complete'] for row in history['coverage'][max(0,target-long_window+1):target+1]):
                missing.append('indicator_candle_coverage_incomplete')
        # Reconstruct cash/position at candle close from fills, not current balances.
        account, ledger = self._account_at(account_id, symbol, boundary)
        if account is None:
            missing.append('account_not_available_at_decision_time')
        constructed = any(row['source_fields'].get('test_data') for row in records['observations'])
        evidence = dict(records, account_fills=ledger)
        evidence_hash = sha256(encoded(evidence).encode()).hexdigest()
        end_index = target+1 if target is not None else 0
        start_index = max(0,end_index-200)
        if chart_end is not None and utc_datetime(chart_end)<stamp:
            raise ValueError('Selected candle is outside the visible range; recapture its chart')
        if chart_start is not None:
            first=utc_datetime(chart_start)
            if first>stamp:raise ValueError('Selected candle is outside the visible range; recapture its chart')
            start_index=next((i for i in range(start_index,end_index) if utc_datetime(history['candles'][i]['timestamp'])>=first),start_index)
        named=configured_indicators(history,instances)
        for item in named:item['rows']=item['rows'][start_index:end_index]
        payload = dict(schema_version=1, symbol=symbol, interval=interval, candle_timestamp=stamp.isoformat(),
            decision_time=cutoff.isoformat(), available_time=boundary.isoformat(), candle=candle,
            indicators=dict(short_window=short_window,long_window=long_window,
                            short=values['short'] if values else None,long=values['long'] if values else None,
                            crossover=values['signal'] if values else None,
                            series=history['moving_averages']['rows'][start_index:end_index]),
            account=account, chart=dict(candles=history['candles'][start_index:end_index],
                                       coverage=history['coverage'][start_index:end_index], indicators=named),
            provenance=dict(market_data_kind='constructed' if constructed else 'recorded',
                observation_count=len(records['observations']),receipt_count=len(records['receipts']),
                evidence_sha256=evidence_hash,account_fill_ids=[row['id'] for row in ledger]),
            completeness=dict(complete=not missing, missing=missing,
                              paper_order_eligible=not missing and not constructed))
        return self.save_snapshot(payload, evidence)

    @staticmethod
    def _market_records(connection, symbol, cutoff):
        cursor = connection.execute('''SELECT o.id,o.provider,o.ticker,o.source_time_json,o.source_time_utc,
                        o.payload_json,o.supersedes_observation_id,r.id,r.received_at_utc
                        FROM receipts r JOIN observations o ON o.id=r.observation_id
                        WHERE o.ticker=? AND o.provider='yahoo' ORDER BY r.id''', (symbol,))
        observations, receipts = {}, []
        for row in cursor:
            if utc_datetime(row[8]) > cutoff: continue
            if row[4] is not None and utc_datetime(row[4]) > cutoff: continue
            observations[row[0]] = dict(id=row[0],provider=row[1],ticker=row[2],source_time_json=row[3],
                source_time_utc=row[4],source_fields=json.loads(row[5]),supersedes_observation_id=row[6])
            receipts.append(dict(id=row[7],observation_id=row[0],received_at_utc=row[8]))
        return dict(observations=list(observations.values()), receipts=receipts)

    def _account_at(self, identifier, symbol, cutoff):
        with closing(sqlite3.connect(self.path)) as c:
            c.row_factory=sqlite3.Row; c.execute('BEGIN')
            account=c.execute('SELECT * FROM paper_accounts WHERE id=?',(identifier,)).fetchone()
            if account is None or utc_datetime(account['created_at']) > cutoff: return None, []
            if account['source_database'] != str(self.market): raise ValueError('Account observation source mismatch')
            rows=c.execute('''SELECT f.*,o.symbol,o.side FROM paper_fills f JOIN paper_orders o ON o.id=f.order_id
                              WHERE o.account_id=? ORDER BY f.id''',(identifier,)).fetchall()
        cash, shares, basis = Fraction(1000),0,Fraction(0)
        visible=[]
        for row in rows:
            if utc_datetime(row['executed_at']) > cutoff: continue
            visible.append(dict(row))
            amount=Fraction(row['price'])*row['quantity']
            cash = cash-amount if row['side']=='buy' else cash+amount
            if row['symbol'] != symbol: continue
            if row['side']=='buy': basis+=amount; shares+=row['quantity']
            else:
                basis-=basis/shares*row['quantity']; shares-=row['quantity']
        return dict(account_id=identifier,mode=account['mode'],created_at=account['created_at'],
                    cash=money(cash),starting_cash='1000',symbol=symbol,shares=shares,average_cost=money(basis/shares) if shares else None,
                    order_size=self.broker.order_size),visible

    def get_decision(self, identifier):
        with closing(sqlite3.connect(self.path)) as c:
            c.row_factory=sqlite3.Row
            row=c.execute('SELECT * FROM decisions WHERE id=?',(identifier,)).fetchone()
        if row is None: raise ValueError('Decision does not exist')
        result=dict(row)
        answer=result.pop('answer_json')
        result['answer']=json.loads(answer) if answer else None
        result['paper_order_eligible']=bool(result['paper_order_eligible'])
        with closing(sqlite3.connect(self.path)) as c:
            image=c.execute('SELECT metadata_json,questions_json,answers_json,comparison FROM decision_images WHERE decision_id=?',(identifier,)).fetchone()
        if image:
            result['image_analysis']=dict(capture=json.loads(image[0]) if image[0] else None,
                questions=json.loads(image[1]),answers=json.loads(image[2]) if image[2] else None,
                comparison=image[3],image_url=f'/api/decisions/{identifier}/image' if image[0] else None)
        with closing(sqlite3.connect(self.path)) as c:
            review=c.execute('SELECT payload_json FROM decision_reviews WHERE decision_id=?',(identifier,)).fetchone()
        if review:result['review']=json.loads(review[0])
        with closing(sqlite3.connect(self.path)) as c:
            c.row_factory=sqlite3.Row
            application=c.execute('SELECT id,run_id,status,reason,order_id,fill_id FROM automation_attempts WHERE decision_id=?',(identifier,)).fetchone()
        if application:result['application']=dict(application)
        return result

    async def decide(self, snapshot_id=None):
        identifier=str(uuid.uuid4())
        provider=self.provider
        with closing(sqlite3.connect(self.path)) as c,c:
            c.execute('''INSERT INTO decisions (id,requested_snapshot_id,created_at,provider,model,model_call_kind,status,validation_status)
                         VALUES (?,?,?,?,?,?,'pending','not_evaluated')''',
                      (identifier,snapshot_id,datetime.now(UTC).isoformat(),provider.name,provider.model,provider.mode))
        result=dict(status='missing_input',validation_status='incomplete',error_code='snapshot_missing',
                    proposal=None,quantity=None,explanation='No eligible frozen snapshot was supplied.',paper_order_eligible=0,answer_json=None)
        snapshot=None
        try:
            if not snapshot_id: raise ValueError('Snapshot missing')
            snapshot=self.get_snapshot(snapshot_id)['snapshot']
            with closing(sqlite3.connect(self.path)) as c,c:
                c.execute('UPDATE decisions SET snapshot_id=?,market_data_kind=? WHERE id=?',
                          (snapshot_id,snapshot['provenance']['market_data_kind'],identifier))
            if not snapshot['completeness']['complete']:
                result['error_code']='snapshot_incomplete'
                result['explanation']='Backend input unavailable: '+', '.join(snapshot['completeness']['missing'])
            else:
                response=await asyncio.wait_for(asyncio.to_thread(provider.decide,json.loads(encoded(snapshot))),timeout=provider.timeout+1)
                answer=parse_answer(response,provider.model)
                proposal=answer['choice']
                valid,reason,quantity=validate_proposal(snapshot,proposal)
                result.update(status='valid' if valid else 'invalid_proposal',validation_status='valid' if valid else 'rejected',
                    error_code=None if valid else 'account_rule_violation',proposal=proposal,quantity=quantity,
                    explanation=explanation(snapshot,proposal,reason),answer_json=encoded(answer),
                    paper_order_eligible=0)
        except ProviderFailure as error:
            result.update(status=error.status,validation_status='not_evaluated',error_code=error.code,
                          explanation='No validated proposal: '+error.code)
        except (TimeoutError, asyncio.TimeoutError):
            result.update(status='timeout',validation_status='not_evaluated',error_code='provider_timeout',explanation='Provider timed out; no action was proposed.')
        except ValueError:
            pass
        except Exception:
            # Never log/store arbitrary exceptions that may contain headers or keys.
            result.update(status='provider_error',validation_status='not_evaluated',error_code='provider_failed',explanation='Provider request failed; no validated proposal.')
        with closing(sqlite3.connect(self.path)) as c,c:
            c.execute('UPDATE decisions SET '+','.join(key+'=?' for key in result)+' WHERE id=?',(*result.values(),identifier))
        from backend.decision_review import review_decision
        return await review_decision(self,identifier)


def validate_proposal(snapshot, proposal):
    account=snapshot['account']; shares=account['shares']; size=account['order_size']
    quantity = size if proposal in {'buy','sell'} else shares if proposal=='close' else None
    if proposal=='buy' and Decimal(account['cash']) < Decimal(str(snapshot['candle']['close']))*size:
        return False,'Insufficient simulated cash at the frozen close.',quantity
    if proposal=='sell' and shares<size: return False,'Sell exceeds the frozen position.',quantity
    if proposal in {'hold','close'} and shares<=0: return False,'Action requires a frozen open position.',quantity
    if proposal=='wait' and shares: return False,'Wait requires a flat frozen account; hold preserves shares.',quantity
    return True,'Valid under frozen long-only account rules; no order executed.',quantity


def explanation(snapshot, proposal, reason):
    indicators=snapshot['indicators']; account=snapshot['account']
    return (f"Model proposal: {proposal}. Backend facts at {snapshot['decision_time']}: "
            f"{snapshot['symbol']} close {snapshot['candle']['close']}; "
            f"SMA {indicators['short_window']}={indicators['short']}, SMA {indicators['long_window']}={indicators['long']}; "
            f"crossover {indicators['crossover'] or 'none'}; simulated cash {account['cash']}, shares {account['shares']}, "
            f"configured order size {account['order_size']}. Rule check: {reason}")
