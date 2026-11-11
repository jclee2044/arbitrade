# Simple moving averages

The chart overlays a blue short SMA and a brown long SMA. Choose the two window
lengths and click **Apply SMA windows**. Defaults are 20 and 50. Both must be
positive whole numbers, with short smaller than long. Applying windows reconnects
the current selection; a replay restarts from its first receipt.

Python averages the last N **ended candle closes**, including the candle at
that timestamp. A window counts existing candles for the selected symbol and
interval, across sessions; missing intervals are not invented. A candle's
`ended` flag means its interval has finished. Coverage remains a separate label:
an ended candle with partial recorded coverage still contributes its available
close. This calculation does not claim backfilled or complete market data.

A window stays Unavailable until N ended candles exist. A forming candle has
neither a confirmed SMA value nor a crossover. On live transport, interval end
can make an SMA available through a periodic status update without a new quote.
On replay, end is evaluated using the recorded receipt clock, as before.

The first non-equal comparable pair establishes the side without a signal.
Equal pairs retain the last known side. Only a later change from below to above
or above to below produces a signal. Python uses exact rational sums of the
stored decimal close representations for averages and comparisons. Output
numbers are serialized as floats; Vue formats values to at most six fractional
digits for display. Signals are determined before serialization or formatting,
so displayed equal values can still have a confirmed crossover.

Green upward and red downward arrows mark the relevant completed candles.
The inspector shows both SMA values and the selected candle's signal; the
Confirmed SMA crossovers list provides accessible times/directions/values.
Vue renders the backend output and performs no averaging or crossover detection.
A new timeframe or symbol recomputes its own history. Late revisions recompute
all affected averages and signals, and may replace or remove historical markers.
Replay only uses observations and revisions already revealed at that receipt.

HTTP history accepts `short_window` and `long_window`. Use `include_status=true`
for the envelope with `moving_averages`; the default six-field candle array
remains compatible. Both live and replay WebSockets accept the same windows.
Live snapshots, candle updates and status messages carry the full current
`moving_averages` object. Replay snapshots carry it after every receipt.

```json
{
  "moving_averages": {
    "short_window": 2,
    "long_window": 3,
    "rows": [
      {"timestamp": "2026-11-10T15:04:00Z", "short": 16.0, "long": 13.0, "signal": "up"}
    ]
  }
}
```

Each candle has a row, with `null` for unavailable values and absent signals.
Possible non-null signals are `up` and `down`. No indicators are persisted to
SQLite and replay remains read-only with respect to saved sessions.

## Checked reference

Constructed completed closes: 13, 10, 7, 13, 19, 7, 1. Windows: 2 and 3.

| Candle / UTC time | Short SMA | Long SMA | Signal |
| --- | --- | --- | --- |
| 1 / 15:00 | Unavailable | Unavailable | None |
| 2 / 15:01 | 11.5 | Unavailable | None |
| 3 / 15:02 | 8.5 | 10 | None; establishes below |
| 4 / 15:03 | 10 | 10 | None; retains below |
| 5 / 15:04 | 16 | 13 | Up |
| 6 / 15:05 | 13 | 13 | None; retains above |
| 7 / 15:06 | 4 | 9 | Down |

Both full-history and receipt-by-receipt checks passed, including every warm-up
row. The seventh first appears forming and has no averages or downward signal.
A repeated receipt at its interval end confirms its 4/9 values and down marker.
An additional unit test delivers a late revision to candle 5: averages and
historical signals change only after its receipt, proving no future revision
is used by earlier replay frames.

Run the repeatable UI SmokeTest:

```bash
PYTHONPATH=backend/.packages /usr/bin/python -m scripts.sma_smoke --output /tmp/arbitrade-sma-results
```

It starts feed-off FastAPI/Vite on 18000/15173, opens system Chromium using the
existing project Playwright, applies 2/3 through the UI, checks invalid windows,
live transport against the same frozen constructed history, HTTP batch output,
every replay prefix and inspector, the forming candle, final markers, mobile
layout and a fresh 5m selection. It verifies the separate test database remains
byte-identical (7 observations / 8 receipts), saves report/screenshots, then
cleans up its services/browser and disposable database. No source edits or
production database writes are needed. Ports must be free. All test input is
labeled CONSTRUCTED test_data=true.

[Checked two-marker chart](screenshots/sma-2026-11-10/two-crossovers.png),
[full report](screenshots/sma-2026-11-10/report.json),
[verification and failures](verification.md). Fresh live provider crossover
verification remains pending; this evidence uses the requested hand reference.
