# Local paper trading

Explicit Start/Stop paper automation can now apply approved decisions through a
separate guarded path; manual questions remain read-only. See
[paper-automation.md](paper-automation.md) for current execution/dedup rules.

The dashboard's **Trade → Orders** panel shows USD cash, the selected ticker's
whole shares and P&L, plus the account's order history, rejection reasons and
linked fills. Enter a supported U.S. stock ticker such as MSFT or BRK-B in the
Live chart before submitting. Accounts start at **$1,000** with cash shared
across tickers. **Open positions** shows holdings and valuation across tickers.
Buy shares, sell part, or close the selected position. **Hold** keeps
an existing position; **Wait** leaves an empty position in cash. Neither creates
an order. Hold from cash and wait while holding return an explanation without
an order. No broker integration or real order routing exists.

Buy/sell quantities must be integer JSON numbers from 1 through 2147483647,
excluding booleans, strings and fractional numbers. The UI validates before
submission; invalid trade requests reaching execution become audited rejected
orders. A sell larger than current shares and a close from cash are rejected.
Close takes no quantity: it sells the entire remaining position at execution,
including changes caused by earlier pending orders.

## Simulated fill rule

1. A new valid request is **pending**, with its submission time and receipt-ID
   boundary. The currently displayed quote/candle is never a fill price.
2. Fill at the **next eligible arriving receipt** after that boundary for the
   same symbol, with zero fees. An eligible quote has a finite positive price,
   USD stock pricing, and a known source timestamp in the U.S. regular session
   at or before receipt time. Previously seen exact repeats and explicit revisions
   are skipped; after-hours, invalid and future-timestamp quotes are skipped.
   A normal delayed quote can fill when it arrives: “after submission” is
   evaluated by receipt arrival/time, not by requiring a newer source timestamp.
3. Orders for the same account process in order-ID order. Pending orders do not
   reserve resources. At fill, recheck available cash/shares; reject if insufficient.
   Another pending order can consume resources first. All-or-nothing fills:
   no partial executions, spread, slippage or liquidity model.
4. Cash arithmetic uses Decimal values stored as text, avoiding binary float
   money accumulation. UI rounds USD for display to two fractional digits.
5. Under one SQLite `BEGIN IMMEDIATE` transaction: advance the account's receipt
   cursor, insert the fill, update cash/shares, and mark the order filled (or
   rejected). A failure rolls everything back, including the cursor, for retry.
   Each order can have only one fill. Executed-at is simulated receipt time;
   source time is separately retained. Later revisions never rewrite old fills.

Accepted orders stay pending with the feed disabled, no next eligible receipt,
or at replay end. The backend keeps each live subscription active while its
ticker has an open position or a pending order, including when the user changes
charts or closes the page. Startup restores the subscriptions from SQLite.
The server processes committed receipts in receipt-ID order independently of
the dashboard, and marks each open position with the same ticker's completed
one-minute observed close. Realized P&L uses that ticker's weighted-average
cost and its sell fills. The dashboard reports the price and time of the last
valuation. Startup, live account reads and submissions also recover committed
receipts after the saved cursor.

## Accounts, persistence and replay isolation

Paper tables live in the **existing mutable chart-config SQLite database**,
`backend/data/chart-config.sqlite3` (`ARBITRADE_CONFIG_DATABASE`). This reuses
existing SQLite state alongside named indicators without writing execution
state into immutable recorded market observations. `ARBITRADE_DATABASE` still
selects the separately read observation database. Tests use disposable copies.

The live account ID is `live`, retained across refresh and backend restart.
Its first creation records the current last saved receipt, so preexisting
history cannot immediately fill a new order. It is bound to the observation
file path; using another observation database requires separate account state.

Each replay connection has its **own** `replay-<uuid>` account. New orders match
the replay ticker and use the current receipt and clock. Only `next` delivers its newly revealed
observation to execution. Reading account state and indicator `refresh` cannot
peek ahead or fill against future rows already stored on disk. Live receipts
never update replay accounts; replay does not spend live paper cash.

Restarting/reconnecting replay (including selection/window/timeframe changes)
creates a new $1,000 simulation account. Prior replay orders/fills remain in
SQLite for audit and can be read by account ID; their inactive sessions accept
no new actions. Retrying an already recorded request remains idempotent even
when the replay session is closed. Resuming an old replay execution account is
not implemented. The UI labels this behavior explicitly.

Stored tables:

- `paper_accounts`: ID/mode, observation file, USD cash, creation time, last receipt.
- `paper_positions`: whole shares by account/symbol (nonnegative).
- `paper_orders`: ID/account/request ID/symbol/side/quantity/submission time,
  receipt boundary/status/rejection reason.
