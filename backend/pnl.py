"""Append-only weighted-average paper P&L; exact cost arithmetic, USD text output."""

from decimal import Decimal, localcontext
from fractions import Fraction

from backend.candles import utc_datetime

SCHEMA = '''
    CREATE TABLE IF NOT EXISTS paper_pnl_state (
        account_id TEXT NOT NULL REFERENCES paper_accounts(id), symbol TEXT NOT NULL,
        shares INTEGER NOT NULL, basis_exact TEXT NOT NULL, realized_exact TEXT NOT NULL,
        last_fill_at TEXT NOT NULL, last_candle_time TEXT, last_candle_price TEXT,
        candle_version INTEGER NOT NULL DEFAULT 0, last_mark_receipt INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(account_id,symbol)
    );
    CREATE TABLE IF NOT EXISTS paper_pnl_history (
        id INTEGER PRIMARY KEY, account_id TEXT NOT NULL REFERENCES paper_accounts(id),
        symbol TEXT NOT NULL, event_key TEXT NOT NULL, event_type TEXT NOT NULL,
        event_time TEXT NOT NULL, price_time TEXT, price_source TEXT NOT NULL, price TEXT,
        cash TEXT NOT NULL, shares INTEGER NOT NULL, average_cost TEXT,
        realized TEXT NOT NULL, unrealized TEXT, total TEXT,
        basis_exact TEXT NOT NULL, realized_exact TEXT NOT NULL, unrealized_exact TEXT,
        fill_id INTEGER UNIQUE REFERENCES paper_fills(id), candle_time TEXT, receipt_id INTEGER,
        UNIQUE(account_id,symbol,event_key)
    );
'''


def money(value):
    if value is None:
        return None
    value = Fraction(value)
    if not value:
        return '0'
    with localcontext() as context:
        context.prec = 40
        label = format(Decimal(value.numerator) / Decimal(value.denominator), 'f')
        return label.rstrip('0').rstrip('.') if '.' in label else label


def state(c, account_id, symbol):
    return c.execute('SELECT * FROM paper_pnl_state WHERE account_id=? AND symbol=?', (account_id, symbol)).fetchone()


