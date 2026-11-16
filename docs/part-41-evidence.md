# Part 4.1 evidence trace

## Fresh live Yahoo check — November 16

Ran `ARBITRADE_BACKEND_PORT=18241 ARBITRADE_FRONTEND_PORT=15441 PYTHONPATH=backend/.packages /usr/bin/python -m scripts.ui_smoke --live --require-volume --output /tmp/arbitrade-live-volume-95`.
The new Yahoo subscription supplied 44 real observations to disposable SQLite.
No fixture quotes were injected. The test waited for a usable preceding-minute
baseline, froze the receiver for exact comparisons, and verified visible chart
values plus all timeframes, advancing age, and disconnected upstream with the
FastAPI chart WebSocket still open. Services/browser/temp database were cleaned.

| Node | Verified live value |
| --- | --- |
| Observation 43 / receipt 43 in test database | Source 15:40:59 UTC; cumulative volume 9,852,459 |
| Observation 44 / receipt 44 in test database | Source 15:41:00 UTC; cumulative volume 9,853,489; price 354.385 |
| Independent difference | 9,853,489 − 9,852,459 = 1,030 shares |
| WebSocket and visible 15:41 UTC candle | O/H/L/C 354.385; volume 1,030; Still forming |

The original receipt times are15:41:00.618083 and15:41:01.764874 UTC. See
[live chart/inspector screenshot](evidence/live-volume-2026-11-16/initial.png),
[disconnect screenshot](evidence/live-volume-2026-11-16/disconnected-desktop.png),
[independent trace](evidence/live-volume-2026-11-16/volume-trace.json), and
[full test report with stored observations and backend frames](evidence/live-volume-2026-11-16/report.json).
The screenshots show disconnected because the receiver was deliberately stopped
after capturing fresh data, making the chart comparison stable and testing
feed loss. IDs43/44 belong to that isolated database, not the user's production
database. Volume describes the stream's observed cumulative change, not a
complete minute of exchange trades.

## Verified observed volume — November 16

The recorded-volume SmokeTest now traces actual saved Yahoo records through
independent SQL, HTTP, the browser's received WebSocket snapshot, and the
current chart. It uses a frozen November 16 clock and a disposable database
loaded from the [177 original observations and receipts](evidence/volume-2026-11-16/source-observations.json).
It makes no new Yahoo request and does not write the production database.

| Node | Verified value |
| --- | --- |
| Baseline observation 62387 / receipt 62795 | Source 15:16:59 UTC; day volume 8,535,291 |
| Final observation 62453 / receipt 62861 | Source 15:17:59 UTC; day volume 8,602,961; price 354.04 |
| Independent SQL difference | 8,602,961 − 8,535,291 = 67,670 shares |
| HTTP and WebSocket 15:17 UTC candle | O/H/L/C 354.065 / 354.15 / 353.86 / 354.04; volume 67,670 |
| Visible chart inspector | Same OHLC, 67,670 shares, Ended; observed cumulative-change basis visible |

See the [chart screenshot](evidence/volume-2026-11-16/recorded-volume-chart.png),
[actual database-query HTTP response screenshot](evidence/volume-2026-11-16/database-query-response.png),
[counter/SQL/WebSocket trace](evidence/volume-2026-11-16/volume-trace.json), and
[browser result](evidence/volume-2026-11-16/report.json). The response screenshot
is not DB Browser. The feed is disabled during this deterministic check; these
are real recorded observations, not a fresh live-source demonstration.

Repeat with existing dependencies:

```bash
PYTHONPATH=backend/.packages /usr/bin/python -m scripts.recorded_volume_smoke
```

Root cause: multiple received updates shared the same Yahoo source timestamp,
while their cumulative totals increased. Rejecting all such ties suppressed
every saved minute's volume. The corrected rules allow nondecreasing counters
in first-receipt order and retain null for missing data, resets/decreases,
invalid/decreasing tied baselines and gaps. Price-order ambiguity is separate.
The full saved database now has 864 computable observed-volume minutes out of
2,770 minute buckets; the earlier zero-volume result describes the old rules.

