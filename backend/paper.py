"""Local long-only simulation. No broker connection; fees are always zero."""

from contextlib import contextmanager, closing
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import sqlite3
from threading import Lock
import uuid

from backend.candles import utc_datetime
from backend.timeframes import exchange_sessions
from backend.history import history_response
from backend import pnl


class RequestConflict(ValueError):
    pass


US_STOCK_SYMBOL = re.compile(r'[A-Z][A-Z0-9-]{0,15}')


def stock_quote(payload):
    symbol = payload.get('id')
    # Yahoo uses quote type 8 for stocks. Older stock observations can omit
    # type or currency, so only explicit non-stock or non-USD data is excluded.
    return (isinstance(symbol, str) and US_STOCK_SYMBOL.fullmatch(symbol) is not None
            and payload.get('currency', 'USD') == 'USD' and payload.get('quote_type', 8) == 8)


class PaperBroker:
    def __init__(self, state_database, observation_database, *, clock=None, order_size=1):
        if type(order_size) is not int or not 0 < order_size <= 2147483647:
            raise ValueError('Configured paper order size must be a positive whole number')
        self.order_size = order_size
        self.clock = clock or (lambda: datetime.now(UTC))
        self.receipt_lock = Lock()
        self.last_valuation = {}
        self.path = Path(state_database).resolve()
        self.market = Path(observation_database).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as c:
            c.executescript('''
                CREATE TABLE IF NOT EXISTS paper_accounts (
                    id TEXT PRIMARY KEY, mode TEXT NOT NULL, source_database TEXT NOT NULL,
                    cash TEXT NOT NULL, created_at TEXT NOT NULL, last_receipt_id INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS paper_positions (
                    account_id TEXT REFERENCES paper_accounts(id), symbol TEXT NOT NULL,
                    shares INTEGER NOT NULL CHECK(shares >= 0), PRIMARY KEY(account_id,symbol)
                );
                CREATE TABLE IF NOT EXISTS paper_orders (
                    id INTEGER PRIMARY KEY, account_id TEXT NOT NULL REFERENCES paper_accounts(id),
                    request_id TEXT NOT NULL, symbol TEXT NOT NULL, side TEXT NOT NULL,
                    quantity INTEGER, submitted_at TEXT NOT NULL, after_receipt_id INTEGER NOT NULL,
                    status TEXT NOT NULL, rejection_reason TEXT,
                    UNIQUE(account_id,request_id)
                );
                CREATE TABLE IF NOT EXISTS paper_fills (
                    id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL UNIQUE REFERENCES paper_orders(id),
                    quantity INTEGER NOT NULL, price TEXT NOT NULL, fees TEXT NOT NULL,
                    observation_id INTEGER NOT NULL, receipt_id INTEGER NOT NULL,
                    source_time_utc TEXT NOT NULL, executed_at TEXT NOT NULL,
                    market_observation_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS paper_requests (
                    account_id TEXT NOT NULL REFERENCES paper_accounts(id), request_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL, order_id INTEGER REFERENCES paper_orders(id),
                    result_json TEXT, PRIMARY KEY(account_id,request_id)
                );
            ''')
            c.executescript(pnl.SCHEMA)
            from backend.automation import setup_schema
            setup_schema(c)
            c.execute('BEGIN IMMEDIATE')
            pnl.backfill_fills(c)

    @contextmanager
    def transaction(self):
        with closing(sqlite3.connect(self.path, timeout=10)) as c:
            c.row_factory = sqlite3.Row
            c.execute('PRAGMA foreign_keys=ON')
            c.execute('BEGIN IMMEDIATE')
            try:
                yield c
                c.commit()
            except BaseException:
                c.rollback()
                raise

    def market_cursor(self):
        if not self.market.exists():
            return 0
        with closing(sqlite3.connect(self.market.as_uri()+'?mode=ro', uri=True)) as c:
            return c.execute('SELECT COALESCE(MAX(id),0) FROM receipts').fetchone()[0]

    def create_account(self, mode='live', *, now=None):
        identifier = 'live' if mode == 'live' else 'replay-' + str(uuid.uuid4())
        timestamp = utc_datetime(now or self.clock()).isoformat()
        cursor = self.market_cursor() if mode == 'live' else 0
        with self.transaction() as c:
            c.execute('INSERT OR IGNORE INTO paper_accounts VALUES (?,?,?,?,?,?)',
                      (identifier, mode, str(self.market), '1000', timestamp, cursor))
            account = self._account(c, identifier)
            if account['source_database'] != str(self.market):
                raise ValueError('Paper account belongs to a different observation database')
        return identifier

    @staticmethod
    def _account(c, identifier):
        row = c.execute('SELECT * FROM paper_accounts WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise ValueError('Paper account does not exist')
        return row

    @staticmethod
    def _shares(c, account_id, symbol):
        row = c.execute('SELECT shares FROM paper_positions WHERE account_id=? AND symbol=?',
                        (account_id, symbol)).fetchone()
        return row[0] if row else 0

    def snapshot(self, account_id='live'):
        with closing(sqlite3.connect(self.path)) as c:
            c.row_factory = sqlite3.Row
            c.execute('BEGIN')
            account = dict(self._account(c, account_id))
            positions = [dict(row) for row in c.execute('SELECT symbol,shares FROM paper_positions WHERE account_id=? ORDER BY symbol', (account_id,))]
            orders = [dict(row) for row in c.execute('SELECT * FROM paper_orders WHERE account_id=? ORDER BY id', (account_id,))]
            fills = [dict(row) for row in c.execute('''
                SELECT f.* FROM paper_fills f JOIN paper_orders o ON o.id=f.order_id
                WHERE o.account_id=? ORDER BY f.id
            ''', (account_id,))]
            pnl_history, pnl_summary = pnl.read(c, account_id, positions)
        return dict(account=account, positions=positions, orders=orders, fills=fills,
                    pnl_history=pnl_history, pnl_summary=pnl_summary,
                    simulated=True, currency='USD', starting_cash='1000', fees='0', configured_order_size=self.order_size)

    def tracked_symbols(self):
        with closing(sqlite3.connect(self.path)) as c:
            return {row[0] for row in c.execute("""
                SELECT symbol FROM paper_positions WHERE account_id='live' AND shares > 0
                UNION
                SELECT symbol FROM paper_orders WHERE account_id='live' AND status='pending'
            """)}

    def execute(self, account_id, *, request_id, action, symbol='AAPL', quantity=None,
                submitted_at=None, after_receipt_id=None, accept_new=True, automation_attempt_id=None,
                replay_symbol=None):
        """Shared execution entry point for HTTP or a future decision agent.

        Market context is supplied by the server/runner, never by a browser price.
        Invalid trade requests become audited rejected orders. Hold/wait never
        create orders. Same request id + intent returns the original result.
        """
        if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 128:
            raise ValueError('A stable request ID of 1 to 128 characters is required')
        symbol = symbol.strip().upper()
        if action not in {'buy', 'sell', 'close', 'hold', 'wait'}:
            raise ValueError('Choose buy, sell, close, hold or wait')
        if not US_STOCK_SYMBOL.fullmatch(symbol):
            raise ValueError('Enter a U.S. stock ticker in Yahoo format, such as MSFT or BRK-B')
        payload = json.dumps(dict(action=action, symbol=symbol, quantity=quantity), sort_keys=True, allow_nan=False)
        timestamp = utc_datetime(submitted_at or self.clock()).isoformat()
        with self.transaction() as c:
            account = self._account(c, account_id)
            previous = c.execute('SELECT * FROM paper_requests WHERE account_id=? AND request_id=?',
                                 (account_id, request_id)).fetchone()
            if previous:
                if previous['payload_json'] != payload:
                    raise RequestConflict('Request ID was already used with different order details')
                if previous['order_id'] is not None:
                    return dict(c.execute('SELECT * FROM paper_orders WHERE id=?', (previous['order_id'],)).fetchone())
                return json.loads(previous['result_json'])
            if not accept_new:
                raise ValueError('Replay session is closed; reopen replay to submit a new action')
            if replay_symbol is not None and symbol != replay_symbol:
                raise ValueError('Order ticker must match the replay ticker')
            if automation_attempt_id:
                from backend.automation import authorize_submission
                reason=authorize_submission(c,self,automation_attempt_id,account_id,action,symbol,quantity)
                if reason:
                    c.execute("UPDATE automation_attempts SET status='skipped',reason=? WHERE id=? AND status='reviewed'",(reason,automation_attempt_id))
                    return dict(status='skipped',rejection_reason=reason)
            shares = self._shares(c, account_id, symbol)
            if action in {'hold', 'wait'}:
                reason = ('Hold requires an existing position' if action == 'hold' and shares == 0 else
                          'Wait requires an empty position; use hold to keep shares' if action == 'wait' and shares else None)
                result = dict(status='rejected' if reason else 'no_order', action=action, rejection_reason=reason, order_id=None)
                c.execute('INSERT INTO paper_requests VALUES (?,?,?,?,?)',
                          (account_id, request_id, payload, None, json.dumps(result)))
                if automation_attempt_id:
                    c.execute('UPDATE automation_attempts SET status=?,reason=? WHERE id=?',('skipped' if reason else 'no_order',reason,automation_attempt_id))
                return result
            reason = None
            valid = type(quantity) is int and 0 < quantity <= 2147483647
            if action in {'buy', 'sell'} and not valid:
                reason = 'Quantity must be a positive whole number, at most 2147483647'
            elif action == 'close' and quantity is not None:
                reason = 'Close uses the entire position; omit quantity'
            elif action in {'sell', 'close'} and (shares == 0 or (action == 'sell' and quantity > shares)):
                reason = 'Cannot sell more shares than held'
            elif action == 'buy' and Decimal(account['cash']) <= 0:
                reason = 'Insufficient cash'
            order_quantity = shares if action == 'close' else quantity if valid else None
            cursor = account['last_receipt_id'] if after_receipt_id is None else after_receipt_id
            order = c.execute('''
                INSERT INTO paper_orders (account_id,request_id,symbol,side,quantity,submitted_at,
                                          after_receipt_id,status,rejection_reason)
                VALUES (?,?,?,?,?,?,?,?,?)
            ''', (account_id, request_id, symbol, action, order_quantity, timestamp, cursor,
                  'rejected' if reason else 'pending', reason))
            c.execute('INSERT INTO paper_requests VALUES (?,?,?,?,NULL)',
                      (account_id, request_id, payload, order.lastrowid))
            if automation_attempt_id:
                c.execute('UPDATE automation_attempts SET order_id=?,status=?,reason=? WHERE id=?',
                    (order.lastrowid,'skipped' if reason else 'pending',reason,automation_attempt_id))
            return dict(c.execute('SELECT * FROM paper_orders WHERE id=?', (order.lastrowid,)).fetchone())

    @staticmethod
    def eligible(event):
        try:
            payload = event['payload']
            price = Decimal(str(payload.get('price')))
            if (not stock_quote(payload) or isinstance(payload.get('price'), bool)
                    or not price.is_finite() or price <= 0 or event.get('repeat') or event.get('supersedes') is not None):
                return None
            if not isinstance(event.get('source_time_utc'), str) or not isinstance(event.get('received_at_utc'), str):
                return None
            source, received = utc_datetime(event['source_time_utc']), utc_datetime(event['received_at_utc'])
            if source > received:
                return None
            sessions = exchange_sessions('NASDAQ', (source-timedelta(days=1)).date().isoformat(),
                                         (source+timedelta(days=1)).date().isoformat())
            if not any(session.opened <= source < session.closed for session in sessions):
                return None
            return price
        except (ValueError, TypeError, InvalidOperation, KeyError):
            return None

    def observe(self, account_id, event):
        """FIFO fills on a newly delivered receipt; all state changes atomic."""
        price = self.eligible(event)
        with self.transaction() as c:
            account = self._account(c, account_id)
            if event['receipt_id'] <= account['last_receipt_id']:
                return
            c.execute('UPDATE paper_accounts SET last_receipt_id=? WHERE id=?', (event['receipt_id'], account_id))
            if price is None:
                return
            cash = Decimal(account['cash'])
            for order in c.execute('''SELECT * FROM paper_orders WHERE account_id=? AND status='pending'
                                       AND symbol=? AND after_receipt_id < ? ORDER BY id''',
                                   (account_id, event['payload']['id'], event['receipt_id'])).fetchall():
                if utc_datetime(event['received_at_utc']) < utc_datetime(order['submitted_at']):
                    continue
                from backend.automation import before_fill,finish
                guard=before_fill(c,self,order,event)
                if guard:
                    c.execute("UPDATE paper_orders SET status='cancelled',rejection_reason=? WHERE id=?",(guard,order['id']))
                    finish(c,order['id'],'skipped',guard)
                    continue
                shares = self._shares(c, account_id, order['symbol'])
                quantity = shares if order['side'] == 'close' else order['quantity']
                cost = price * quantity
                reason = ('Insufficient cash at fill' if order['side'] == 'buy' and cash < cost else
                          'Insufficient shares at fill' if order['side'] != 'buy' and (quantity <= 0 or quantity > shares) else None)
                if reason:
                    c.execute("UPDATE paper_orders SET status='rejected',rejection_reason=? WHERE id=?", (reason, order['id']))
                    finish(c,order['id'],'skipped',reason)
                    continue
                buying = order['side'] == 'buy'
                cash = cash - cost if buying else cash + cost
                shares = shares + quantity if buying else shares - quantity
                c.execute('INSERT INTO paper_positions VALUES (?,?,?) ON CONFLICT(account_id,symbol) DO UPDATE SET shares=excluded.shares',
                          (account_id, order['symbol'], shares))
                c.execute('UPDATE paper_accounts SET cash=? WHERE id=?', (str(cash), account_id))
                c.execute("UPDATE paper_orders SET status='filled',quantity=? WHERE id=?", (quantity, order['id']))
                c.execute('''INSERT INTO paper_fills (order_id,quantity,price,fees,observation_id,receipt_id,
                             source_time_utc,executed_at,market_observation_json) VALUES (?,?,?,'0',?,?,?,?,?)''',
                          (order['id'], quantity, str(price), event['observation_id'], event['receipt_id'],
                           event['source_time_utc'], event['received_at_utc'], json.dumps(event['payload'], sort_keys=True)))
                fill = c.execute('SELECT * FROM paper_fills WHERE order_id=?', (order['id'],)).fetchone()
                pnl.record_fill(c, fill, order, str(cash))
                finish(c,order['id'],'filled',fill_id=fill['id'])

    def catch_up_live(self,account_id='live'):
        if not self.market.exists():
            return
        # Recorder callbacks, dashboard polling and the background broker may
        # all see the same receipts. Replay the live ledger in one serial pass.
        with self.receipt_lock:
            self._catch_up_receipts(account_id)

    def _catch_up_receipts(self, account_id):
        with closing(sqlite3.connect(self.path)) as c:
            c.row_factory = sqlite3.Row
            cursor = self._account(c, account_id)['last_receipt_id']
        with closing(sqlite3.connect(self.market.as_uri()+'?mode=ro', uri=True)) as c:
            rows = c.execute('''SELECT r.id,r.observation_id,r.received_at_utc,o.source_time_utc,o.payload_json,
                              o.supersedes_observation_id,(SELECT MIN(id) FROM receipts WHERE observation_id=o.id)
                              FROM receipts r JOIN observations o ON o.id=r.observation_id
                              WHERE r.id>? AND o.provider='yahoo' ORDER BY r.id''',
                             (cursor,)).fetchall()
        for row in rows:
            if utc_datetime(row[2]) > utc_datetime(self.clock()):
                break
            self.mark_live(as_of=row[2], receipt_limit=row[0],account_id=account_id)
            self.observe(account_id, dict(receipt_id=row[0], observation_id=row[1], received_at_utc=row[2],
                                     source_time_utc=row[3], payload=json.loads(row[4]), supersedes=row[5], repeat=row[0] != row[6]))
            cursor = row[0]

        now = utc_datetime(self.clock())
        key = cursor, now.replace(second=0, microsecond=0)
        if key != self.last_valuation.get(account_id):
            self.mark_live(as_of=now, receipt_limit=cursor, account_id=account_id)
            self.last_valuation[account_id] = key

    def mark_completed(self, account_id, snapshot, *, event_time, receipt_id):
        with self.transaction() as c:
            self._account(c, account_id)
            pnl.mark_completed(c, account_id, snapshot, event_time=utc_datetime(event_time).isoformat(), receipt_id=receipt_id)

    def mark_live(self, *, as_of, receipt_limit,account_id='live'):
        with closing(sqlite3.connect(self.path)) as c:
            symbols = [row[0] for row in c.execute('''
                SELECT symbol FROM paper_positions WHERE account_id=? AND shares>0 ORDER BY symbol
            ''', (account_id,))]
        for symbol in symbols:
            snapshot = history_response(symbol, source='observations', calendar='NASDAQ',
                                        database=self.market, as_of=as_of, receipt_limit=receipt_limit,
                                        quote_filter=stock_quote)
            self.mark_completed(account_id, snapshot, event_time=as_of, receipt_id=receipt_limit)