- `paper_fills`: unique linked order, quantity/price/zero fees, original
  observation ID and receipt ID, source/execution timestamps, decoded market
  observation payload. Observation IDs refer to the file recorded on the account.
- `paper_requests`: stable ID + canonical intent, order link or no-order result.
  Original invalid quantity is retained in this intent even if order quantity
  is unavailable. Hold/wait are audited here without creating orders.

## Request retries and the shared execution function

Vue generates one UUID for each explicit intent. **Retry last request** resends
that same ID and exact intent, including after a network failure. The server's
(account ID, request ID) key returns the same order's current status instead of
creating a duplicate. Reusing an ID with different details returns HTTP 409.
The last UI retry intent stays in the current component; it is cleared on page
reload/account change. Request IDs and their results remain durable in SQLite.

Both HTTP and a future decision agent call `PaperBroker.execute(...)` in
`backend/paper.py`. Server/runner code owns the market context; no client fill
price, observation ID or replay clock is accepted as execution context.

```python
broker.catch_up_live()
order = broker.execute(
    'live', request_id='stable-id-for-this-intent', action='buy', symbol='AAPL',
    quantity=4, after_receipt_id=broker.market_cursor(),
)
```

`execute` submits/validates/deduplicates; receipt delivery through
`observe`/`catch_up_live` fills pending requests. A decision agent must generate
one stable ID per intended action and reuse it on retries, rather than creating
a new ID for a transport retry.

- `GET /api/paper/account?account_id=live`: balances/positions/orders/fills,
  simulation/currency/zero-fee metadata. Live reads can process newly arrived
  committed receipts; replay reads cannot advance execution.
- `POST /api/paper/actions`:

```json
{"account_id":"live","request_id":"stable-id-for-this-intent","action":"buy","symbol":"AAPL","quantity":4}
```

Response contains `result` and current `state`. Business rejection is a normal
response with `status: rejected` and a reason, retaining the audit record.
Malformed/unsupported requests return 422; conflicting retry IDs return 409.
For close/hold/wait, omit quantity or send null. Manual orders support U.S. stock
tickers in Yahoo format. Reviewed automation uses AAPL.

## Repeatable browser SmokeTest

```bash
PYTHONPATH=backend/.packages /usr/bin/python -m scripts.multi_ticker_paper_smoke
```

The multi-ticker runner uses the production FastAPI lifecycle with a constructed
Yahoo transport. Chromium submits AAPL and MSFT trades, switches charts and
closes the page. A read-only SQLite connection verifies that the backend
keeps the MSFT stream, rejects unrelated and non-USD quotes as fill prices,
and updates the right positions independently. The runner also verifies
restoration from a persisted pending order at startup and cleans up its
browser, services and disposable databases.

Run the original AAPL regression with this command.

```bash
PYTHONPATH=backend/.packages /usr/bin/python -m scripts.paper_smoke --output /tmp/arbitrade-paper-results
```

The runner starts isolated FastAPI/Vite (18000/15173), opens system Chromium,
uses disposable observations and a disposable existing-style chart-config
account DB, operates the Vue controls, and supplies labeled constructed prices
**after** the corresponding pending request. The test-only app is
`scripts.paper_fixture:app`; production exposes no quote-injection endpoint.
The fixture has fixed regular-session source times on November 10, with actual
receipt times at the test's later arrival/submission time.

| Action | Next arriving price | Cash | Shares |
| --- | --- | --- | --- |
| Start / wait | None | $1,000 | 0 |
| Buy 4 | $100 | $600 | 4 |
| Retry same buy / hold | No additional fill | $600 | 4 |
| Sell 1 | $110 | $710 | 3 |
| Close remaining 3 | $105 | $1,025 | 0 |
| Sell from empty account | Rejected | $1,025 | 0 |
| Actual backend restart + refresh | Exactly 3 persisted fills | $1,025 | 0 |

The browser/SQL comparison passed on November 11, 2026. A separate replay
account also stayed pending despite saved future prices; its first newly
revealed price triggered an insufficient-cash recheck rejection and left live
cash unchanged. Exactly **three fills globally** persisted. Backend unit tests
also verify actual replay fills only against delivered observations, concurrent
retries, FIFO resource rechecks, recovery, and full rollback on injected failure.

[Checked panel after restart](screenshots/paper-2026-11-11/after-restart.png),
[full phase/SQL report](screenshots/paper-2026-11-11/report.json),
[verification and failures](verification.md). The runner removes both disposable
DBs and cleans up its browser/services. Review services remain separate. Fresh
actual provider-to-paper-fill verification remains pending with Yahoo disabled.
