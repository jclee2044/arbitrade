"""Explicitly enabled, candle-deduplicated paper automation; no real broker."""
from contextlib import closing
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
import json
import sqlite3
import uuid

from backend.candles import utc_datetime
from backend.decisions import candle_end,encoded,validate_proposal
from backend.decision_review import facts
from backend.indicators import validate_windows


def setup_schema(c):
    c.executescript('''
      CREATE TABLE IF NOT EXISTS automation_accounts (source_database TEXT PRIMARY KEY,account_id TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS automation_runs (
        id TEXT PRIMARY KEY,requested_account TEXT NOT NULL,account_id TEXT NOT NULL,strategy TEXT NOT NULL,
        symbol TEXT NOT NULL,interval TEXT NOT NULL,short_window INTEGER NOT NULL,long_window INTEGER NOT NULL,
        started_at TEXT NOT NULL,enabled INTEGER NOT NULL,max_age INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS automation_attempts (
        id TEXT PRIMARY KEY,run_id TEXT NOT NULL REFERENCES automation_runs(id),account_id TEXT NOT NULL,
        strategy TEXT NOT NULL,symbol TEXT NOT NULL,interval TEXT NOT NULL,candle_timestamp TEXT NOT NULL,
        cutoff TEXT NOT NULL,snapshot_id TEXT,decision_id TEXT UNIQUE,status TEXT NOT NULL,reason TEXT,
        order_id INTEGER UNIQUE,fill_id INTEGER,capture_error TEXT,created_at TEXT NOT NULL,
        UNIQUE(account_id,strategy,symbol,interval,candle_timestamp));
    ''')


def finish(c,order_id,status,reason=None,fill_id=None):
    c.execute('UPDATE automation_attempts SET status=?,reason=?,fill_id=? WHERE order_id=?',
              (status,reason,fill_id,order_id))


def _approval(c,broker,attempt,now):
    run=c.execute('SELECT * FROM automation_runs WHERE id=?',(attempt['run_id'],)).fetchone()
    if not run or not run['enabled']:return 'automation_stopped'
    age=(utc_datetime(now)-utc_datetime(attempt['cutoff'])).total_seconds()
    if age<0 or age>run['max_age']:return 'decision_expired'
    d=c.execute('SELECT * FROM decisions WHERE id=?',(attempt['decision_id'],)).fetchone()
    rv=c.execute('SELECT payload_json FROM decision_reviews WHERE decision_id=?',(attempt['decision_id'],)).fetchone()
    saved=c.execute('SELECT * FROM decision_snapshots WHERE id=?',(attempt['snapshot_id'],)).fetchone()
    if not d or not rv or not saved:return 'missing_reviewed_decision'
    review=json.loads(rv[0])
    if (d['status']!='valid' or not review['final_check']['passed']
        or review['reviewer']['verdict']!='accept' or review['reviewer']['status']!='valid'):return 'decision_not_approved'
    if sha256(saved['payload_json'].encode()).hexdigest()!=saved['payload_sha256']:return 'snapshot_integrity_failed'
    s=json.loads(saved['payload_json']);review=json.loads(rv[0]);account=broker._account(c,attempt['account_id'])
    if (d['snapshot_id']!=attempt['snapshot_id'] or s['account']['account_id']!=attempt['account_id']
        or s['symbol']!=attempt['symbol'] or s['interval']!=attempt['interval']
        or utc_datetime(s['candle_timestamp'])!=utc_datetime(attempt['candle_timestamp'])
        or review['snapshot_sha256']!=saved['payload_sha256']):return 'decision_context_mismatch'
    image=c.execute('SELECT * FROM decision_images WHERE decision_id=?',(d['id'],)).fetchone()
    if not image or not image['png'] or image['comparison']!='match':return 'fresh_chart_analysis_required'
    digest=sha256(image['png']).hexdigest()
    if review['analyst'].get('image_sha256')!=digest or review['reviewer'].get('image_sha256')!=digest:return 'chart_integrity_failed'
    if not s['completeness']['complete']:return 'incomplete_snapshot'
    if s['provenance']['market_data_kind']=='constructed' and account['mode']!='test':return 'test_account_required'
    if account['mode'] not in {'live','test'}:return 'unsupported_account_mode'
    if not facts(s,d['proposal'])['strategy_passed'] or not validate_proposal(s,d['proposal'])[0]:return 'backend_rule_violation'
    if s['account']['order_size']!=broker.order_size:return 'configured_size_changed'
    return None


