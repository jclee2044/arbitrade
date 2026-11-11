# Named chart indicators

In **Chart indicators**, choose a type, enter a name, set its window, and click
**Add indicator**. **Saved indicator values** shows each instance's settings
and its value for the selected candle. Selecting another candle updates the
values. Unavailable means warm-up is incomplete or the candle is still forming.
Names/settings return after refresh for the same symbol and timeframe.

The available types and settings come from Python through FastAPI. The first
two types are:

| Type | Inputs from the last N completed candles | Calculation | Units | Display |
| --- | --- | --- | --- | --- |
| `sma` | closes | sum of closes / N | Instrument quote price (USD for AAPL) | Price pane |
| `price_range` | highs and lows | highest high − lowest low | Quote-price difference (USD for AAPL), not percent | Separate indicator pane |

Both use a positive whole-number `window`, default 20. Each named instance owns
its validated settings. Window 2 and window 3 can coexist without affecting one
another. Names are trimmed, 1–80 characters, unique within the symbol/timeframe
(case-sensitive). Invalid settings or duplicate names produce an explanation
and leave existing entries unchanged. The UI supports creating named instances;
editing/deleting saved instances is not part of this change.

The existing paired-SMA/crossover controls remain compatible, and their
calculation now calls the same registered SMA implementation. Those paired
query controls remain separate from named saved instances. To retain a specific
SMA window across refresh, create a named SMA through Chart indicators.

## Calculation contract and extension

`backend/indicators.py` defines `IndicatorType` and the `INDICATOR_TYPES`
registry. A type contains a label, description, units, display pane (`price` or
`separate`), settings metadata and a pure Python calculator. Supported setting
metadata is an integer field with label, minimum and default. Validation is
strict: booleans, fractions, strings, missing/extra fields and values below the
minimum are rejected before persistence/calculation. Vue renders the supplied
settings fields; it contains no SMA or range formula or hardcoded type list.

A calculator receives:

1. Completed candle dictionaries in chronological order, with the standard
   timestamp/open/high/low/close/volume fields. Completion uses existing `ended`
   metadata. Coverage completeness remains a separate label, so a partially
   captured ended candle still contributes its available prices.
2. A fresh dictionary of that instance's validated settings. Do not mutate the
   candle input. Do not read feeds, storage or future observations in calculators.

It returns one number (preferably an exact Fraction) or `None` for **each input
completed candle**, in the same order. For N-window calculations, the first
N−1 outputs are gaps. `indicator_rows` validates settings, filters to completed
candles, checks output length, aligns the results to **every chart candle time**
(including a gap at forming candles) and serializes numeric values as floats.
It does not create missing market candles or treat warm-up as zero.

To add a type, implement a pure calculator and register its metadata, for
example following `range_values` / `price_range` in that file:

```python
INDICATOR_TYPES['my_type'] = IndicatorType(
    label='My indicator', description='Describe the calculation and inputs.',
    units='price difference', pane='separate',
    settings={'window': dict(label='Window', type='integer', minimum=1, default=20)},
    calculate=my_calculator,
)
```

The catalog, UI form, named-instance transport, persistence and rendering use
that registration. No new Vue calculation is needed. A unit test registers a
third constant type and exercises the generic output path. The paired SMA
uses `indicator_rows('sma', ..., exact=True)` before comparing sides, preserving
its full-precision crossover and tie rules.

Calculations consume the snapshot supplied by the existing live or replay
pipeline. A late revision changes values only when available in that snapshot;
replay never reads future selected observations. Windows count actual completed
candles across sessions, not invented consecutive intervals. Large-history
performance remains future work; range currently scans its rolling window.

## Saved configuration and transport

Default settings file: `backend/data/chart-config.sqlite3`, selected separately
with `ARBITRADE_CONFIG_DATABASE=/absolute/path/chart-config.sqlite3`. Keep it
separate from `ARBITRADE_DATABASE` (recorded observations). Startup initializes
only the settings table; calculations do not save derived values. Creating a
named indicator writes configuration only. Replay still opens recorded sessions
read-only. No fixture configurations are added to the production settings file.

`chart_indicators` stores id, symbol, timeframe, name, type and settings JSON,
with a unique (symbol, timeframe, name) constraint. Each operation opens/closes
its own connection; insert validation happens before the transaction.

- `GET /api/indicators/types`: types, descriptions, units, pane and setting rules.
- `GET /api/indicators?symbol=AAPL&timeframe=1m`: saved named configurations.
- `POST /api/indicators`: creates an instance (201); invalid input 422;
  duplicate name 409. Example body:

```json
{"symbol":"AAPL","timeframe":"1m","name":"Range 2","type":"price_range","settings":{"window":2}}
```

HTTP history with `include_status=true` and live/replay WebSocket messages add
an `indicators` array containing the configuration, units/pane and
`rows: [{"timestamp": "...", "value": 5.0}]`. Live periodic status reflects
new settings. A replay `{"action":"refresh"}` reloads configured indicators at
the **same** replay position/clock; adding an instance does not require advancing
or restarting replay. `next` retains its earlier behavior. Timeframe changes
reopen that timeframe's configuration; returning to 1m restores its instances.

## Repeatable browser verification

```bash
PYTHONPATH=backend/.packages /usr/bin/python -m scripts.indicator_smoke --output /tmp/arbitrade-indicator-results
```

This starts feed-off FastAPI/Vite on 18000/15173 and system Chromium with the
existing Playwright dependency. It creates a labeled fixture in one disposable
SQLite database and saves settings to a **different** disposable database.
It performs real UI creation/refresh/error/inspection operations and compares
visible values, checks the saved settings and unchanged observation file, then
cleans up browser, services and both databases. The previous SmokeTest runners
also isolate their configuration databases.

Constructed (high, low) pairs: (12,9), (15,10), (13,11). Completed outputs:

| Candle | Range 2 | Range 3 | Named SMA 2 (closes 12,15,13) |
| --- | --- | --- | --- |
| First | Unavailable | Unavailable | Unavailable |
| Second | 15−9 = 6 | Unavailable | 13.5 |
| Third | 15−10 = **5** | 15−9 = **6** | **14** |

Verified November 11, 2026: Range 2/Range 3 created through the UI, third-candle
values 5/6, refresh restored settings and values, zero window explained the error
and kept both valid entries. Named SMA creation uses the same interface. Replay
prefixes show forming gaps and final values equal batch. Observations stayed
byte-identical (6 source observations / 6 receipts). Settings SQL contained the
three named instances with independent windows 2/3/2. Desktop/mobile screenshots
visually reviewed. Existing SMA crossover UI regression also passed.

[Report](screenshots/indicators-2026-11-11/report.json),
[range chart](screenshots/indicators-2026-11-11/range-lines.png),
[verification/failures](verification.md). This proves the constructed reference;
actual fresh provider indicator-to-screen verification remains pending.