This verifies the observed change in the stream's cumulative counter, not
exchange trade-tape completeness or equality to Yahoo downloaded minute bars.
For example, the saved 15:13 UTC counter delta was 44,397 versus a downloaded
bar's 44,296. The application labels the measurement and never adds it to the
downloaded bar volume. The [upstream protocol schema](https://github.com/ranaroussi/yfinance/blob/main/yfinance/pricing.proto)
defines time and volume fields but does not establish tie/correction ordering;
the counter-order policy is an explicit application assumption supported by
the recorded observations and tested guards.

## Actual Yahoo example

The [November 11 browser/backend report](screenshots/live-check-2026-11-11/report.json)
records an actual Yahoo AAPL update, without injected test observations. The
backend candle close changed from 353.355 to **353.3325**. The visible inspector
matched that change, and the feed reported live with source age of one second.
The [full-page screenshot](screenshots/live-check-2026-11-11/live-page.png)
shows the source time, status, candle and inspector. The [chart screenshot](screenshots/live-check-2026-11-11/live-candles.png)
provides another view. These show the earlier UI, not the current styling.

On November 16, a new standard-library SQLite read-only query independently
confirmed the recorded example in backend/data/observations.sqlite3:

| Node | Observed value |
| --- | --- |
| Stored Yahoo observation | ID 197, ticker AAPL, price 353.3325 |
| Source time | 2026-11-11T14:45:07+00:00 |
| Receipt | ID 201, 2026-11-11T14:45:08.304419+00:00 |
| Previously captured backend candle | 2026-11-11T14:45:00Z, close 353.3325 |
| Previously captured visible inspector | 14:45 UTC, close 353.3325, Still forming |

This confirms the stored row still matches the prior captured backend/UI
evidence. It is not a fresh live-stream/browser check. Volume was null in that
example. The screenshot and report do not establish actual live volume accuracy.

## DB Browser capture still required

Computer-use inventory exposed no apps or browsers. DB Browser installation was
approved, but `omarchy pkg add sqlitebrowser` requires the student's sudo
password on Omarchy; the agent could not complete authentication. A pkexec
attempt also lacked an authentication agent. No DB Browser screenshot has been
captured. The November 16 automated SQL/HTTP/WebSocket/chart screenshots above
provide the completed alternate verification path.

Open the observation database read-only in DB Browser and run:

```sql
SELECT o.id AS observation_id, o.provider, o.ticker,
       o.source_time_utc,
       json_extract(o.payload_json, '$.price') AS price,
       r.id AS receipt_id, r.received_at_utc
FROM observations AS o
JOIN receipts AS r ON r.observation_id = o.id
WHERE o.id = 197
ORDER BY r.id;
```

Capture the result and compare the IDs, times and price with the evidence above.
For a fresh complete trace, capture a new actual Yahoo event, its backend frame,
its matching SQLite row in DB Browser, and the same candle in the current UI.
Verify each value before adding screenshots and removing the report placeholder.
Do not substitute a synthetic table image for a DB Browser screenshot.

## Controlled checks

The [constructed dashboard report](screenshots/ui-smoke-2026-11-10/report.json)
and [disconnect screenshot](screenshots/ui-smoke-2026-11-10/disconnected-desktop.png)
cover known OHLCV and upstream outage behavior. The
[constructed replay report](screenshots/replay-constructed-2026-11-10/report.json)
covers late revisions, repeats and unchanged database counts. These are explicitly
constructed tests, not independent observations of Yahoo corrections or outages.

The November 15 readiness review reran 45 focused backend tests, the frontend
build and a constructed Chromium dashboard SmokeTest successfully. See the
[verification log](verification.md) for commands, failures and limitations.
