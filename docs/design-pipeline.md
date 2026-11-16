# Design pipeline

## Submission artifacts · November 16, 2026

The supplied [Assignment 4.1 demonstration](../demos/Assignment%204.1%20Demo.mov)
is preserved unchanged in `demos/` and linked from the README. The local
`report.md` links to the same video and is excluded from Git. The recording
is a supplied artifact; adding it does not constitute a fresh application check.

## Observed volume correction · November 16, 2026

Yahoo updates in the saved capture share source timestamps while cumulative day
volume increases. Minute formation now accepts nondecreasing totals in source
time/first-receipt order; price-order ambiguity remains independent. Missing
values, gaps, resets, decreases and invalid/decreasing tied baselines retain
null volume. No raw observation is replaced or assigned a guessed subsecond time.
History and replay label the result `volume_provenance=yahoo_quote_counter`;
Candle details explain that it is observed cumulative change. This does not claim
the stream is a complete trade tape or matches downloaded provider bar volume.
Intraday live overlays use this observed delta rather than dropping it or adding
it to cached provider volume. The recorded-volume SmokeTest independently queries
endpoint counters, compares HTTP and browser WebSocket candles, inspects the
visible chart, saves screenshots and cleans up. See [evidence](part-41-evidence.md).

## Current trading desk

Moving-average color identifies type: EMA orange (`#c87519`), SMA blue (`#307492`),
across all periods, intervals, custom averages, Signals, legends, selection borders
and frozen chart images. Existing EMA dashes and two-pixel line weights remain;
lookback-dependent styling is a proposal pending student choice.

The volume shares axis scales from zero for wheel input and pointer dragging.
Its bottom scale margin is zero, keeping the histogram baseline at the pane's
bottom during manual scaling and automatic reset. Price and other study axes
retain center-based scaling. `scripts.history_smoke` verifies rendered volume
bar heights and the fixed baseline alongside existing chart gestures.
The shared right axis reserves a 96px minimum width so changing volume tick
formats does not resize the plot and shift bars sideways. The history browser
check scrolls across numeric/K/M ranges in both directions and checks plot width.

Live chart snapshots use a three-calendar-month window anchored to the New York market date.
ProviderHistory serves native Yahoo 1m, 5m, 15m, 30m and 1h candles and aggregates daily
prices into exchange-aligned weekly and monthly periods. Shorter Yahoo archives accumulate
across refreshes in per-interval caches beside the observations database. The date picker includes the
earliest loaded period. D/W/M initially fit the full window. Replay and paper trading read recorded
observations. The repeatable backfill and browser checks are documented in the README.

The instrument heading leads straight into timeframe controls. Prompt67 removes
the separate latest-price label, value and candle-to-candle change row.

The header wordmark links home to the chart using existing in-app navigation, with keyboard activation and preserved chart state.

The main chart height is 20% taller: desktop `clamp(366px, 55.2vh, 588px)` and phone `clamp(306px, 46.8vh, 426px)`.

The default workspace pairs the chart with the Indicators menu. The AI diamond opens a summary of the selected candle. The summary compares its close (or latest price) with its own open, displays its UTC time, and distinguishes a forming interval and partial coverage. Hover inspects OHLC and available share volume without changing the selection. Clicking a candle, selecting its timestamp, or choosing a confirmed crossover pins the candle for review. AI summary and voice chat share the emerald rail on desktop and the expandable tool area above the chart on phones.

Chart history supports dragging, Previous day, a loaded-date picker in UTC, and Latest candles. Dates come from the current subscription's candles, preserving replay visibility. Weekly/monthly choices are period start dates. Live revisions and rollover retain the visible logical range when the reader is away from the tail. Live charts use the provider history described above. Trackpad vertical wheel and ctrl-wheel pinch use an amplified exponential change to the logical horizontal range, anchored under the pointer. Horizontal wheel swipes use the same range controller for panning. Main-chart zoom uses a 0.0088-per-pixel logarithmic coefficient and horizontal wheel pan uses a 0.8 multiplier, both 20% below prompt61; right-axis scaling retains its separate sensitivity. `chart-gestures.js` adds frame-driven exponential decay after wheel/pinch release, using zoom/pan decay times of 300/360ms and a 2.2-second safety limit; each new input replaces the previous release tail, including small OS momentum events. Mouse and touch drags use the library kinetic scrolling. Per-event limits and an eight-interval minimum bound zoom. New input, date jumps, pinned selections, Latest candles, reconnects, blur and unmount cancel custom momentum; animation frames and listeners are cleaned up. The right-hand price axis uses a more sensitive center-preserving vertical transform for pointer dragging and wheel input, through the public price-range API. Pointer capture keeps dragging responsive outside the axis; release/blur cancels the drag, and double-click restores auto scaling. Horizontal time range is preserved during price scaling.

