# Arbitrade

A local trading workstation with a Vue frontend, a Python/FastAPI backend, and SQLite market and simulation records. The chart, indicators, AI analysis, and simulated account share the same candle context. [Assignment 4 description](docs/assignment-4.md).

## Demonstration

[Watch or download the Assignment 4.1 demo](demos/Assignment%204.1%20Demo.mov)
(QuickTime `.mov`, about 72.4 MiB). The submission report is maintained locally
as `report.md` and excluded from Git.

## Around the desk

Click the Arbitrade logo to return to the chart home view.

- **Chart** opens with AAPL candlesticks and volume. Hover for OHLC and reported volume, or pin a candle by clicking it or choosing **Inspect candle**. **Follow latest** returns to the most recent candle. Source, age and feed status sit beneath the plot. **Feed details** contains the connection check and source timestamps.
- **Indicators** in the emerald sidebar has a **Moving Averages** grid for SMA and EMA. Toggle 10, 20, 30, 50, 100 or 200 candles independently for 1m, 5m, 15m, 1hr, 1D and 1W. All EMA lines are orange and all SMA lines are blue, including custom averages, Signals and saved chart images. Selections stay on the chart when its timeframe changes. Lines start once the source interval has enough completed candles. Selected buttons have a checkmark and a border matching the chart line. Expand **Rolling price range & custom indicators** to add a named indicator or edit its window. Selections are saved per symbol.
- **Signals**, the second sidebar tab, shows confirmed SMA crossovers newest first. Choose one to bring its candle into view and inspect both averages. **Crossover windows** sets the strategy pair, initially 20 and 50.
- **Drawing Tools**, the pencil between Signals and AI, has separate icon rows for Trend Line, Freehand and Eraser. Select a drawing tool and drag on the price chart. Select 1:2, 1:3, or 1:4, then drag between opposite corners on the price chart to size the box. Drag the filled box to move it. The upper and lower handles resize both zones at the selected ratio, and the side handle changes width. Select Eraser and sweep across a drawing to remove it. Command-Z on Mac or Ctrl-Z on Windows and Linux undoes the latest drawing, move, resize, or erasure. Drawings stay with their symbol, timeframe, and mode until page reload.
- **AI**, the blue diamond in the sidebar, opens the AI summary and voice chat. The summary shows observed candle evidence. **Decision API** captures the visible chart and asks for **long**, **short**, or **wait** using only the PNG and identifying context. The choice and data quality appear first; audit metadata stays under Decision details. Captures are saved without an on-page screenshot. **Review paper proposal** opens the separate position-aware workflow used by paper automation. **Voice chat** discusses those saved paper decisions.
- **Trade**, the emerald button at the top right, toggles an inset parchment paper account card with a maroon top rule. Closing it expands the desktop chart. **Orders** contains manual orders, fills, and profit and loss. **Automation** contains the bot controls and its decision history. While automation runs, **Stop automation** is also available in the header.

The main chart is 20% taller across desktop and phone layouts. Timeframe controls
sit directly below the instrument heading; the separate last-price/change row is removed.

Scroll over the green sidebar to move through its controls while the tab bar stays in place. Use the chevron to collapse or expand the sidebar. Moving between Indicators and AI slides past Signals and Drawing Tools in either direction. The sidebar, its tabs, and Trade slide into place and honor the device’s reduced-motion setting. On phones the sidebar starts collapsed and Trade opens a drawer beneath the header. [AI and paper trading](docs/screenshots/chart-trade/ai-and-paper.png) · [Expanded chart](docs/screenshots/chart-trade/expanded-chart.png).

## Run

Use the existing `/usr/bin/python` environment and approved local packages:

