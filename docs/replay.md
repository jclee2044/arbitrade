# Recorded-session replay

Saved counter updates sharing a source timestamp now yield observed volume
when totals are nondecreasing in receipt order. Decreases, resets, invalid values
and missing baselines remain unavailable. The chart identifies the counter-delta
basis. This differs from Yahoo downloaded bar volume. The saved-Yahoo
[volume trace](part-41-evidence.md) verifies SQL, backend and visible chart values.

Choose **Replay** on the dashboard, select a saved symbol, and enter inclusive
start/end **receipt times**, with an ISO 8601 timezone such as `+00:00` or `Z`.
The defaults cover the saved receipts for that symbol. Click **Load / restart
replay**, then **Next observation** or **Play replay**. Play advances one receipt
every 500 ms after the previous frame arrives; **Pause replay** stops scheduling
steps. Playback is accelerated by receipt, not paced by original elapsed time.
Changing timeframe or restarting starts the selection from zero.

The title says Replay. Progress counts receipts, including exact repeats. Both
the original source time and receipt time of the current observation are shown.
Source timestamps can move backward for a late arrival. No replay step records
a new observation or receipt in the saved database. An empty selection explicitly
says it has no recorded observations. After-hours observations can still advance
progress without producing regular-session candles.

To start the backend with Yahoo disconnected:

```bash
ARBITRADE_LIVE_FEED=off PYTHONPATH=backend/.packages /usr/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
npm --prefix frontend run dev
```

`ARBITRADE_DATABASE` selects a saved database as before. Feed-off startup does
not initialize, migrate or create the observation database. Restart with the
variable omitted or `on` to resume the shared Yahoo subscription.

`GET /api/replay/selections` lists saved Yahoo symbols and receipt bounds.
`WS /api/replay?symbol=AAPL&start=...&end=...&timeframe=1m` sends an empty initial
snapshot and advances with each `{"action":"next"}` message. Use URL encoding
for query values (especially `+`). Each snapshot includes `replay.position`,
`total`, `current`, `done` and an optional empty-selection message. The optional
`calendar` parameter is required for symbols other than AAPL; the current UI
and recorder support AAPL/NASDAQ.

The saved file is opened with SQLite `mode=ro`. A connection-local in-memory
SQLite database accumulates selected observations/receipts in original receipt
ID order, retaining original IDs, payloads, source times and explicit correction
links. Each frame uses the existing `form_candles` and `derive_timeframe`
functions. No future selected receipt is inserted before its step. Candle end
is evaluated at the greatest processed receipt time; existing source-time
availability and exchange-session rules still apply. Repeated payloads add
receipt steps without duplicate source values. Correction links take effect
when their observation arrives, including corrections to older candles.

Only the selected receipts supply candle and volume context. Include the
preceding minute when a cumulative-volume baseline is needed. An absent
baseline yields Unknown, never a fabricated zero. Replay completion does not
advance the market clock beyond the final receipt, so its last candle may
remain Still forming. Selections are frozen when loaded; reload to include
newly saved receipts. Selection rows and complete snapshots are held in memory;
large-session scaling remains future work.

Run the replay UI SmokeTest without source edits:

```bash
PYTHONPATH=backend/.packages /usr/bin/python -m scripts.replay_smoke --output /tmp/arbitrade-replay-results
PYTHONPATH=backend/.packages /usr/bin/python -m scripts.replay_smoke --constructed --output /tmp/arbitrade-replay-constructed
```

The first uses the first actual saved AAPL receipt and independently reads its
price from SQLite; it expects a regular-session candle and Unknown volume for
that single-receipt selection. This matches the current saved capture. If that
capture is replaced with a different session, update the verification selection
appropriately rather than treating absent data as a pass. The second uses a
separate disposable database labeled CONSTRUCTED test_data=true in the UI and
report. It verifies known volume, a late correction and an exact repeat.

Both commands start new feed-off FastAPI/Vite services on **18000/15173**, launch
system Chromium with the existing project Playwright dependency, perform two
replays and compare visible values, test automatic playback and a timeframe
change, test an empty selection, check unchanged observation/receipt counts,
write screenshots/report.json and clean up their services/browser. Existing
development services are preserved. Vite accepts `ARBITRADE_FRONTEND_PORT` and
`ARBITRADE_BACKEND_PORT`; defaults remain 5173 and 8000.

Actual capture result: 2026-11-10 19:32 UTC, OHLC 348.58, volume Unknown. Known
volume result in constructed data: 15:00 UTC O/H/L/C 98/103/98/103, volume
1011 − 1000 = 11. Both passed twice in Chromium. Actual late revisions and
known-volume captures still need real provider examples; those cases are
currently verified using constructed data. Evidence and initial failures are
recorded in [verification.md](verification.md).