The emerald sidebar has four keyboard-accessible icon tabs and a collapse button. Indicators toggles 10/20/30/50/100/200-period SMA and EMA overlays and exposes named SMA, EMA and rolling-range settings. Signals focuses the chart on the selected strategy's two SMAs. Its newest-first list, chart marker and evidence card share the pinned candle timestamp. Switching tabs preserves the replay position and restores the chosen overlays.

The chart uses eight exchange-session intervals. Python calculates EMA from an initial SMA and weights each subsequent completed close by `2 / (window + 1)`. Weekly and monthly bars aggregate scheduled sessions up to the first or last trading day of their period. The same calendar and receipt cutoff govern live/history, replay and frozen decisions. The existing chart configuration database stores explicit preset choices by symbol, timeframe, type and period.

The parchment header contains the wordmark, mode and an emerald Trade toggle. It opens an inset parchment paper account card with cream space above and below and a maroon top rule beside the chart, or as a drawer on smaller screens. Closing it restores the full desktop chart width. Orders holds orders and P&L, and Automation holds the controls and audit. The header provides a stop control throughout an active run. Indicators and Signals have panel headings, with smaller SMA and EMA subheadings under Indicators. Moving between Indicators and AI slides past Signals and Drawing Tools in either direction. The green sidebar scrolls independently with a pinned tab bar. The panes share a fixed top edge, and the outgoing pane retains its height until the slide ends. The green sidebar, tab changes, and Trade card use slide transitions that respect reduced motion. The AI tab uses the blue brand diamond. It presents observed prices and indicators immediately. Decision API captures the actual visible chart and requests long/short/wait using pixels and identifying context only. The summary prioritizes the choice/status and compact freshness/volume context; model metadata and saved context/question/answer are under Decision details. A short expandable flow explains the process. Images remain saved without a screenshot preview or image link. Review paper proposal opens the separate frozen-data, position-aware analyst/reviewer workflow; paper automation retains that workflow. Voice chat discusses saved paper decisions by ID. See [classroom contract](classroom-decisions.md).

`main.js` keeps the chart and tool components mounted as navigation changes. Inactive panels leave the tab order, and a mounted chart canvas can still produce the native PNG used by automation. Draft SMA inputs become active strategy windows when the user applies them. The source, upstream feed state and age stay visible under the plot. Detailed source timestamps, FastAPI transport and the health check are available in Feed details.

The [assignment](assignment-4.md) allows students to choose navigation. Part 4.1 is demonstrated through the chart, source status, recording, replay and outage evidence. The other panels expose existing later-stage work. Historical strategy backtesting with performance results and the final presentation are separate assignment deliverables.

Implemented flow as of prompt 08:

```text
Yahoo AsyncWebSocket.subscribe(AAPL), provider heartbeat and decoder
  -> continuous receiver owned by FastAPI lifespan (one shared connection)
  -> UTC receipt + describe_update -> ObservationStore.record -> SQLite commit
  -> history_response(source=observations, symbol=AAPL, requested timeframe)
  -> form_candles: source-time OHLC, valid cumulative-volume deltas
  -> derive_timeframe: regular exchange session aggregation
  -> /api/live: initial snapshot, candle replacements/appends, status heartbeat
  -> Vite WebSocket proxy -> Vue selector and candle/volume panes
```

The backend recomputes snapshots once per second per connected browser and
sends only changed candles/completion plus feed status. Same timestamps replace
candles; later timestamps add intervals; late corrections can replace older
bars. A disappearing candle triggers a complete snapshot. Completion advances
without a new quote. Feed loss is detected from the upstream transport within
about 250ms plus scheduling; browser status arrives on the next one-second
update. Reconnect uses a new subscribed client after a three-second backoff.

