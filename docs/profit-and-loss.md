# Realized and unrealized paper P&L

The paper panel includes **Profit and loss · USD** and an append-only **P&L
history** table. Each row shows account/symbol event context, event time,
valuation price, its source and price time, cash, shares, weighted average cost,
cumulative realized P&L, unrealized P&L and their total. Earlier rows stay visible
when a new price arrives and after the position closes. On mobile, the history
table scrolls horizontally.

## Cost and P&L rules

For quantity Q and remaining purchase cost B:

- A buy of q shares at p adds q×p to B and q to Q. Average cost is B/Q, weighted
  by quantities rather than averaging fill prices equally.
- A sale realizes q×(p−B/Q). Remaining cost becomes B−q×(B/Q), so a partial sale
  retains the same per-share average. When flat, remaining cost is zero and
  average cost is not applicable; cumulative realized profit is retained.
- An open position valued at v has unrealized P&L Q×v−B.
- Total P&L is cumulative realized plus unrealized. After closing, unrealized
  is zero and total equals realized. Fees remain zero, as in paper execution.

Cost and realized/unrealized arithmetic use exact Fraction values so recurring
average costs do not accumulate rounding error. SQLite retains those exact
fractions plus readable USD amount strings (up to 40 significant digits).
Vue formats dollar displays to two fractional digits. Cash still uses the
existing Decimal paper-execution balances. An open valuation with no usable
price has NULL unrealized/total, displayed as **Unavailable**, never zero.
Known realized profit remains visible in that case.

## Events, prices and timing

A fill records its P&L row in the **same transaction** as the fill, account,
position, order status and receipt cursor. Its event key is the stable fill ID;
its valuation is the fill price. Event time is simulated execution/receipt time;
price time is the original quote source time. The row links directly to fill ID
and therefore its order and observed market data.

Open positions also receive marks from **completed regular-session 1m candle
closes**, independent of the timeframe selected for chart viewing. The canonical
1m interval avoids duplicate/inconsistent accounting from different viewers.
An ended interval can have partial recorded coverage; its available close is
used and no missing data is backfilled. Forming candles create no valuation row.

Candle marks carry candle start, interval end as price time, availability/event
time, receipt boundary, exact price and source “Completed 1m candle close”. A new
completed candle is a new valuation event even when its price equals a previous
bar. A changed close on the latest valued candle appends a new revision row,
retaining the earlier row. Reprocessing the same version/event is idempotent;
older receipt snapshots cannot rewind the newer valuation. Bars older than the
latest marked bar cannot replace the current price. Bars ending at/before the
latest fill do not retrospectively mark the current holding with an old price.

On each new receipt the engine first values the prior holding using any bars
newly complete/available at that point, then executes pending fills. The fill
row then records the resulting holding at its execution price. Clock-only
completion is discovered by the live account's periodic dashboard reads (or
next receiver/account catch-up), so a forming bar can finish without another
quote. Price time stays the candle's actual end even if discovery is later.

Live catch-up derives candles using both availability time **and receipt ID**,
including when two receipts share a timestamp. Replay uses only its in-memory
revealed observations and its recorded clock. A replay refresh cannot advance
accounting. Future stored observations, late revisions not yet received, and
chart sample CSV values cannot be used for paper P&L. Flat accounts receive no
candle marks, while their prior history and final realized total remain intact.

## Storage, migration and API

The existing mutable `chart-config.sqlite3` holds two added tables:

- `paper_pnl_state`: exact remaining purchase cost/realized profit and shares per
  account/symbol, latest fill time, and durable candle deduplication state.
- `paper_pnl_history`: stable event key and type, account/symbol, event and price
  timestamps/source/price, cash/shares/average cost, readable realized/unrealized/
  total amounts and exact arithmetic values, optional fill/candle/receipt links.

A unique (account, symbol, event key) constraint and unique fill ID prevent
repeated processing from inserting another row. Transactions serialize state
and event updates. No P&L data is written into immutable market observations.

On startup, older saved fills without P&L rows are backfilled in fill-ID order
once, reconstructing their cash and weighted cost from $1,000 and the zero-fee
fill ledger. Existing balances, orders and fills are preserved. Historical
candle marks before this feature are **not invented**; prospective completed
marks use the available current state and receipt boundary.

`GET /api/paper/account` and paper action responses now include `pnl_history`
and `pnl_summary` in the existing state envelope. Exact fields support audit;
readable amount fields are strings or NULL for unavailable values. No price,
cost basis or P&L value is accepted from the browser. Existing live/replay
account isolation and request-idempotency rules remain unchanged.

## Checked zero-fee example

| Event | Cash | Shares | Realized | Unrealized | Total |
| --- | ---: | ---: | ---: | ---: | ---: |
| Buy 4 @ $100 | $600 | 4 | $0 | $0 | $0 |
| Completed candle @ $110 | $600 | 4 | $0 | $40 | $40 |
| Sell 1 @ $110 | $710 | 3 | $10 | $30 | $40 |
| Completed candle @ $95 | $710 | 3 | $10 | -$15 | -$5 |
| Close 3 @ $105 | $1,025 | 0 | $25 | $0 | $25 |

All five browser rows matched direct SQLite queries before and after an actual
backend restart. Average cost stayed $100 through the partial sale. Repeated
reads and request retry preserved exactly five P&L rows and three fills. Closed
position rows remain visible. Source/time labels and open loss were visually
reviewed in screenshots.

Repeat the UI SmokeTest without source edits:

```bash
PYTHONPATH=backend/.packages /usr/bin/python -m scripts.pnl_smoke --output /tmp/arbitrade-pnl-results
```

It starts isolated feed-off FastAPI/Vite on 18000/15173 and Chromium, creates
separate disposable market/state SQLite files, uses a labeled controlled clock
for the reference and submits trades through Vue. Quotes are revealed before
candle-completion advances; forming candles are checked not to mark. It compares
all visible rows to direct SQL, retries, restarts the actual backend, refreshes
and compares identical saved row IDs/sources/amounts, then cleans up browser,
services, both databases and clock. Production has no fixture/injection endpoint.

[History after restart](screenshots/pnl-2026-11-11/history-after-restart.png),
[open -$5 loss](screenshots/pnl-2026-11-11/open-loss.png),
[SQL/phase report](screenshots/pnl-2026-11-11/report.json),
[verification and remaining checks](verification.md). Evidence uses constructed
prices, not newly arriving Yahoo data. Backend tests also cover fractional
weighted costs, missing valuation, revision/reprocessing behavior, fill/P&L
rollback, legacy fill migration and replay visibility. Large-history query
performance, pagination/retention and fresh live provider verification remain
future work.
