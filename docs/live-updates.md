# Live observation chart

`/api/live?symbol=AAPL&timeframe=1m` accepts AAPL with 1m/5m/15m/1h/1d.
Invalid requests receive an error envelope and close code 1008. No sample
candles are mixed into the observation stream. Initial stored history is
sent on the WebSocket itself so HTTP and subscription startup cannot race.

Messages:

- `snapshot`: symbol, interval, source, feed, candles array, coverage array,
  plus existing history metadata. This loads/replaces all chart data.
- `candle`: symbol, interval, source, feed, candle, completion. The candle has
  exactly the CSV's six fields; completion has interval_end, ended, complete,
  coverage_complete, expected/available_minutes and volume_known.
- `status`: symbol, interval, source, feed. Sent every second, including
  while no quote arrives or the upstream is disconnected.
- `error`: readable error text. Vue displays the error; socket closure triggers
  a retry after three seconds. Changing timeframe invalidates older handlers.

Feed metadata contains status (`connecting`, `waiting`, `live`, `stale`,
`disconnected`, `error`), latest source timestamp/age, last decoded observation
summary and its SQLite observation/receipt ids. The summary describes the most
recent accepted quote; it is not a provenance id for every historical candle.
Age uses source time; source age over 30 seconds changes live to stale.
Missing quotes alone do not prove a disconnection. Backend health remains ok
when Yahoo is unavailable; the page reports each connection separately.

Source prices are quotes, not a complete exchange trade feed. Regular-session
calendar rules exclude out-of-session source minutes, while preserving their
stored source records. Completion means interval ended and minute coverage
complete, not proof that all exchange trades were received. Ended candles can
still be revised. Unknown volume remains null; known available-constituent
volume does not claim full-interval coverage.

One server process owns one continuous AAPL subscription. Subscribe, heartbeat
and decoding reuse the installed yfinance adapter. Its 1.8.0 listen loop hides
failures and can loop after clean closure; listen_continuously consumes one
subscribed transport instead, then lets LiveFeed report loss and reconnect.
This uses pinned yfinance `_ws` / `_decode_message` internals and websockets
transport state; recheck this integration before upgrading those packages.
The transport needed no new dependency. The separately approved UI-testing
setup later added playwright-core 1.65.0 to the frontend dev dependencies.

Snapshots reuse the existing full SQLite aggregation, currently once per second
per browser, and Vue resets both series from its timestamp-keyed candle list.
This favors correct late revisions over throughput; incremental aggregation,
retention limits and larger-history performance work remain future tasks.
Start with a single Uvicorn worker; each additional worker would subscribe.

Repeatable transport verification uses temporary SQLite storage and stops both
services: `PYTHONPATH=backend/.packages /usr/bin/python -m scripts.verify_live`.
`--recorded` supplies constructed `test_data: true` input and visibly labels
its source if a dashboard is opened. `--browser` opens the page and asks for
human comparisons. For automated UI SmokeTest, use
`PYTHONPATH=backend/.packages /usr/bin/python -m scripts.ui_smoke`. The constructed
check verifies same-minute close/volume replacement, rollover, all timeframe
snapshots and disconnect status. The actual check compares a real saved quote
to the WebSocket candle and closes the real upstream socket while retaining
its client WebSocket. The automated constructed UI check passed with desktop/mobile screenshots and
matching values, replacement, rollover, five intervals and disconnected status.
The actual evening Yahoo browser check is pending for an in-session quote;
after-hours quotes were stored but correctly did not produce chart candles.
See docs/screenshots/ui-smoke-2026-11-10/report.json and verification.md.