Vue defaults to 1m. Switching to 5m, 15m, 30m, 1h, 1d, 1w or 1mo opens matching
history plus live updates. Generation checks discard old subscription events.
Unknown volume is histogram whitespace. Selected candles show forming/ended
and complete/partial coverage separately. Chart connection and Yahoo feed
status are separate. Source age comes from source time and advances locally.

The existing HTTP route remains backward compatible:

```text
GET /api/history -> default sample CSV, or selectable observation history
 -> base minute versions -> same backend timeframe/calendar aggregation
 -> six-field array, or metadata envelope with include_status=true
```

Health checks remain independent of Yahoo health. The Check connection button in Feed details
only checks FastAPI health. Synthetic CSV history is available by HTTP but is
no longer the dashboard source. The standalone Yahoo CLI remains a bounded
one-quote recorder.

Storage, replay and session rules are defined in candle-rules.md and
higher-timeframes.md. WebSocket envelope and implementation limits are in
live-updates.md. Observed checks and failures are in verification.md.

The automated UI flow is implemented and passed on Omarchy:

```text
scripts/ui_smoke.py -> disposable SQLite + FastAPI + Vite
  -> scripts/ui_smoke.mjs -> project-scoped playwright-core
  -> system Chromium -> real Vue connection button and timeframe controls
  -> visible inspector compared with stored-observation aggregation
  -> same-minute change / rollover / feed disconnect / mobile viewport
  -> screenshots + JSON report -> browser and service cleanup
```

Constructed replay data is explicitly labeled. Backend completion uses its
fixed evaluation time; the displayed source age continues to use real time.
The chart now fits its first streamed data after an empty snapshot and follows
new intervals when the inspected selection is following the latest bar.

A previous actual quote was verified from storage through WebSocket transport.
The evening live browser attempt received only after-hours quotes, which are
excluded from the regular-session chart. Its screenshot shows FastAPI connected,
Yahoo source age/status and the waiting message. Actual in-session receipt
through to visible candle remains pending. This is independent of the passing
constructed UI SmokeTest. The integrated browser bridge was not repaired;
explicitly approved Playwright automation supplies the project testing path.


Prompt 12 adds recorded-session replay alongside the live path:

```text
Saved SQLite opened mode=ro -> selected inclusive receipt-time range
 -> immutable selection ordered by receipt ID
 -> one step inserts original observation/receipt into connection-local memory
 -> existing form_candles + derive_timeframe at recorded receipt clock
 -> /api/replay snapshot + source time / receipt time / progress
 -> Vue Replay controls -> existing candle/volume chart and inspector
```

No replay route writes the saved database. Late arrivals and explicit revisions
become visible at their own receipt steps. Exact repeats retain receipt progress
without duplicating source values. Only selected receipts provide volume
context. Play advances at 500 ms per receipt rather than original elapsed time;
timeframe changes restart the selection. `ARBITRADE_LIVE_FEED=off` skips the
Yahoo lifecycle and store initialization, enabling disconnected review.

The replay SmokeTest starts isolated feed-off services, drives Chromium through
two replays, compares visible OHLCV and unchanged storage counts, tests an empty
selection and cleans up. Actual capture and separate constructed-data runs
passed. See [replay.md](replay.md) and [verification.md](verification.md).


Prompt 13 adds backend SMAs after session/timeframe aggregation:

```text
Candle snapshot + per-candle ended flags + chosen short/long windows
 -> Python exact decimal-rational rolling sums -> completed-candle SMA rows
 -> first comparable side / ties retain side / side-change signals
 -> HTTP metadata or live/replay WebSocket moving_averages envelope
 -> Vue blue/brown LineSeries + candle arrow markers + inspector/crossover list
```

Live status updates refresh indicators when an interval ends without a quote.
Replay recomputes only from its already revealed receipts; late corrections can
replace or remove historical signals. Forming candles and warm-up rows remain
unavailable. Window changes restart a replay, and each symbol/timeframe uses
its own derived candles. No indicator writes to saved SQLite or extra packages.

