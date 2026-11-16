# One-minute candles from saved observations

`backend/candles.py` uses the existing SQLite observation database. It only
reads; it does not overwrite observations, store derived candles, or change
the CSV chart source. No new dependency or database schema is needed.

From `/home/jlrj/Documents/arbitrade`:

```bash
/usr/bin/python -m backend.candles --ticker AAPL
```

Optional arguments: `--database /absolute/path/to/observations.sqlite3`,
`--provider yahoo`, and `--as-of 2026-11-09T15:00:55Z`. The file must exist.
The CLI opens it read-only. `--as-of` evaluates whether minutes have ended;
it does not reconstruct which receipts were available at that past time.
All observations currently in the database are considered.

## Price and time rules

Filter to one ticker and provider. Read each observation once, independently
of how many receipts it has. Exclude an observation only when an explicit
`supersedes_observation_id` points to it. Preserve every stored source row.
Only the remaining revision leaves contribute to derived candles. Multiple
unlinked messages at the same timestamp remain separate inputs.

Normalize source times to UTC and group into half-open minute intervals:
`[15:00:00, 15:01:00)`. A source time exactly at 15:01 belongs to the next
minute. Output UTC minute-start timestamps ending in `Z`.

Order prices by source time. Open and close are the first and last observed
prices; high and low are their extrema. For tied source times, use first
receipt id, then observation id, as a deterministic tie break. This does not
establish the provider's true ordering: differing tied prices set
`price_order_ambiguous: true` in metadata. Invalid prices cause an error.
Unknown source times are excluded from buckets and their ids are reported in
`unbucketed_observation_ids`; they are never grouped by receipt time.

Each candle contains exactly `timestamp, open, high, low, close, volume`.
The separate `minute_status` array records `ended`, volume availability/reason,
and price-order ambiguity. `ended` means evaluation time is at least the
minute's exclusive end. It does not mean the candle is immune to late data.
Empty minutes are omitted; no prices or zero-volume bars are manufactured.
These are candles of saved price observations, not a complete trade tape.

## Cumulative volume rules

Use Yahoo `day_volume` as a running session total. Never sum those totals or
use `last_size` as a replacement. Select the latest effective observation
strictly before the minute as baseline. Require it to fall in the immediately
preceding minute, avoiding assignment of volume across entirely missing
minutes. All available cumulative totals from that baseline through the
minute must be nonnegative integral values and nondecreasing.

When an explicit source `session_id` is present, require it on all inputs and
require equality. Without it, require the baseline and minute inputs to share
a UTC calendar date. This is a conservative date guard, not an exchange
calendar or proof of session identity. Resets between unobserved messages
cannot be detected; known volume assumes the observed totals share a session.

With a valid baseline and no detected uncertainty:

```text
volume = minute's final cumulative total - pre-minute baseline
       = 1011 - 1000 = 11
```

Updates at the same source timestamp are ordered by first receipt ID. Increasing
or unchanged cumulative totals are accepted; the final received total at the
preceding timestamp is the baseline. This is an observed counter difference,
not Yahoo's downloaded exchange-minute bar volume. Source-time ties may still
make price ordering ambiguous, independently of the counter calculation.

Missing baseline, missing/invalid cumulative values, observed decreases/resets,
or session changes yield `volume: null` and a reason in metadata. A decreasing
or invalid tied pre-minute baseline also yields unknown volume. Unknown is
never coerced to zero. Following a
reset, later minutes may regain known volume when a valid new baseline exists.
Volume for a minute still in progress covers observations received so far.

## Late data and corrections

Recompute from the effective saved observations on every call. A late source
observation can change an ended minute's open, high, low, close, or volume.
A late baseline can resolve previously unknown volume. An identifiable
correction replaces its explicitly linked predecessor only in aggregation;
old source values and receipts stay in SQLite. Recomputing all buckets also
updates any following minute whose baseline changed, and moves observations
if an explicit correction changes source time.

The Yahoo receiver currently cannot identify correction links. A changed
message at the same source time is retained, not treated as an automatic
correction. Increasing counters at that timestamp contribute to the observed
delta; decreases remain unknown. See README for the
recorder's exact-payload repeat policy and limitations.

## Verification

```bash
/usr/bin/python -m unittest backend.test_candles backend.test_observations backend.test_yahoo_stream -v
```

The tests use disposable databases and labelled constructed inputs.
The target candle matches the prompt both before and after minute end, and
after the middle price observation arrives late. Other checks cover repeats,
explicit corrections, baseline changes, resets, missing data, tied timestamps,
session boundaries, ticker filtering, and receipt lifecycle behavior.
Exact expected and observed values are recorded in `docs/verification.md`.
