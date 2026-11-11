"""Named indicator settings, separate from immutable market observations."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3

from backend.indicators import validate_settings
from backend.timeframes import TIMEFRAMES

DEFAULT_CONFIG_DATABASE = Path(__file__).resolve().parent / 'data' / 'chart-config.sqlite3'


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