The new scripts.sma_smoke command starts/cleans up isolated services and Chromium,
compares the seven-close hand reference with batch and every replay prefix,
checks warm-up/unfinished gaps and visible markers, and verifies test storage.
See [moving-averages.md](moving-averages.md) and [verification.md](verification.md).


Prompt 14 adds a generic named-indicator path:

```text
Python INDICATOR_TYPES registry -> /api/indicators/types -> Vue type/settings form
 -> validated POST /api/indicators -> separate SQLite chart_indicators settings
 -> current symbol/timeframe snapshot + independently saved instances
 -> indicator_rows: completed candle inputs -> calculator -> aligned value/gap rows
 -> HTTP metadata / live periodic status / replay snapshot -> generic Vue lines
 -> candle selection -> each named instance's value and units
```

SMA and rolling price range use this same calculation contract; the paired SMA
crossover path also calls the registered SMA with exact values. Named SMA lines
use the price pane, range uses a separate pane. A configuration is scoped by
symbol/timeframe, survives refresh, and cannot be overwritten by an invalid
creation. Observation storage stays separate/read-only for replay. Replay
refresh can load a new configuration without advancing its receipt position.

scripts.indicator_smoke uses isolated observation/settings databases and services,
creates Range 2/Range 3 in Chromium, compares third-candle values 5/6, refreshes,
checks zero-window handling and saved SQLite settings, creates an SMA through the
same UI, compares replay/batch/forming outputs and cleans up. See
[chart-indicators.md](chart-indicators.md) and [verification.md](verification.md).


Prompt 15 adds local paper execution:

```text
Vue buy/sell/close/hold/wait + stable request UUID
 -> FastAPI /api/paper/actions -> PaperBroker.execute (shared with future agent)
 -> existing mutable config SQLite: audited pending/rejected order or no-order request
 -> next eligible newly received quote (live durable catch-up / replay next only)
 -> recheck FIFO cash/shares -> one transaction: fill + order + balances + receipt cursor
 -> /api/paper/account -> Vue balances/history, with explicit retry of same intent
```

Paper tables share chart-config.sqlite3; recorded observations stay separate.
Live account persists through restart; replay connections have independent
accounts and never consult future stored prices. Startup/receiver/account reads
recover committed live receipts after its saved cursor. Repeated requests and
already processed receipts are idempotent. Fill failure rolls back resources,
status, fill and cursor together. Fees zero; current/displayed prices do not fill
new requests. See [paper-trading.md](paper-trading.md) for precise eligibility.

scripts.paper_smoke runs a labeled disposable fixture, browser-operated $1,000
buy/sell/close sequence, SQL comparisons, duplicate retry, empty sale rejection,
actual backend restart and replay no-lookahead check. It cleans up services and
both test databases. Expected final $1,025/0 and exactly three fills passed.
Named-indicator browser regression also passed after paper integration.


Prompt 16 adds durable P&L after paper execution/market completion:

```text
Fill transaction -> exact weighted purchase cost + cumulative realized P&L
 -> append stable fill-linked P&L row alongside atomic account/fill updates
Completed regular-session 1m close available at receipt/clock boundary
 -> prior open holding + exact average cost -> append valuation row (or unavailable)
 -> durable event/receipt dedup + retain earlier rows/revisions
 -> existing paper account API pnl_history/pnl_summary -> Vue USD history table
```

Valuations use canonical 1m candles independently of chart timeframe. Live
candles are restricted by available time and receipt ID; replay uses only its
visible in-memory observations and recorded clock. Newly completed valuations
precede fills at the same market event. Bars ending before the latest fill do
not retroactively value later holdings. Flat positions keep prior rows and
realized totals. Missing open price yields unavailable unrealized/total.

Two P&L tables share the existing state SQLite; old fills backfill once while
balances/orders stay intact. A repeated fill/candle event adds no second entry.
The scripts.pnl_smoke fixture uses a controlled clock, real Vue operations,
direct SQL comparisons and an actual backend restart; all five reference rows
matched. See [profit-and-loss.md](profit-and-loss.md) and verification.md.


