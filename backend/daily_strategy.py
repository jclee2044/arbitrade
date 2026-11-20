"""Reproducible daily crossover simulation and read-only, as-of assessment evidence."""
from dataclasses import dataclass
from datetime import timedelta
from fractions import Fraction
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, ConfigDict

from backend.candles import utc_datetime
from backend.daily_history import daily_history
from backend.decision_provider import ProviderFailure
from backend.pnl import apply_fill, money
from backend.timeframes import sessions_for_chart, TIMEFRAMES

Variant = Literal['baseline', 'sma200', 'ema200']
Mode = Literal['live', 'replay', 'backtest']
VARIANTS = {'baseline': '20/50 baseline', 'sma200': 'Close above SMA 200', 'ema200': 'Close above EMA 200'}
VERSION = 'daily-sma20-50-v1'
STARTING_CASH = 1000
RULES = ('All three long-only simulations start flat with $1,000 at the first 200-session mean. '
         'An upward daily SMA 20/50 crossover while flat signals a one-share buy. Each filtered variant '
         'requires the same close to be strictly above its own 200-day average. A downward crossover '
         'closes any position regardless of filter. A skipped crossover is never bought later. '
         'Market orders fill at the next regular session open if affordable. '
         'Zero fees and slippage. Price-only USD P&L excludes dividends. Open shares are marked at the last close.')


class StrategySelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    variant: Variant
    dataset_id: str | None = None


def decision(study, close, variant, shares):
    if study['sma200'] is None:
        return 'wait', 'warmup'
    if study['crossover'] == 'up' and not shares:
        if variant != 'baseline' and close <= study[variant]:
            return 'wait', 'entry_filter_failed'
        return 'buy', 'upward_crossover'
    if study['crossover'] == 'down' and shares:
        return 'close', 'downward_crossover'
    return ('hold' if shares else 'wait'), ('no_position' if study['crossover'] == 'down' else 'no_new_entry_or_exit')


@dataclass
class Simulation:
    facts: list
    orders: list
    summary: dict


def simulate(history, variant):
    shares = 0
    cash, basis, realized = Fraction(STARTING_CASH), Fraction(0), Fraction(0)
    peak, drawdown = cash, Fraction(0)
    facts, orders = [], []
    pending = None
    for bar, study in zip(history.bars, history.studies):
        if pending is not None:
            price = Fraction(str(bar['open']))
            side = pending['side']
            if side == 'buy' and price > cash:
                pending.update(status='rejected', reason='insufficient_cash', resolved_at=bar['timestamp'])
            else:
                cash += -price if side == 'buy' else price
                shares, basis, realized = apply_fill(shares, basis, realized, side, 1, price)
                pending.update(status='filled', fill_at=bar['timestamp'], fill_price=bar['open'])
            pending = None
        mark = shares * Fraction(str(bar['close']))
        equity = cash + mark
        peak = max(peak, equity)
        drawdown = max(drawdown, (peak - equity) / peak)
        verdict, reason = decision(study, bar['close'], variant, shares)
        facts.append(dict(rule_version=VERSION, dataset_id=history.digest, ticker=history.symbol,
            interval='1d', variant=variant, cutoff=bar['cutoff'], close=bar['close'], **study,
            verdict=verdict, reason=reason, shares=shares, cash=money(cash), equity=money(equity),
            realized=money(realized), unrealized=money(mark - basis)))
        if verdict in ('buy', 'close'):
            pending = dict(order_id=len(orders)+1, signal_at=bar['cutoff'], quantity=1,
                           side='buy' if verdict == 'buy' else 'sell', status='pending')
            orders.append(pending)
    last = facts[-1]
    summary = {k: last[k] for k in ('shares', 'cash', 'equity', 'realized', 'unrealized')}
    return Simulation(facts, orders, dict(summary, variant=variant, max_drawdown_pct=float(100*drawdown),
        return_pct=float((equity / STARTING_CASH-1)*100), fills=sum(o['status']=='filled' for o in orders),
        skipped=sum(f['reason']=='entry_filter_failed' for f in facts)))


@lru_cache(maxsize=3)
def simulation(variant):
    return simulate(daily_history(), variant)


def backtest(variant):
    history = daily_history()
    run = simulation(variant)
    return dict(ticker=history.symbol, source=history.source, dataset_id=history.digest, rule_version=VERSION,
        start=history.bars[199]['date'], end=history.bars[-1]['date'], assumptions=RULES,
        comparisons=[dict(simulation(key).summary, label=label) for key, label in VARIANTS.items()],
        bars=history.bars, facts=run.facts, orders=run.orders)


def capture_facts(capture, selection, mode):
    if capture is None:
        raise ProviderFailure('missing_capture', 'chart_capture_required')
    history = daily_history()
    if capture.ticker != history.symbol:
        raise ProviderFailure('unavailable', 'no_daily_history_for_ticker')
    if (selection.dataset_id is not None and selection.dataset_id != history.digest
            or mode == 'backtest' and selection.dataset_id != history.digest):
        raise ProviderFailure('invalid_capture', 'historical_dataset_mismatch')
    start = utc_datetime(capture.candle_timestamp)
    if mode == 'backtest':
        if capture.interval != '1d' or start not in history.ends:
            raise ProviderFailure('invalid_capture', 'expected_historical_session_close')
        cutoff = start
    else:
        # Chart timestamps label bar starts. Bound them by the visible period end
        # and by the replay receipt clock (never by today's wall clock in replay).
        as_of = utc_datetime(capture.captured_at)
        if mode == 'replay':
            if capture.last_quote_at is None:
                raise ProviderFailure('unavailable', 'replay_clock_required')
            as_of = min(as_of, utc_datetime(capture.last_quote_at))
        if start > as_of:
            raise ProviderFailure('invalid_capture', 'chart_follows_market_clock')
        sessions = sessions_for_chart('NASDAQ', capture.interval, start.date(), start.date())
        session = next((s for s in sessions if s.opened <= start < s.closed), None)
        if session is None:
            raise ProviderFailure('unavailable', 'chart_outside_regular_session')
        cutoff = min(as_of, session.closed)
        minutes = TIMEFRAMES[capture.interval]
        if minutes:
            cutoff = min(cutoff, start + timedelta(minutes=minutes))
    index = history.index_at(cutoff)
    if index is None:
        raise ProviderFailure('unavailable', 'completed_daily_history_unavailable')
    facts = simulation(selection.variant).facts[index]
    if facts['reason'] == 'warmup':
        raise ProviderFailure('unavailable', 'insufficient_daily_warmup')
    return facts