```bash
PYTHONPATH=backend/.packages /usr/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```bash
npm --prefix frontend run dev
```

Open [the dashboard](http://127.0.0.1:5173). Stop both commands with Ctrl+C. Run one backend
worker: its lifespan owns one shared AAPL Yahoo subscription, continuously
records quotes and closes the feed on shutdown. Multiple browser connections
share that subscription. Independent backend workers would each subscribe.
No authentication or credentials are used for Yahoo quotes.

The live subscription is AAPL. The chart defaults to one minute and supports
1m, 5m, 15m, 30m, 1hr, daily, weekly and monthly candles. Switching
opens a new WebSocket with matching stored history, followed by backend-derived
updates. The page displays the source, latest source timestamp and age,
upstream feed status separately from the browser connection, and forming/ended
and coverage labels for the inspected candle. Unavailable volume is omitted from candle details and hover cards, with a gap
in the histogram; it is never replaced by zero.

Volume from saved streaming quotes is the observed change in Yahoo's cumulative
day counter. Increasing updates sharing a source timestamp are accepted in
receipt order; resets, decreases and missing baselines remain unavailable.
Candle details identify this basis. Downloaded Yahoo bar volume is a separate
measurement; when fresh quotes revise a cached intraday bar, the observed delta
replaces its volume without adding the two. See [volume evidence](docs/part-41-evidence.md).

Reproduce the saved real-Yahoo SQL → HTTP/WebSocket → chart volume check:

```bash
PYTHONPATH=backend/.packages /usr/bin/python -m scripts.recorded_volume_smoke
```

It loads the included 177-observation capture into a disposable database,
starts isolated services and Chromium, checks the visible 67,670-share delta,
saves evidence, and cleans up. It makes no new Yahoo request and does not write
the saved observation database.

For a new Yahoo check during a regular AAPL session, use
`ARBITRADE_BACKEND_PORT=18241 ARBITRADE_FRONTEND_PORT=15441 PYTHONPATH=backend/.packages /usr/bin/python -m scripts.ui_smoke --live --require-volume`.
It waits up to 90 seconds for a computable observed volume and freezes reception
for exact database/chart comparisons, then checks upstream disconnection and
cleans up. The November 16 run verified price354.385 and observed volume1,030.

Drag the chart right to look back, or use **Previous day** and **Go to date · UTC**
above the plot. Vertical trackpad scrolling and trackpad pinch zoom the horizontal
candle spacing with an amplified, pointer-centered response; horizontal swipes pan.
Quick zooms and swipes continue after release with a moderate, gradual slowdown,
and mouse/touch dragging has momentum too. A new gesture or date/latest navigation
interrupts the release motion. Drag the right-hand price labels up or down
to expand or compress candles vertically; scrolling over those labels also scales
vertically. Double-click the labels to restore automatic price scaling.
The volume shares axis expands and compresses from zero at the bottom of its
pane when scrolling or dragging; double-click restores automatic volume scaling.
The shared right axis reserves label space so volume scaling keeps bars in the
same horizontal position as the labels change.
**Latest candles** returns to the live end. Live updates preserve
an earlier viewport. The date picker lists loaded candle dates (period start
dates for weekly/monthly bars); replay exposes only dates revealed so far.
Live AAPL charts use a rolling three-calendar-month window. Hourly bars come
from Yahoo. Daily bars also supply the weekly and monthly charts, whose first
and last periods can be partial. The five intraday charts use unadjusted Yahoo
bars at their native resolution. Yahoo supplies a shorter initial archive for
1m and 5m–30m. Refreshes retain
older intraday bars within the window. Use **Go to date** to inspect older
intraday candles. Replay and paper execution use recorded observations.

Refresh all local chart caches with
`PYTHONPATH=backend/.packages /usr/bin/python -m scripts.backfill_history`.
The command prints actual counts and first/last timestamps for every frame.
The live chart refreshes its active cache every five minutes and retries a failed
download after one minute. Repeat the isolated all-timeframe browser check with
`PYTHONPATH=backend/.packages /usr/bin/python -m scripts.provider_history_smoke`.
It uses constructed provider data, starts local services, verifies chart/date
selection and outage behavior in Chromium, checks the cache, and cleans up.
Repeat the isolated history UI check with
`PYTHONPATH=backend/.packages /usr/bin/python -m scripts.history_smoke`.

Only regular NASDAQ-session candles are charted. Extended-session quotes remain
stored but are excluded by the existing calendar aggregation. A connected feed
can be stale; no matching quote in 30 source-time seconds marks it stale.
Recorded streaming observations are not backfilled; gaps in those records stay gaps.
Downloaded chart history uses the separate provider cache described above. Daily volume can remain unknown if an
available minute lacks a valid cumulative-volume baseline.

Default database: `backend/data/observations.sqlite3`. Set
`ARBITRADE_DATABASE=/absolute/path/observations.sqlite3` to use another file
for both the live receiver and HTTP observation history. Automated fixture checks use disposable databases. A separately labeled live
decision check saves its snapshot/result in the state database without placing
trades. Prior observations are retained.

## Replay saved observations

Choose **Replay**, select the saved symbol and inclusive receipt-time range,
then **Load / restart replay** and **Next observation** or **Play replay**.
The chart shows Replay, progress, original source time and receipt time.
Saved replay ranges and voice decisions retry automatically after temporary
connection failures. Voice becomes available when a saved decision has loaded;
replay begins empty until **Next observation** or **Play replay** advances it.
Selections preserve arrival order and corrections without writing saved data.
Start the backend with `ARBITRADE_LIVE_FEED=off` to disconnect Yahoo.

```bash
ARBITRADE_LIVE_FEED=off PYTHONPATH=backend/.packages /usr/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
PYTHONPATH=backend/.packages /usr/bin/python -m scripts.replay_smoke --output /tmp/arbitrade-replay-results
```

The replay SmokeTest starts and cleans up isolated feed-off services on
18000/15173 and uses real Chromium. Actual saved AAPL close **348.58** and
Unknown volume matched twice; recorded counts stayed unchanged. A separate
`--constructed` run verifies close **103**, volume **11**, late correction and
repeat handling. The replay feature passed 44 backend tests and the frontend build when added.
[Replay behavior, API, test data and limits](docs/replay.md).

## Moving averages

In **Signals → Crossover windows**, choose positive whole numbers for the short and long SMA windows,
with short smaller than long, then click **Apply SMA windows**. Defaults are
20/50; applying changes restarts a replay. Python calculates both lines from
ended candle closes. Warm-up and forming candles show Unavailable. Ties retain
the previous side; confirmed changes produce arrows and an accessible crossover
list. Vue draws the results. The existing coverage label remains separate from
whether an interval has ended.

The 2/3 hand reference passes in batch and step-by-step browser replay: upward
at **16/13**, downward at **4/9**; a forming candle produces no confirmed signal.
The SMA feature passed 48 backend tests, the frontend build and its UI SmokeTest when added.

```bash
PYTHONPATH=backend/.packages /usr/bin/python -m scripts.sma_smoke --output /tmp/arbitrade-sma-results
```

This uses isolated services on 18000/15173 and a labeled disposable test database.
[Calculation rules, API and reference table](docs/moving-averages.md).

## Named chart indicators

Open **Indicators → Rolling price range & custom indicators** to choose a type, name an instance and set its window.
SMA, EMA and rolling price range share a Python calculation interface. Each instance
keeps its own settings in `backend/data/chart-config.sqlite3`, separately from
recorded observations, and returns when the same symbol/timeframe is reopened.
`ARBITRADE_CONFIG_DATABASE` selects another settings file. Inspect values for
the selected candle; warm-up/forming candles remain Unavailable. Range lines
use a separate pane, with values in quote-price difference units.

The API supplies type/settings metadata to Vue. The constructed browser check
passed: **Range 2 = 5**, **Range 3 = 6** at the third candle; refresh restored
both, and zero-window validation kept the valid instances. The named-indicator feature passed 52 backend tests, the frontend build and its UI SmokeTest when added. The existing
SMA crossover browser regression also passes.

```bash
PYTHONPATH=backend/.packages /usr/bin/python -m scripts.indicator_smoke --output /tmp/arbitrade-indicator-results
```

[Indicator inputs, units, extension contract, persistence and API](docs/chart-indicators.md).

## Paper trading

Open **Trade** in the upper right and choose **Orders** for cash, shares and order
history. Buy whole shares, sell part, or close the position. Hold/wait create no
orders. Starting cash is **$1,000**; fees are zero. A valid order remains pending
until the next eligible new regular-session observed price arrives. Cash/shares
are rechecked at execution; order, fill and account changes commit atomically.
**Retry last request** reuses its stable ID and cannot duplicate the order/fill.

Paper accounts reuse the existing `backend/data/chart-config.sqlite3`, separate
from recorded market data. The live account survives restart. Each replay
connection has a separate account and can execute only on newly revealed
observations; restarting replay creates a new $1,000 account. Live orders wait
when Yahoo is disabled.

```bash
PYTHONPATH=backend/.packages /usr/bin/python -m scripts.paper_smoke --output /tmp/arbitrade-paper-results
```

Browser/SQLite check passed: buy 4 at $100 → **$600 / 4**, sell 1 at $110 →
**$710 / 3**, close at $105 → **$1,025 / 0**. Retry added no duplicate; empty sale
was rejected; exactly **3 fills** survived an actual backend restart. The initial paper feature passed 59 backend tests and the frontend build when added. [Fill rules, API, persistence and test
command](docs/paper-trading.md).

## Profit and loss

The paper panel now retains a **P&L history** table with weighted average cost,
cumulative realized profit, unrealized profit and their total. Fill events and
completed **1m** candle marks show the price/time/source used. Partial sales keep
the remaining average cost; closed positions retain realized profit and earlier
rows. Missing open valuation displays Unavailable. Reprocessing events or
restarting the backend preserves single entries. Existing fills are backfilled
once without changing balances or inventing historical candle marks.

```bash
PYTHONPATH=backend/.packages /usr/bin/python -m scripts.pnl_smoke --output /tmp/arbitrade-pnl-results
```

Browser/SQLite reference matched before and after backend restart: total P&L
**$0 → $40 → $40 → -$5 → $25**, with $1,025 cash and no shares after close.
All **65 backend tests** and frontend build pass.
[Cost rules, event timing, storage and checked table](docs/profit-and-loss.md).

## Verification

Current offline workstation SmokeTest (free ports 18000/15173):

```bash
./scripts/smoke-test
```

Starts FastAPI/Vue and real Chromium, opens recorded replay, adds/edits an SMA,
checks chart PNG questions plus provider failure, then runs reviewed paper
buy4@100/sell1@110/close3@105. Expected UI and independent SQLite result:
**cash1,025 / shares0 / realized25 / unrealized0**. Vetoes, duplicates and Stop
must not add orders/fills. New temporary databases each run; services/browser
cleaned on success/failure. Local existing tools only, no credentials or installs.
[Command, evidence and hosted workflow prerequisites](docs/workstation-smoke-test.md).
The push workflow uses the same SmokeTest. See the verification log for local results and evidence from separate Yahoo, model and audio checks.

```bash
PYTHONPATH=backend/.packages /usr/bin/python -m unittest discover -s backend -v
npm --prefix frontend run build
/usr/bin/python scripts/smoke_test.py --http-only
PYTHONPATH=backend/.packages /usr/bin/python -m scripts.verify_live --recorded
PYTHONPATH=backend/.packages /usr/bin/python -m scripts.verify_live
```

Earlier live-feature verification on November 10, 2026: 43 backend tests and the frontend build passed.
HTTP and recorded/actual WebSocket transport checks passed earlier. Automated
**UI SmokeTest now passes using Playwright and Chromium on Omarchy**: connection
button, matching OHLCV, same-minute replacement, rollover, the five original timeframes,
forming/ended labels, source age and separate feed/transport status. Desktop
and mobile screenshots were inspected. A visual viewport issue found during
that inspection was fixed: the first streamed candles now fit an initially
empty chart and new intervals remain visible while following the latest bar.

The current UI SmokeTest exercises all eight timeframes. It uses free ports 8000/5173 by default. Set `ARBITRADE_BACKEND_PORT` and `ARBITRADE_FRONTEND_PORT` to use other local ports.

```bash
PYTHONPATH=backend/.packages /usr/bin/python -m scripts.ui_smoke --output /tmp/arbitrade-ui-results
```

This starts FastAPI and Vite, launches the installed `/usr/bin/chromium` with
Playwright, performs user operations on the real Vue page, checks visible values
against disposable SQLite data and stops all test services/browser. The default
input is explicitly labeled **CONSTRUCTED replay**, with a fixed replay time
for forming/ended checks. It writes screenshots and report.json, including
stored observations, receipts and backend snapshots. It does not require the
Codex integrated browser or an extension. The approved dev dependency is
playwright-core 1.65.0 in frontend/node_modules; existing Chromium worked, with
no browser download, sudo or system packages needed.

[Desktop screenshot](docs/screenshots/ui-smoke-2026-11-10/disconnected-desktop.png),
[mobile screenshot](docs/screenshots/ui-smoke-2026-11-10/mobile.png),
[daily screenshot](docs/screenshots/ui-smoke-2026-11-10/timeframe-1d.png),
[detailed UI report](docs/screenshots/ui-smoke-2026-11-10/report.json).

Attempt actual Yahoo input with `--live`. The November 10 evening attempt
received an actual after-hours AAPL quote, displayed the connected chart,
source timestamp/age and waiting message, and reported **PENDING** because
regular-session rules excluded that quote. On November 11 the actual in-session
candle-to-screen comparison **passed** after re-enabling Yahoo: saved quotes,
backend frames and changing visible OHLC agreed. That check used an enabled Yahoo feed.
[Actual live report](docs/screenshots/live-check-2026-11-11/report.json). Read report.json's result field: a completed live attempt may report
PENDING rather than PASS. Its page is captured in
[the live pending screenshot](docs/screenshots/ui-live-2026-11-10/pending-live.png).

The older manual command remains available:

```bash
PYTHONPATH=backend/.packages /usr/bin/python -m scripts.verify_live --recorded --browser
```

HTTP-only and non-browser transport checks are separate from UI SmokeTest.

Details, failures and pending checks: [docs/verification.md](docs/verification.md).
Protocol and limitations: [docs/live-updates.md](docs/live-updates.md).

## API and data rules

- `GET /api/health` returns `{"status":"ok"}` independently of feed health.
- `GET /api/history` preserves the three-row synthetic sample array by default.
- `GET /api/history?symbol=AAPL&timeframe=5m&source=observations&include_status=true`
  returns observation history plus external completion/coverage metadata.
- `WS /api/live?symbol=AAPL&timeframe=1m` sends stored observation history,
  changed candles and periodic upstream status. It never mixes sample and live data.

All candles retain exactly `timestamp,open,high,low,close,volume`. See
[docs/candle-rules.md](docs/candle-rules.md) for deduplication, explicit
corrections, cumulative-volume baselines and source ordering, and
[docs/higher-timeframes.md](docs/higher-timeframes.md) for session alignment,
calendar boundaries and receipt-aware replay.

Useful standalone commands:

```bash
/usr/bin/python -m backend.observations list
/usr/bin/python -m backend.candles --ticker AAPL
PYTHONPATH=backend/.packages /usr/bin/python -m backend.yahoo_stream --ticker AAPL --timeout 30
/usr/bin/python -m scripts.verify_recorder
```

The standalone Yahoo command remains bounded to one observation; the server
uses the continuous receiver. Recorder verification uses constructed data.

## Decision API: assignment chart reading

Click **Decision API** beside the chart. Vue captures the actual visible chart,
including its volume pane and displayed indicators. FastAPI sends only that PNG
and ticker, interval, capture/candle timestamps, visible-candle count, receipt/source
times, freshness and volume status to OpenAI. No candle arrays, numeric indicator
values, account balances, positions or calculated signals are sent as JSON.
The model chooses **long**, **short**, or **wait**. A forming candle or incomplete
indicator warm-up does not block this chart-reading exercise. Stale or unclear
context instructs the model to choose wait; an API error never becomes wait.

The image, context, question and answer are saved; optional probabilities are
available under **Decision details**. The panel shows the choice/status and a compact
freshness/volume line without a screenshot preview or image link. **How the Decision API
works** opens the educational flowchart. No paper order, analyst/reviewer cycle,
or automation attempt is created by this control.

Put `OPENAI_API_KEY=your_actual_key` in the project-root `.env` (beside `frontend/`
and `backend/`), using `.env.example` as a template, and restart FastAPI. Process
settings take precedence, then root `.env`, then legacy `backend/.env` fallback.
Both private locations are ignored by Git. Never put credentials in frontend code.

```bash
PYTHONPATH=backend/.packages /usr/bin/python -m scripts.classroom_smoke --output /tmp/arbitrade-classroom-results
```

This command starts disposable services, exercises Chromium, checks the actual
provider payload and stored capture/result, verifies unchanged paper records and
cleans up. It uses controlled responses and makes no live model request.
See [assignment implementation](docs/classroom-decisions.md).

## Review a paper decision proposal

Select a completed candle and open **Review paper proposal** in the summary. Choose **Freeze selected candle**, inspect its saved
chart/facts, then **Request model proposal**. Python calls OpenAI Decisions;
SQLite retains the snapshot and result. This operation does not submit a paper
order. Set `OPENAI_API_KEY=your_actual_key` in the project-root `.env` and restart the
backend; process environment takes precedence. Keep the key backend-only.
`.env.example` contains placeholders; legacy `backend/.env` remains a fallback. See [docs/decisions.md](docs/decisions.md)
for API, cutoff rules, statuses and configured whole-share order size.

```bash
PYTHONPATH=backend/.packages /usr/bin/python -m scripts.decision_smoke --output /tmp/arbitrade-decision-results
```

This repeatable browser check uses a controlled provider and constructed data,
compares saved decisions and unchanged paper tables, and cleans up its services.

## Ask about a chart image

In **Review paper proposal**, select a completed candle, click **Ask about chart**, and inspect the frozen PNG,
cutoff and questions. **Analyze captured chart** asks the model for action,
visual crossover and evidence sufficiency. Python compares its visual answer with
the calculated crossover; disagreements and unreadable evidence are ineligible
for execution. The PNG, questions and answers are saved together. Orders and
balances stay untouched. See [docs/chart-questions.md](docs/chart-questions.md).

```bash
PYTHONPATH=backend/.packages /usr/bin/python -m scripts.chart_smoke --output /tmp/arbitrade-chart-results
```

The controlled browser check is separate from the single live image check:
that actual model answered wait/none/sufficient while Python found down, and the
application flagged the conflict. Both checks and their evidence are recorded.

## Inspect analyst and reviewer

Every new analysis uses at most one analyst call and one separate reviewer call
on the same frozen snapshot (and PNG for chart questions). The result displays
both outputs/models, reviewer verdict and Python's final account/strategy checks.
A reviewer acceptance cannot permit an unaffordable purchase or unsupported
signal. Expand **Inspect role instructions and answers** for the saved details.
No paper order is sent. See [docs/agent-review.md](docs/agent-review.md).

```bash
PYTHONPATH=backend/.packages /usr/bin/python -m scripts.review_smoke --output /tmp/arbitrade-review-results
```

## Apply reviewed paper decisions

In **Trade → Automation**, **Start paper automation** analyzes each newly completed live-chart candle with
its own frozen PNG, analyst and reviewer. Approved decisions use the simulator's
next eligible quote and current-resource checks. **Stop paper automation** revokes
late replies and cancels pending automation orders. It starts disabled and stays
disabled after a backend restart. Keep the dashboard open; replay remains manual.

The automation audit links each signal and decision ID to its review, fill or skip,
and resulting cash/shares/P&L. Constructed data uses a separate test account.
Manual questions create no order. See [docs/paper-automation.md](docs/paper-automation.md)
for deduplication,120second age limit, fill rules and limitations.

```bash
PYTHONPATH=backend/.packages /usr/bin/python -m scripts.automation_smoke --output /tmp/arbitrade-automation-results
```

Verification used mocked provider replies and disposable recorded test prices:
reusing an approved buy produced exactly one fill,1000→920cash/0→4shares;
a reviewer veto and actual restart added no fill. Live automation was not enabled.

## Discuss a recorded decision by voice

Use **Voice chat** below the AI summary or **Discuss this decision** on a reviewed proposal. **Choose decision** opens the saved records. Inspect the selected
record and click **Start voice**. Allow microphone access, ask a question and a
follow-up, then **End voice**. This is a read-only conversation; it cannot trade
or change automation. The active/off microphone indicator and audio controls
show local capture and playback. See [docs/live-speech.md](docs/live-speech.md).

The Mac browser uses the Mac microphone and speakers even with the backend on
Omarchy. Open the localhost tunnel URL in Safari/Chrome; WebRTC audio connects
directly to OpenAI. No SSH audio forwarding is needed. The key stays on Omarchy.

```bash
PYTHONPATH=backend/.packages /usr/bin/python -m scripts.voice_smoke --output /tmp/arbitrade-voice-results
```

This browser check uses actual local WebRTC with mocked provider/captions and a
synthetic microphone. A separate live-provider synthetic-input session produced
correct audio/captions; the physical Mac microphone/speaker check is pending.

## Files and environment

`backend/live.py` owns feed lifecycle, recording and snapshot derivation;
`backend/yahoo_stream.py` reuses yfinance subscription and decoding;
`backend/main.py` supplies HTTP/WebSocket routes. `backend/history.py`,
`candles.py`, `timeframes.py` and `observations.py` provide data rules and storage.
`frontend/src/useMarketChart.js` owns the chart and socket lifecycle. `CandleChart.js` presents the chart, replay and inspection controls.
`chart-data.js` adapts UTC prices and nullable volume; `vite.config.js` proxies
both HTTP and WebSocket requests. `scripts/verify_live.py` checks transport;
`scripts/ui_smoke.py` and `ui_smoke.mjs` run the automated browser checks.
Major prompts are preserved under `prompts/`, including prompts 08, 08a and the approved 08b UI-testing request.
The [AI-use record](AI-USE.md) identifies the coding assistance used for the desk redesign.

Confirmed environment: Linux/Omarchy, Python 3.14.8 at `/usr/bin/python`,
FastAPI 0.156.8, Uvicorn 0.54.0, Node 26.13.0, npm 11.20.0, Vue 3.5.45,
Vite 8.3.7, Lightweight Charts 5.3.0, yfinance 1.8.0, websockets 17.4 and
exchange-calendars 4.13.2. Approved Python additions live in `backend/.packages`
with pins in `backend/requirements-yahoo.txt` and `requirements-calendar.txt`.
Approved playwright-core 1.65.0 was added to the frontend dev dependencies
and lockfile. No virtual environment was created. Follow `AGENTS.md` before installing or changing dependencies.

## Access from the Mac

With the Omarchy development servers running, forward Vite (including its API/WebSocket proxy):

```bash
ssh -fN -M -S /tmp/arbitrade-mac-tunnel.sock -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -L 127.0.0.1:5173:127.0.0.1:5173 omarchy
```

Open http://127.0.0.1:5173 in the Mac browser. Source stays on Omarchy.
Stop the tunnel with `ssh -S /tmp/arbitrade-mac-tunnel.sock -O exit omarchy`.
November 10: Mac Browser connection and all five timeframes passed using stored
observations. November 11: fresh live quote-to-screen passed in project Chromium
on Omarchy; the Mac tunnel was not reverified. Use the Run commands above to start services; process IDs and log paths are
session-specific. Yahoo is enabled by default unless `ARBITRADE_LIVE_FEED=off`.
Noninteractive SSH needs the existing Node runtime on PATH:
`export PATH=/home/jlrj/.local/share/mise/installs/node/26.13.0/bin:$PATH`.

The live chart initially requests up to 256 recent candles. Scroll toward the
left edge to load earlier candles. Matching browser connections share candle and
indicator calculations. Existing historical prices remain available during a
provider refresh, and the chart retains its loaded range during a reconnect.