November 11 live runtime check completed actual in-session quote-to-screen
verification: feed had remained deliberately disabled from fixture work. After
restarting with ARBITRADE_LIVE_FEED=on, Yahoo source/age, saved SQLite quote,
backend frame and visibly changing Vue OHLC agree. Evidence:
screenshots/live-check-2026-11-11/. This supersedes earlier pending live-candle
checks, while actual live paper-order/P&L checks remain separate and pending.


Prompt 18 adds independent candle-close snapshots and proposal-only decisions:

```text
Selected completed candle + applied SMA windows + paper account
 -> POST /api/decision-snapshots -> receipt/source-time cutoff + as-of fill ledger
 -> immutable payload/evidence + hashes in state SQLite -> Vue frozen chart/facts
 -> explicit POST /api/decisions(snapshot_id)
 -> Python OpenAI /v1/decisions named choice -> frozen-account validation
 -> factual backend explanation + durable decision ID/status -> Vue proposal
```

No arrow leads to PaperBroker.execute. Buy/sell sizes use the frozen configured
whole-share size, close uses all shares, hold/wait create no order. Missing inputs,
timeouts and malformed answers have distinct saved statuses. Constructed snapshots
remain ineligible for orders. Model-call kind and market-data kind are independent
labels. The API key is loaded only by normal backend startup from backend/.env;
controlled fixtures do not load it. See decisions.md and verification.md.


Prompt 19 adds chart-image questions to the same decision route:

```text
Ask about chart -> freeze visible range through selected completed candle
 -> render saved candles/volume/paired SMAs/configured indicators
 -> Lightweight Charts.takeScreenshot -> PNG with snapshot binding
 -> immutable preview + exact three questions -> explicit Analyze captured chart
 -> POST /api/decisions(snapshot_id,capture)
 -> validate/decode PNG and SQLite binding
 -> one OpenAI user message: input_image + input_json.data
 -> validate action/crossover/evidence by name -> compare visual claim vs Python
 -> save PNG/questions/answers/comparison under decision ID -> visible result
```

The route never submits orders. Missing answers, unreadable/insufficient evidence
and conflicts reject execution eligibility. Controlled Chromium PNG/provider/SQL
checks passed; separately the actual live model's none claim disagreed with Python
down and correctly produced conflicting_signal. See chart-questions.md and
verification.md. Yahoo review feed stays enabled; no packages installed.


Prompt20 adds an independent reviewer to both existing decision paths:

```text
Frozen snapshot (+ saved PNG for chart) -> analyst call once
 -> validated actual choice/named answers + Python facts + same snapshot/image
 -> separate reviewer call once -> named review_verdict
 -> Python rechecks account, crossover strategy, input/image and reviewer status
 -> same decision ID + additive decision_reviews record -> visible two-role audit
```

Each role has a bounded timeout, no retries. Analyst failures skip review; reviewer
rejection/timeout/invalid output blocks eligibility. Pending reviews remain
ineligible. Buy requires up and sell/close down; account rules always apply even
when reviewer accepts. A valid hold/wait passes checks without an order. Controlled
browser/SQL audits cover acceptance, rejection and jointly accepted unaffordable
buy; a separate live wait/down/sufficient plus reviewer accept matched Python and
saved snapshot/image. No call leads to execution. See agent-review.md/verification.md.


Prompt21 connects explicitly enabled reviewed decisions to the paper simulator:

```text
Start -> durable run/account/strategy and baseline time
 -> newly completed live-chart candle -> unique durable claim
 -> saved cutoff snapshot -> shared frozen renderer/native PNG capture
 -> analyst + reviewer once -> saved decision ID -> enabled/account/image/age checks
 -> simulator pending order (or no_order/skip)
 -> next eligible fresh quote -> current cash/shares/age/run/dedup recheck
 -> one transaction: order/fill + cash/shares + P&L + decision/application link
 -> Vue signal/decision/review/fill-or-skip/resulting-account audit
Stop -> revoke run + cancel pending orders; late replies cannot submit/fill
Restart -> cancel/revoke before receipt catch-up; candle keys survive
```

Known constructed sources route to a separate test account. Manual chart requests
never enter application. Browser open/capture required; replay remains manual.
Controlled browser/SQL/restart proof uses1000cash, approvedbuy4 at20 ->920/4,
duplicateApply stays one fill, reviewer veto stays unchanged. No live automation
trade/provider call claimed. See paper-automation.md and verification.md.


