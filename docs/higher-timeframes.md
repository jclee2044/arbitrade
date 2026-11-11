# Session-aligned history

The history endpoint derives all requested resolutions from one-minute data
on every request. Supported values: `1m` (default), `5m`, `15m`, `1h`, `1d`.
It never treats already aggregated bars as minute inputs. No higher-timeframe
candles are cached or written to SQLite.

Start the backend from the project root with its approved local dependencies:

```bash
PYTHONPATH=backend/.packages /usr/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Example requests:

```text
/api/history?symbol=AAPL&timeframe=5m
/api/history?symbol=AAPL&timeframe=1d&include_status=true
/api/history?symbol=AAPL&timeframe=15m&source=observations&include_status=true
/api/history?symbol=AAPL&timeframe=5m&as_of=2026-11-09T14:32:00Z&include_status=true
```

The default response remains an array of six-field candles, preserving the
existing Vue chart request. `include_status=true` returns an envelope with
`candles`, `coverage`, symbol, timeframe, calendar, source, and evaluation time.
Every candle still contains exactly timestamp/open/high/low/close/volume.
Invalid timeframes, calendars, source values, or naive evaluation times return
HTTP 422. An unavailable calendar dependency returns HTTP 503.

## Inputs and availability

`source=sample` (default) reads the existing synthetic CSV and labels its symbol
as AAPL. It rejects other symbols. A complete static CSV minute becomes
available at its exclusive end, so replay cannot see its final high/low/close
before then. The fixture has no historical revision log.

`source=observations` reads the existing SQLite file without modifying it.
It reconstructs one-minute candles using only messages whose source time and
at least one backend receipt time are at or before `as_of`. Only corrections
received by then can supersede an old observation. A current minute can
therefore appear as an observed, unfinished snapshot. The bounded receiver
still records one quote per invocation; this is not a continuous feed.

`as_of` defaults to current UTC and must include a timezone. Latest available
versions replace prior versions of a minute; they are not added twice. The
pure aggregation layer accepts explicit `MinuteVersion` availability timestamps.
SQLite replay derives the corresponding snapshot from source/receipt history.
Late data changes results only after it is received. The standalone
`backend.candles --as-of` command retains its earlier end-status-only semantics;
the history service additionally passes its receipt-availability cutoff.

## Session and grouping rules

Use installed exchange-calendars 4.13.2. AAPL defaults to `NASDAQ`, an alias of
the package's shared US equities `XNYS` calendar. For another recorded symbol,
explicitly supply its exchange calendar, for example `calendar=XNYS`; the
backend does not guess a listing venue. Keep its package calendar current for
schedule changes. Tests verify the relevant 2026 US regular sessions against
[Nasdaq's published schedule](https://www.nasdaq.com/market-activity/stock-market-holiday-schedule).

Only regular-session minute starts are included, using `[open, close)` and
excluding scheduled breaks. Pre-/post-market minutes, holidays, and the
exclusive close boundary are reported as excluded. Exchange-local open/close
times are converted by the calendar to UTC, accounting for daylight saving
and early closes. A daily candle starts at the session open in UTC and covers
that one trading session, including any missing-minute gaps. It never uses
UTC midnight or splits a session because observations are sparse.

Intraday intervals start at `session_open + floor(offset / duration) * duration`.
Thus an hour starts at 14:30 UTC for the November sample, not 14:00. The last
interval is clipped to the session close. An early-close final hourly bar can
have only 30 expected minutes. Scheduled breaks are omitted from expected
minute counts, while groups remain anchored to the session open.

Within each group, use first open, maximum high, minimum low, last close, and
sum of the available minute volumes. Unknown constituent volume yields null;
known zero remains zero. A missing minute is a coverage gap, not a fabricated
zero-volume candle. Known volume for sparse input means the sum for available
minutes only, not a verified total for the full session or interval.

## Separate coverage and completion

Each coverage entry reports timestamp, session label, interval end, expected
regular-session minutes, available distinct minutes, `coverage_complete`,
`ended`, `complete`, and `volume_known`. `complete` requires both full minute
coverage and elapsed interval end. Coverage measures represented minute bars;
it does not prove that every trade or quote was captured inside each minute.
Unknown volume and incomplete coverage are independent conditions. Ended
bars remain revisable when later data becomes available.

For the three supplied minutes, the five-minute candle is:

```json
{"timestamp":"2026-11-09T14:30:00Z","open":100,"high":105,"low":99,"close":104,"volume":3550}
```

Coverage is 3/5 for five minutes and 3/390 for the regular day. Both are partial.
Adding a labelled constructed 14:35 minute creates a second five-minute bar
but updates the same daily bar. A next-session minute creates another daily
bar timestamped at the next session's open.

## Verification

```bash
PYTHONPATH=backend/.packages /usr/bin/python -m unittest backend.test_timeframes backend.test_candles backend.test_observations backend.test_yahoo_stream -v
/usr/bin/python scripts/smoke_test.py --http-only
```

All 39 tests pass, including the actual calendar's early closes, holiday and
DST boundaries, replay visibility, revised-minute replacement, known-zero and
unknown volume, and session alignment. Direct HTTP requests for all five
timeframes and invalid inputs passed. The existing frontend proxy smoke
passed, including backend failure/recovery. Browser rendering was not changed
or reverified; its earlier connection limitation remains. Exact results are
in `docs/verification.md`.
