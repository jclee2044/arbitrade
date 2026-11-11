# Apply reviewed decisions to paper trading

Click **Start paper automation** in the dashboard's Paper automation panel. It
uses the applied SMA windows, AAPL and the current live-chart interval. Only
candles ending after Start are eligible; there is no historical backfill. Keep
the dashboard open so it can render and capture each completed candle. Replay
continues to use its manual controls; automation is restricted to the live chart.

For every newly completed candle, the server claims a durable candle key and
freezes its market/account snapshot. Vue renders only those records with the
shared manual-chart renderer and native PNG export. The fresh capture goes to
the existing analyst/reviewer services. No stale preview is reused. A missing
or unreadable image becomes a saved failed decision and a skipped execution.
The panel shows the last frozen capture and an audit table linking candle/signal,
decision ID, proposal, reviewer, final Python status, order/fill or skip reason,
and the fill's resulting cash/shares/P&L. Manual chart questions still create
no order.

**Stop paper automation** disables the run in SQLite and cancels its pending
orders in the simulator transaction. Late model replies can finish their saved
analysis but cannot execute. The UI stops initiating captures immediately and
waits for server confirmation; a network failure is shown as an unconfirmed
Stop, with retry available. Changing chart account/symbol/interval/SMA windows
requests Stop; unmounting sends a Stop request. Server restart disables every
run and cancels pending automation orders before market catch-up. Start again
explicitly after restart. Browser crashes/network outages cannot deliver a Stop
request; pending orders still face the short age limit below. New analyses need
an open browser and working transport. Automation is off by default.

## Accounts and approval

Start on an observation source containing constructed `test_data` automatically
selects a separate `test-...` paper account, initially $1,000 cash/zero shares.
Its ID is explicit in the panel, survives restart for deduplication and never
shares balances with the ordinary live account. SmokeTest uses disposable
SQLite files and removes this account with them. A newly tainted/mismatched live
snapshot is skipped rather than permitted to trade the live account; Start again
selects the test account. Account identity stays fixed throughout a decision.

Application requires all of these checks inside the simulator transaction:

- The run is still enabled and the decision belongs to its account, strategy,
  symbol, interval and completed candle.
- The stored snapshot hash, same-image hashes, complete input, visual comparison,
  analyst result and accepted reviewer result match the saved decision.
- Python's frozen account/strategy rules pass: buy on up, sell/close on down;
  hold requires holdings and wait requires flat cash. Buy/sell use the frozen
  configured whole-share size. A changed simulator size skips the decision.
- Constructed data can execute only within its isolated test account. It retains
  its ordinary decision-level `paper_order_eligible=false`; the automation test
  route separately permits a fully reviewed, complete test simulation.

Buy/sell submit that configured size; close exits the whole current position.
Hold/wait are recorded as `no_order`. Unsupported signals, reviewer vetoes,
invalid/missing images or answers and stale/stopped decisions are recorded as
skips without an order.

## Fill rules, Stop and deduplication

Orders use the existing simulator's next eligible newly received regular-session
quote, never the PNG close or a browser-supplied price. Immediately before fill,
the same transaction rechecks approval/run state, current cash/shares, decision
age and whether it was already handled. Decision age must be between0 and120
seconds after candle end; source quote age must be at most30 seconds at actual
processing time. Queued orders expire instead of filling after that deadline.
Fees stay zero; manual orders retain their existing rules. FIFO manual orders
can consume resources first; automation then rejects insufficient cash/shares.

`automation_attempts` has a durable unique key of account/strategy/symbol/interval/
candle. The strategy ID includes both SMA windows. Claims, repeat Analyze calls
and repeated Apply calls cannot create another analysis or fill for that key.
Starting another configuration revokes the older run for the account/symbol.
One active controller is supported; another Start replaces the old run. There
is no retry of a failed analysis for the same candle. A restart preserves the
key and audit outcome, so starting again cannot reprocess it.

The simulator commits its receipt cursor, order/fill, cash/position, fill-linked
P&L and the attempt's decision/order/fill link in one transaction. If P&L insertion
fails, the whole fill/application rolls back and the ordinary receipt recovery
can retry it. Stop's cancellation and fill transactions serialize in SQLite:
a fill committed before Stop is retained; no new fill can commit after Stop's
acknowledged disable. Independent completed-candle P&L marks retain their normal
behavior and may change while balances are unchanged.

## API and storage

- `GET /api/paper/automation?run_id=...`: run, up to50 account attempts, saved
  decision results, current account/orders/fills/P&L. Omit run_id for the latest.
- `POST /api/paper/automation/start`: account_id=live, symbol, interval,
  short_window, long_window. Backend chooses isolated test routing if needed.
- `POST /api/paper/automation/{run_id}/stop`: revoke and cancel.
- `POST /api/paper/automation/claim`: run_id/candle_timestamp; returns the one
  attempt and snapshot, or claimed=false for an existing candle key.
- `POST /api/paper/automation/attempts/{id}/analyze`: capture (same PNG/manifest
  format as manual analysis) or capture_error. At most one analysis per claim;
  saves the result and attempts application only for that enabled run.
- `POST /api/paper/automation/attempts/{id}/apply`: idempotently return/apply its
  already linked decision. It cannot attach a manual/arbitrary decision ID.
- `GET /api/decisions/{id}` now also includes an application link/status when
  that decision belongs to automation.

Three additive tables in the existing state database: automation_accounts,
automation_runs and automation_attempts. Existing paper/decision tables and
historical data remain intact. The snapshot schema permits explicit test-mode
accounts; inactive replay accounts remain prohibited.

## Verification

```bash
PYTHONPATH=backend/.packages /usr/bin/python -m unittest backend.test_automation -v
PYTHONPATH=backend/.packages /usr/bin/python -m scripts.automation_smoke --output /tmp/arbitrade-automation-results
```

The controlled browser test clicks Start, completes a recorded up crossover,
automatically captures a decodable fresh PNG and compares provider/saved bytes.
It applies the same approved decision twice, delivers the next quote at20,
and observes exactly one buy4 fill: **cash1000→920, shares0→4**, fill P&L0.
A subsequent reviewer veto leaves balances/fill count unchanged. Stop and an
actual backend restart retain those values and deduplicate the original candle.
SQLite joins verify decision/fill/P&L linkage and the other account's unchanged
cash/shares. Services/browser/test databases are cleaned up. Unit tests also
cover Stop during a pending reply, pending-order cancellation before restart
catch-up, unavailable images/manual question isolation, expiry, stale quotes,
FIFO resource rechecks, close/wait and atomic rollback.

Observed final tests/build/browser results are in [verification.md](verification.md)
and screenshots/automation-2026-11-11/report.json. **Provider responses for this
feature's execution checks were mocked**, with constructed recorded prices. No
new live model request or live-account automation trade was made. The review
backend retains Yahoo ON and automation stopped; actual unattended/live-model
execution is not claimed as verified.