Prompt22 adds a read-only two-way conversation about a selected saved decision:

```text
Selected decision ID -> SQLite mode=ro summary: snapshot/agents/validation/outcome
Start voice -> Mac/browser microphone + native RTCPeerConnection + oai-events
 -> local SDP + ICE -> FastAPI with decision ID
 -> server-owned GPT-Live configuration/summary + SDP -> /v1/live/sessions
 -> returned answer -> browser remote description -> wait session.started
 -> bidirectional audio tracks + transcript fragments, same session for follow-up
End/error/disconnect/selection change -> release microphone and close peer/audio
```

No arrow leads to orders, automation mutation or SQLite writes. Remote code can
use local Mac audio; the tunnel carries app signaling and WebRTC connects browser
to provider directly. Mocked browser lifecycle/readonly checks and separate actual
provider synthetic-input audio/captions passed. Human Mac hardware check remains
pending. See live-speech.md and verification.md; no dependency installation.

Prompt23 adds one offline workstation SmokeTest command, `./scripts/smoke-test`:

```text
wrapper (/usr/bin/python + backend/.packages)
 -> new temporary market/config SQLite + explicit clock + feed/model stubs
 -> FastAPI fixture lifespan (no .env/Yahoo) + real Vue/Vite, ports18000/15173
 -> real Playwright Chromium: replay -> add SMA -> PATCH saved window -> inspect
 -> native chart PNG -> actual analyst/reviewer pipeline -> known answers/failure
 -> browser Start -> completed candles -> snapshot/PNG -> rules/review -> order
 -> next eligible marks: buy4@100 -> sell1@110 -> close3@105
 -> UI cash1025/shares0/realized25/unrealized0 + independent SQLite audit
 -> duplicate/veto/Stop guards -> close browser/process groups -> discard DBs
```

Named indicator window edits now persist through PATCH /api/indicators/{id};
existing type-specific validation protects other settings/instances. Automation
panel now shows realized/unrealized P&L from its existing account snapshot.
Only fixture controls change the configured buy/sell sizes during the test.
Production feed/decision/execution rules remain in use; no trading logic bypass.
GitHub Actions workflow repeats the same command twice with offline fixtures;
its hosted provisioning/run is still unverified and requires installation review
before first activation. No Git repository exists here. Separate prior actual
Yahoo/image-model observations and deferred physical voice check remain as
recorded. See workstation-smoke-test.md and verification.md.


Unknown-volume labels are hidden in the chart inspector, hover card, chart key
and decision summary. Available volume still appears; missing volume remains null
and leaves a histogram gap. The volume pane and decision context are retained.

Moving Averages groups each SMA and EMA window by its source interval. FastAPI calculates selected lines from the matching live history or the current replay receipt prefix. At each chart candle it samples the latest value available by that candle’s close or the snapshot time, whichever comes first. Each series uses the display candle timestamps so overlays keep the price and volume panes aligned.

Drawing Tools presents Trend Line, Freehand and Eraser in individual labeled icon rows above the ratio presets. It uses price-pane coordinates for trend lines, freehand strokes, and entry boxes. Dragging opposite corners sets the box bounds and previews the selected ratio before release. The contact eraser removes whole drawings, and undo tracks edits per mode, symbol and timeframe. Each box stores entry and risk per share and derives its target from the fixed reward multiple. The emerald and maroon fills use 50% opacity. The visible-chart Decision API capture includes the drawing overlay.

Live chart delivery shares each in-flight calculation and briefly reuses its
result across identical chart settings. Indicators use the full history before
the server limits the displayed range. The client requests older bars near the
left edge and sends its earliest loaded timestamp on automatic reconnect.


Saved-list recovery: voice decisions and replay ranges use ten-second request
deadlines and retry failed loads after three seconds. A successful list load
clears its outage message; voice loads the selected record before enabling
Start voice. If Replay was selected before its range arrived, range recovery
connects that replay automatically. Unmount clears retry timers. Explicitly
entered replay ranges are preserved when a delayed list arrives.