def append(c, *, account_id, symbol, event_key, event_type, event_time, price_time,
           price_source, price, cash, shares, basis, realized, fill_id=None,
           candle_time=None, receipt_id=None):
    unrealized = shares * price - basis if shares and price is not None else None if shares else Fraction(0)
    total = realized + unrealized if unrealized is not None else None
    c.execute('''INSERT INTO paper_pnl_history
        (account_id,symbol,event_key,event_type,event_time,price_time,price_source,price,cash,shares,
         average_cost,realized,unrealized,total,basis_exact,realized_exact,unrealized_exact,fill_id,candle_time,receipt_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (account_id, symbol, event_key, event_type, event_time, price_time, price_source,
         money(price), str(cash), shares, money(basis / shares) if shares else None,
         money(realized), money(unrealized), money(total), str(basis), str(realized),
         str(unrealized) if unrealized is not None else None, fill_id, candle_time, receipt_id))


def record_fill(c, fill, order, cash):
    """Must run in the same transaction as its fill/balance updates."""
    if c.execute('SELECT 1 FROM paper_pnl_history WHERE fill_id=?', (fill['id'],)).fetchone():
        return
    previous = state(c, order['account_id'], order['symbol'])
    shares = previous['shares'] if previous else 0
    basis = Fraction(previous['basis_exact']) if previous else Fraction(0)
    realized = Fraction(previous['realized_exact']) if previous else Fraction(0)
    price, quantity = Fraction(fill['price']), fill['quantity']
    if order['side'] == 'buy':
        basis += price * quantity
        shares += quantity
    else:
        if quantity > shares or shares == 0:
            raise ValueError('P&L fill history has an inconsistent share balance')
        average = basis / shares
        realized += quantity * (price - average)
        basis -= quantity * average
        shares -= quantity
    c.execute('''INSERT INTO paper_pnl_state
        (account_id,symbol,shares,basis_exact,realized_exact,last_fill_at) VALUES (?,?,?,?,?,?)
        ON CONFLICT(account_id,symbol) DO UPDATE SET shares=excluded.shares,
        basis_exact=excluded.basis_exact,realized_exact=excluded.realized_exact,last_fill_at=excluded.last_fill_at''',
        (order['account_id'], order['symbol'], shares, str(basis), str(realized), fill['executed_at']))
    append(c, account_id=order['account_id'], symbol=order['symbol'], event_key=f"fill:{fill['id']}",
           event_type='fill', event_time=fill['executed_at'], price_time=fill['source_time_utc'],
           price_source=f"Fill · order {order['id']} · observation {fill['observation_id']}",
           price=price, cash=cash, shares=shares, basis=basis, realized=realized,
           fill_id=fill['id'], receipt_id=fill['receipt_id'])


def backfill_fills(c):
    """Initialize legacy fills once; don't invent historical candle valuations."""
    balances = {}
    for row in c.execute('''SELECT f.*,o.account_id,o.symbol,o.side FROM paper_fills f
                            JOIN paper_orders o ON o.id=f.order_id ORDER BY f.id''').fetchall():
        account_id = row['account_id']
        cash = balances.get(account_id, Fraction(1000))
        amount = Fraction(row['price']) * row['quantity']
        cash = cash - amount if row['side'] == 'buy' else cash + amount
        balances[account_id] = cash
        record_fill(c, row, dict(id=row['order_id'], account_id=account_id, symbol=row['symbol'], side=row['side']), money(cash))


def mark_completed(c, account_id, snapshot, *, event_time, receipt_id):
    """Prospective 1m marks. Repeated/revised close handling is durable."""
    symbol = snapshot.get('symbol', 'AAPL')
    previous = state(c, account_id, symbol)
    if previous is None or previous['shares'] == 0 or receipt_id < previous['last_mark_receipt']:
        return
    shares, basis, realized = previous['shares'], Fraction(previous['basis_exact']), Fraction(previous['realized_exact'])
    last_time, last_price, version = previous['last_candle_time'], previous['last_candle_price'], previous['candle_version']
    cash = c.execute('SELECT cash FROM paper_accounts WHERE id=?', (account_id,)).fetchone()[0]
    statuses = {row['timestamp']: row for row in snapshot['coverage']}
    for candle in sorted(snapshot['candles'], key=lambda row: row['timestamp']):
        completion = statuses[candle['timestamp']]
        if not completion['ended'] or utc_datetime(completion['interval_end']) > utc_datetime(event_time):
            continue
        # Never mark today's holdings with a bar that ended before their latest fill.
        if utc_datetime(completion['interval_end']) <= utc_datetime(previous['last_fill_at']):
            continue
        timestamp = candle['timestamp']
        if last_time is not None and utc_datetime(timestamp) < utc_datetime(last_time):
            continue
        try:
            value = candle['close']
            price = Fraction(str(value)) if not isinstance(value, bool) else None
            if price is not None and price <= 0:
                price = None
        except (ValueError, TypeError, ZeroDivisionError):
            price = None
        label = money(price)
        if timestamp == last_time and label == last_price:
            continue
        event_key = f'candle:1m:{timestamp}:receipt:{receipt_id}:price:{label}'
        if c.execute('SELECT 1 FROM paper_pnl_history WHERE account_id=? AND symbol=? AND event_key=?',
                     (account_id, symbol, event_key)).fetchone():
            continue
        version = version + 1 if timestamp == last_time else 1
        append(c, account_id=account_id, symbol=symbol, event_key=event_key,
               event_type='valuation', event_time=event_time, price_time=completion['interval_end'],
               price_source='Completed 1m candle close', price=price, cash=cash, shares=shares,
               basis=basis, realized=realized, candle_time=timestamp, receipt_id=receipt_id)
        last_time, last_price = timestamp, label
        c.execute('''UPDATE paper_pnl_state SET last_candle_time=?,last_candle_price=?,candle_version=?,last_mark_receipt=?
                     WHERE account_id=? AND symbol=?''', (last_time,last_price,version,receipt_id,account_id,symbol))


def read(c, account_id, positions):
    history = [dict(row) for row in c.execute('SELECT * FROM paper_pnl_history WHERE account_id=? ORDER BY id', (account_id,))]
    latest = {row['symbol']: row for row in history}
    summaries = []
    for position in positions:
        row = latest.get(position['symbol'])
        if row is None:
            row = dict(symbol=position['symbol'], shares=position['shares'], average_cost=None,
                       realized='0', unrealized=None if position['shares'] else '0',
                       total=None if position['shares'] else '0', price=None, price_time=None, price_source=None)
        summaries.append(dict(row, valuation_status='unavailable' if row['unrealized'] is None else 'available'))
    return history, summaries
