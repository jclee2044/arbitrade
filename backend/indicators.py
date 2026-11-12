"""Extensible completed-candle indicators and exact SMA crossover comparisons."""

from collections import deque
from dataclasses import dataclass
from fractions import Fraction
from typing import Callable

DEFAULT_SHORT = 20
DEFAULT_LONG = 50
WINDOW = {'window': dict(label='Window', type='integer', minimum=1, default=20)}


def sma_values(completed, settings):
    """One exact mean or None per completed candle; input ordered oldest first."""
    size = settings['window']
    queue, total, values = deque(), Fraction(0), []
    for candle in completed:
        price = Fraction(str(candle['close']))
        queue.append(price)
        total += price
        if len(queue) > size:
            total -= queue.popleft()
        values.append(total / size if len(queue) == size else None)
    return values


def ema_values(completed, settings):
    size = settings['window']
    values = [None] * len(completed)
    if len(completed) < size:
        return values
    previous = sum(candle['close'] for candle in completed[:size]) / size
    values[size - 1] = previous
    alpha = 2 / (size + 1)
    for index in range(size, len(completed)):
        previous += alpha * (completed[index]['close'] - previous)
        values[index] = previous
    return values


def range_values(completed, settings):
    """Highest high minus lowest low in the last N completed candles."""
    size = settings['window']
    queue, values = deque(), []
    for candle in completed:
        queue.append((Fraction(str(candle['high'])), Fraction(str(candle['low']))))
        if len(queue) > size:
            queue.popleft()
        values.append(max(high for high, _ in queue) - min(low for _, low in queue)
                      if len(queue) == size else None)
    return values


@dataclass(frozen=True)
class IndicatorType:
    label: str
    description: str
    units: str
    pane: str
    settings: dict
    calculate: Callable


# Extend this registry with a pure calculator + metadata; no Vue formula changes.
INDICATOR_TYPES = {
    'sma': IndicatorType('Simple moving average', 'Mean of the last N completed candle closes.',
                         'price', 'price', WINDOW, sma_values),
    'price_range': IndicatorType('Rolling price range', 'Highest high minus lowest low of the last N completed candles.',
                                 'price difference', 'separate', WINDOW, range_values),
    'ema': IndicatorType('Exponential moving average', 'Smoothed completed closes, seeded with the first full window mean.',
                         'price', 'price', WINDOW, ema_values),
}


def indicator_types():
    return [dict(type=key, label=kind.label, description=kind.description,
                 units=kind.units, pane=kind.pane, settings=kind.settings)
            for key, kind in INDICATOR_TYPES.items()]


def validate_settings(kind, settings):
    definition = INDICATOR_TYPES.get(kind)
    if definition is None:
        raise ValueError('Unknown indicator type')
    if not isinstance(settings, dict) or settings.keys() != definition.settings.keys():
        raise ValueError('Supply exactly these indicator settings: ' + ', '.join(definition.settings))
    result = {}
    for key, spec in definition.settings.items():
        value = settings[key]
        if spec['type'] != 'integer' or type(value) is not int or value < spec['minimum']:
            raise ValueError(f"{spec['label']} must be a positive whole number")
        result[key] = value
    return result


def indicator_rows(kind, candles, coverage, settings, *, exact=False):
    """Validate settings; calculate on ended candles; align gaps to every time.

    Calculators receive ordered completed candles and their own settings copy.
    They return one number/None per input. Fractions stay exact for comparisons.
    """
    settings = validate_settings(kind, settings)
    ended = {row['timestamp']: row['ended'] for row in coverage}
    ordered = sorted(candles, key=lambda item: item['timestamp'])
    completed = [c for c in ordered if ended.get(c['timestamp'], False)]
    calculated = INDICATOR_TYPES[kind].calculate(completed, settings)
    if len(calculated) != len(completed):
        raise ValueError('Indicator must return one value or gap per completed candle')
    values = iter(calculated)
    rows = []
    for candle in ordered:
        value = next(values) if ended.get(candle['timestamp'], False) else None
        rows.append(dict(timestamp=candle['timestamp'],
                         value=value if exact or value is None else float(value)))
    return rows


def configured_indicators(snapshot, instances):
    return [dict(instance, units=INDICATOR_TYPES[instance['type']].units,
                 pane=INDICATOR_TYPES[instance['type']].pane,
                 rows=indicator_rows(instance['type'], snapshot['candles'], snapshot['coverage'], instance['settings']))
            for instance in instances]


def validate_windows(short_window, long_window):
    if (type(short_window) is not int or type(long_window) is not int
            or short_window <= 0 or long_window <= short_window):
        raise ValueError('SMA windows must be positive whole numbers with short smaller than long')


def moving_averages(candles, coverage, short_window=DEFAULT_SHORT, long_window=DEFAULT_LONG):
    validate_windows(short_window, long_window)
    short_rows = indicator_rows('sma', candles, coverage, {'window': short_window}, exact=True)
    long_rows = indicator_rows('sma', candles, coverage, {'window': long_window}, exact=True)
    side, rows = 0, []
    for short_row, long_row in zip(short_rows, long_rows):
        short, long = short_row['value'], long_row['value']
        row = dict(timestamp=short_row['timestamp'], short=float(short) if short is not None else None,
                   long=float(long) if long is not None else None, signal=None)
        if short is not None and long is not None:
            current = (short > long) - (short < long)
            if current:
                if side and current != side:
                    row['signal'] = 'up' if current > 0 else 'down'
                side = current
        rows.append(row)
    return dict(short_window=short_window, long_window=long_window, rows=rows)


def with_averages(snapshot, short_window=DEFAULT_SHORT, long_window=DEFAULT_LONG):
    return dict(snapshot, moving_averages=moving_averages(
        snapshot['candles'], snapshot['coverage'], short_window, long_window))