def authorize_submission(c,broker,attempt_id,account_id,action,symbol,quantity):
    a=c.execute('SELECT * FROM automation_attempts WHERE id=?',(attempt_id,)).fetchone()
    if not a:raise ValueError('Automation attempt not found')
    if a['status']!='reviewed':return 'attempt_already_handled'
    if a['account_id']!=account_id or a['symbol']!=symbol:return 'decision_context_mismatch'
    reason=_approval(c,broker,a,broker.clock())
    if reason:return reason
    d=c.execute('SELECT * FROM decisions WHERE id=?',(a['decision_id'],)).fetchone()
    if action!=d['proposal'] or (action in {'buy','sell'} and quantity!=d['quantity']):return 'decision_action_mismatch'
    shares=broker._shares(c,account_id,symbol);cash=Decimal(broker._account(c,account_id)['cash'])
    snapshot=json.loads(c.execute('SELECT payload_json FROM decision_snapshots WHERE id=?',(a['snapshot_id'],)).fetchone()[0])
    if action=='buy' and cash<Decimal(str(snapshot['candle']['close']))*quantity:return 'insufficient_cash_before_submit'
    if action in {'sell','close','hold'} and (shares<=0 or (action=='sell' and quantity>shares)):return 'insufficient_position_before_submit'
    if action=='wait' and shares:return 'position_changed_before_submit'
    return None


def before_fill(c,broker,order,event):
    a=c.execute('SELECT * FROM automation_attempts WHERE order_id=?',(order['id'],)).fetchone()
    if not a:return None
    if a['status']!='pending':return 'attempt_already_handled'
    now=max(utc_datetime(broker.clock()),utc_datetime(event['received_at_utc']))
    reason=_approval(c,broker,a,now)
    if reason:return reason
    age=(now-utc_datetime(event['source_time_utc'])).total_seconds()
    if age>30:return 'stale_fill_quote'
    return None


