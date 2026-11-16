# Ask about a frozen chart


> This document describes the separate paper proposal/automation workflow under **Review paper proposal**. The assignment’s main **Decision API** control uses [image-only chart reading](classroom-decisions.md) with long/short/wait. Keys now load from process settings, project-root `.env`, then legacy `backend/.env`.
Explicit Start/Stop paper automation can now apply approved decisions through a
separate guarded path; manual questions remain read-only. See
[paper-automation.md](paper-automation.md) for current execution/dedup rules.

New analyses also receive a separate reviewer call on the same snapshot/image.
Python enforces account and explicit crossover strategy rules after review; see
[agent-review.md](agent-review.md) for current roles, statuses and eligibility.

Select a completed candle in the dashboard inspector, choose your SMA windows,
and scroll/zoom so the candle is visible. Click **Ask about chart**. The backend
freezes the selected symbol/interval, current range through that candle, candles,
indicator values and paper position. The dashboard renders that saved data and
uses Lightweight Charts' native PNG export, limited to the chart. It includes
candles, volume and indicator panes, with blue short SMA and amber long SMA.
Unknown volume stays a gap rather than zero.

Inspect the **Captured chart** preview, symbol, interval, cutoff, effective range
and three exact named questions. Click **Analyze captured chart** to submit.
Live updates can continue; the saved PNG and snapshot stay fixed. Each analysis
click creates a separate decision. No button in this panel executes a paper order.
The chart range is capped at the last 200 candles through the cutoff; the preview
and labels show the actual submitted range. Selecting a candle outside the visible
range requires recapture. SMA calculations retain earlier warm-up history even
when the visible capture starts later.

Python retrieves the snapshot from SQLite and validates the uploaded PNG and its
snapshot binding. It sends one user message to OpenAI Decisions containing both
`input_image.image_url` (an actual `data:image/png;base64,...` URL) and
`input_json.data` (the saved snapshot), with three named choice questions:

| Name | Allowed answers |
| --- | --- |
| action | buy, sell, hold, wait, close |
| crossover | up, down, none, unreadable |
| evidence | sufficient, insufficient, unreadable |

The action uses the existing long-only frozen cash/position rules and configured
whole-share size. Python validates every answer by name regardless of response
order; missing/duplicate names and unknown choices are malformed answers. It
compares the model's visual crossover with the exact Python crossover. Conflicts,
unreadable images and insufficient evidence are explicitly ineligible for automated
execution. Constructed snapshots remain ineligible, even when answers match.
The factual explanation identifies both claims; the backend never invents a model
rationale. A matching answer is not an execution instruction.

PNG validation bounds bytes/pixels, verifies signature/chunk CRCs, fully inflates
and decodes RGB/RGBA scanlines, rejects blank images and verifies embedded snapshot
ID/hash/symbol/interval/cutoff/range against SQLite and the request manifest.
Errors instruct the student to recapture the matching/readable chart. This binding
detects accidental swaps; it does not prove arbitrary client-provided pixels are
a faithful rendering. This is a local application, without capture attestation.

## API and persistence

- `POST /api/decision-snapshots` additionally accepts optional chart_start and
  chart_end. It freezes configured indicator series as well as the paired SMAs.
- `GET /api/decision-questions/chart` returns the exact three questions shown
  before submission and stored with the result.
- `POST /api/decisions` still accepts the original snapshot-only request. Adding
  `capture: {image_url, manifest}` selects image analysis. See frontend
  chart-capture.js for manifest fields and PNG metadata binding.
- `GET /api/decisions/{id}` includes image_analysis: capture metadata, questions,
  normalized answers, comparison and retrievable image URL.
- `GET /api/decisions/{id}/image` returns the saved image/png, without caching.

The additive decision_images table stores the PNG bytes, metadata/hashes, questions,
answers and comparison under the existing decision ID. Existing decision records
are preserved. PNGs live in the state SQLite database, not in market observations
or a remote image host. The key stays in backend environment settings; no frontend credentials or
new dependency are needed. Snapshot-only decisions continue to work.

## Repeatable checks and live result

```bash
PYTHONPATH=backend/.packages /usr/bin/python -m unittest backend.test_chart_decisions -v
PYTHONPATH=backend/.packages /usr/bin/python -m scripts.chart_smoke --output /tmp/arbitrade-chart-results
```

SmokeTest uses isolated services/SQLite, recorded constructed crossover observations
and a controlled provider. Chromium captures a known up crossover, volume bars and
Range 2, checks the preview/questions, then named results and failures. Direct SQL
confirms that the provider received the exact decodable saved PNG, displayed answers
match storage, and every paper table is unchanged. Services/browser/databases are
cleaned up. It does not read backend/.env or make a live provider request.

On November 11, 2026, one separate live image request used actual recorded Yahoo
AAPL/1m candles at 15:37 UTC (10:37 Eastern), cutoff15:38 UTC. OpenAI gpt-6-luna
answered **action=wait, crossover=none, evidence=sufficient**. Python calculated
**down**, so the saved result correctly has **conflicting_signal**, comparison
conflict, and no execution eligibility. This is a disagreement, not a successful
visual signal match. The browser result, PNG and SQLite answers matched, and paper
balances/orders/fills/positions were unchanged. See
screenshots/chart-live-2026-11-11/report.json and [verification.md](verification.md).

Request schema: [OpenAI Decisions reference](https://developers.openai.com/api/reference/resources/decisions/methods/create).
PNG export: [Lightweight Charts screenshot example](https://tradingview.github.io/lightweight-charts/examples/data/screenshot).
