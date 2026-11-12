"""Named indicator settings, separate from immutable market observations."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3

from backend.indicators import validate_settings
from backend.timeframes import TIMEFRAMES

DEFAULT_CONFIG_DATABASE = Path(__file__).resolve().parent / 'data' / 'chart-config.sqlite3'
PRESET_PERIODS = (10, 20, 30, 50, 100, 200)
DEFAULT_PRESETS = {('sma', 20), ('sma', 200), ('ema', 30)}


def chart_selection(symbol, timeframe):
    symbol = symbol.strip().upper()
    if not symbol or len(symbol) > 32:
        raise ValueError('Symbol must contain 1 to 32 characters')
    if timeframe not in TIMEFRAMES:
        raise ValueError('Unsupported timeframe')
    return symbol, timeframe


class IndicatorStore:
    def update_settings(self, identifier, settings):
        with closing(sqlite3.connect(self.path)) as connection, connection:
            row = connection.execute('SELECT type FROM chart_indicators WHERE id=?', (identifier,)).fetchone()
            if row is None:
                raise ValueError('Indicator not found')
            settings = validate_settings(row[0], settings)
            connection.execute('UPDATE chart_indicators SET settings_json=? WHERE id=?',
                               (json.dumps(settings, sort_keys=True), identifier))
        return dict(id=identifier, settings=settings)

    def __init__(self, path=DEFAULT_CONFIG_DATABASE):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute('''
                CREATE TABLE IF NOT EXISTS chart_indicators (
                    id INTEGER PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL,
                    settings_json TEXT NOT NULL,
                    UNIQUE(symbol, timeframe, name)
                )
            ''')
            connection.execute('''
                CREATE TABLE IF NOT EXISTS indicator_presets (
                    symbol TEXT NOT NULL, timeframe TEXT NOT NULL, kind TEXT NOT NULL,
                    period INTEGER NOT NULL, enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
                    PRIMARY KEY(symbol,timeframe,kind,period)
                )
            ''')

    def presets(self, symbol, timeframe):
        symbol, timeframe = chart_selection(symbol, timeframe)
        with closing(sqlite3.connect(self.path)) as connection:
            overrides = {(kind, period): enabled for kind, period, enabled in connection.execute(
                'SELECT kind,period,enabled FROM indicator_presets WHERE symbol=? AND timeframe=?',
                (symbol, timeframe))}
        return [dict(id=f'{kind}-{period}', name=f'{kind.upper()} {period}', type=kind,
                     settings={'window': period}, preset=True, pane='price')
                for kind in ('sma', 'ema') for period in PRESET_PERIODS
                if overrides.get((kind, period), (kind, period) in DEFAULT_PRESETS)]

    def set_preset(self, symbol, timeframe, kind, period, enabled):
        symbol, timeframe = chart_selection(symbol, timeframe)
        if kind not in ('sma', 'ema') or period not in PRESET_PERIODS:
            raise ValueError('Choose a supported SMA or EMA preset')
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute('''INSERT INTO indicator_presets VALUES (?,?,?,?,?)
                                  ON CONFLICT(symbol,timeframe,kind,period) DO UPDATE SET enabled=excluded.enabled''',
                               (symbol, timeframe, kind, period, enabled))
        return self.presets(symbol, timeframe)

    def chart_indicators(self, symbol, timeframe):
        return self.list(symbol, timeframe) + self.presets(symbol, timeframe)

    def list(self, symbol, timeframe):
        symbol, timeframe = chart_selection(symbol, timeframe)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            rows = connection.execute('''
                SELECT id,symbol,timeframe,name,type,settings_json FROM chart_indicators
                WHERE symbol=? AND timeframe=? ORDER BY id
            ''', (symbol, timeframe)).fetchall()
        return [dict(id=r[0], symbol=r[1], timeframe=r[2], name=r[3], type=r[4], settings=json.loads(r[5]))
                for r in rows]

    def create(self, symbol, timeframe, name, kind, settings):
        symbol, timeframe = chart_selection(symbol, timeframe)
        name = name.strip()
        if not name or len(name) > 80:
            raise ValueError('Indicator name must contain 1 to 80 characters')
        settings = validate_settings(kind, settings)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            cursor = connection.execute('''
                INSERT INTO chart_indicators (symbol,timeframe,name,type,settings_json)
                VALUES (?,?,?,?,?)
            ''', (symbol, timeframe, name, kind, json.dumps(settings, sort_keys=True)))
            identifier = cursor.lastrowid
        return dict(id=identifier, symbol=symbol, timeframe=timeframe, name=name, type=kind, settings=settings)