class AutomationService:
    def __init__(self,broker,decisions,indicators):
        self.broker,self.decisions,self.indicators=broker,decisions,indicators
        # A server restart requires a new explicit Start; candle keys survive it.
        with broker.transaction() as c:
            c.execute('UPDATE automation_runs SET enabled=0')
            self._cancel(c,None,'backend_restarted')
            c.execute("UPDATE automation_attempts SET status='skipped',reason='backend_restarted' WHERE status IN ('capturing','analyzing','reviewed')")

    @staticmethod
    def _cancel(c,run_id,reason):
        query="SELECT * FROM automation_attempts WHERE status='pending'";args=()
        if run_id:query+=' AND run_id=?';args=(run_id,)
        for a in c.execute(query,args).fetchall():
            c.execute("UPDATE paper_orders SET status='cancelled',rejection_reason=? WHERE id=? AND status='pending'",(reason,a['order_id']))
            c.execute("UPDATE automation_attempts SET status='skipped',reason=? WHERE id=?",(reason,a['id']))

    def _test_source(self):
        with closing(sqlite3.connect(self.broker.market.as_uri()+'?mode=ro',uri=True)) as c:
            return any(json.loads(r[0]).get('test_data') for r in c.execute("SELECT payload_json FROM observations WHERE ticker='AAPL'"))

    def start(self,*,account_id='live',symbol='AAPL',interval='1m',short_window=20,long_window=50):
        validate_windows(short_window,long_window)
        if account_id!='live' or symbol!='AAPL':raise ValueError('Automation uses the live chart, routing constructed data to a separate test account. Replay remains manual.')
        from backend.timeframes import TIMEFRAMES
        if interval not in TIMEFRAMES:raise ValueError('Unsupported interval')
        requested=account_id;now=self.broker.clock().isoformat();strategy=f'sma-v1:{short_window}:{long_window}'
        if self._test_source():
            with self.broker.transaction() as c:
                row=c.execute('SELECT account_id FROM automation_accounts WHERE source_database=?',(str(self.broker.market),)).fetchone()
                if row:account_id=row[0]
                else:
                    account_id='test-'+str(uuid.uuid4())
                    c.execute('INSERT INTO paper_accounts VALUES (?,?,?,?,?,?)',(account_id,'test',str(self.broker.market),'1000',now,self.broker.market_cursor()))
                    c.execute('INSERT INTO automation_accounts VALUES (?,?)',(str(self.broker.market),account_id))
        with self.broker.transaction() as c:
            # One active controller for this account/symbol. Starting another configuration revokes old runs.
            for r in c.execute('SELECT id FROM automation_runs WHERE account_id=? AND symbol=? AND enabled=1',(account_id,symbol)).fetchall():
                c.execute('UPDATE automation_runs SET enabled=0 WHERE id=?',(r['id'],));self._cancel(c,r['id'],'run_replaced')
            identifier=str(uuid.uuid4())
            c.execute('INSERT INTO automation_runs VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (identifier,requested,account_id,strategy,symbol,interval,short_window,long_window,now,1,120))
        return self.state(identifier)

    def stop(self,run_id):
        with self.broker.transaction() as c:
            c.execute('UPDATE automation_runs SET enabled=0 WHERE id=?',(run_id,));self._cancel(c,run_id,'automation_stopped')
            c.execute("UPDATE automation_attempts SET status='skipped',reason='automation_stopped' WHERE run_id=? AND status IN ('capturing','reviewed')",(run_id,))
        return self.state(run_id)

    def claim(self,run_id,candle_timestamp):
        stamp=utc_datetime(candle_timestamp).isoformat();identifier=str(uuid.uuid4())
        with self.broker.transaction() as c:
            r=c.execute('SELECT * FROM automation_runs WHERE id=?',(run_id,)).fetchone()
            if not r or not r['enabled']:raise ValueError('Automation is stopped')
            old=c.execute('SELECT id FROM automation_attempts WHERE account_id=? AND strategy=? AND symbol=? AND interval=? AND candle_timestamp=?',
                (r['account_id'],r['strategy'],r['symbol'],r['interval'],stamp)).fetchone()
            if old:return dict(attempt=self.attempt(old[0]),claimed=False)
            cutoff=candle_end(r['symbol'],r['interval'],stamp)
            if cutoff>utc_datetime(self.broker.clock()):raise ValueError('Candle is still forming')
            if cutoff<=utc_datetime(r['started_at']):raise ValueError('Automation starts with future completed candles; no history backfill')
            c.execute('INSERT INTO automation_attempts VALUES (?,?,?,?,?,?,?,?,NULL,NULL,?,NULL,NULL,NULL,NULL,?)',
                (identifier,run_id,r['account_id'],r['strategy'],r['symbol'],r['interval'],stamp,cutoff.isoformat(),'capturing',self.broker.clock().isoformat()))
        try:
            frozen=self.decisions.freeze(account_id=r['account_id'],symbol=r['symbol'],interval=r['interval'],candle_timestamp=stamp,
                short_window=r['short_window'],long_window=r['long_window'],instances=self.indicators.list(r['symbol'],r['interval']))
            with self.broker.transaction() as c:c.execute('UPDATE automation_attempts SET snapshot_id=? WHERE id=?',(frozen['snapshot']['snapshot_id'],identifier))
        except ValueError as error:
            with self.broker.transaction() as c:c.execute("UPDATE automation_attempts SET status='skipped',reason='snapshot_unavailable' WHERE id=?",(identifier,))
            frozen=None
        return dict(attempt=self.attempt(identifier),snapshot=frozen,claimed=True)

    async def analyze(self,attempt_id,capture=None,capture_error=None):
        from backend.chart_decisions import decide_image
        with self.broker.transaction() as c:
            a=c.execute('SELECT * FROM automation_attempts WHERE id=?',(attempt_id,)).fetchone()
            if not a:raise ValueError('Attempt not found')
            r=c.execute('SELECT * FROM automation_runs WHERE id=?',(a['run_id'],)).fetchone()
            if a['status']!='capturing':return self.attempt(attempt_id)
            if not r['enabled']:
                c.execute("UPDATE automation_attempts SET status='skipped',reason='automation_stopped' WHERE id=?",(attempt_id,))
                return dict(a,status='skipped',reason='automation_stopped')
            c.execute("UPDATE automation_attempts SET status='analyzing',capture_error=? WHERE id=?",('chart_unavailable' if capture_error else None,attempt_id))
        decision=await decide_image(self.decisions,a['snapshot_id'],capture or {})
        with self.broker.transaction() as c:
            enabled=c.execute('SELECT enabled FROM automation_runs WHERE id=?',(a['run_id'],)).fetchone()[0]
            c.execute('UPDATE automation_attempts SET decision_id=?,status=?,reason=? WHERE id=?',
                (decision['id'],'reviewed' if enabled else 'skipped',None if enabled else 'automation_stopped',attempt_id))
        if enabled:self.apply(attempt_id)
        return self.attempt(attempt_id)

    def apply(self,attempt_id):
        a=self.attempt(attempt_id)
        if a['status'] not in {'reviewed','pending','filled','no_order'}:return a
        if a['order_id'] is not None or a['status']=='no_order':return a
        d=self.decisions.get_decision(a['decision_id'])
        self.broker.execute(a['account_id'],request_id='automation:'+attempt_id,action=d['proposal'] or 'wait',symbol=a['symbol'],
            quantity=d['quantity'] if d['proposal'] in {'buy','sell'} else None,after_receipt_id=self.broker.market_cursor(),automation_attempt_id=attempt_id)
        return self.attempt(attempt_id)

    def attempt(self,identifier):
        with closing(sqlite3.connect(self.broker.path)) as c:
            c.row_factory=sqlite3.Row;row=c.execute('SELECT * FROM automation_attempts WHERE id=?',(identifier,)).fetchone()
        if not row:raise ValueError('Attempt not found')
        return dict(row)

    def tick(self):
        self.broker.catch_up_live()
        with closing(sqlite3.connect(self.broker.path)) as c:
            accounts=[r[0] for r in c.execute('SELECT account_id FROM automation_accounts')]
        for account in accounts:self.broker.catch_up_live(account)

    def state(self,run_id=None):
        self.tick()
        with self.broker.transaction() as c:
            r=c.execute('SELECT * FROM automation_runs WHERE id=?',(run_id,)).fetchone() if run_id else c.execute('SELECT * FROM automation_runs ORDER BY rowid DESC LIMIT 1').fetchone()
            if not r:return dict(run=None,attempts=[],state=None)
            rows=c.execute('SELECT * FROM automation_attempts WHERE account_id=? ORDER BY rowid DESC LIMIT 50',(r['account_id'],)).fetchall()
            for a in rows:
                if a['status']=='pending' and (utc_datetime(self.broker.clock())-utc_datetime(a['cutoff'])).total_seconds()>r['max_age']:
                    c.execute("UPDATE paper_orders SET status='cancelled',rejection_reason='decision_expired' WHERE id=? AND status='pending'",(a['order_id'],))
                    c.execute("UPDATE automation_attempts SET status='skipped',reason='decision_expired' WHERE id=?",(a['id'],))
        attempts=[]
        for row in rows:
            a=self.attempt(row['id'])
            if a['decision_id']:
                a['decision']=self.decisions.get_decision(a['decision_id'])
                s=self.decisions.get_snapshot(a['snapshot_id'])['snapshot']
                a['signal']=s['indicators']['crossover'] or 'none'
            attempts.append(a)
        return dict(run=dict(r),attempts=attempts,state=self.broker.snapshot(r['account_id']))
