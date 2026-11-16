# Candle-close decision proposals


> This document describes the separate paper proposal/automation workflow under **Review paper proposal**. The assignment’s main **Decision API** control uses [image-only chart reading](classroom-decisions.md) with long/short/wait. Keys now load from process settings, project-root `.env`, then legacy `backend/.env`.
Explicit Start/Stop paper automation can now apply approved decisions through a
separate guarded path; manual questions remain read-only. See
[paper-automation.md](paper-automation.md) for current execution/dedup rules.

New analyses also receive a separate reviewer call on the same snapshot/image.
Python enforces account and explicit crossover strategy rules after review; see
[agent-review.md](agent-review.md) for current roles, statuses and eligibility.

Choose a completed candle in the inspector, then **Freeze selected candle**.
Review the saved candle/SMA chart, cash, position, decision time and snapshot ID.
**Request model proposal** submits that saved snapshot; changing the main chart
or receiving another quote does not change it. Each click creates a new decision.
The panel never sends a paper order.

The backend loads the project-root `.env`, then legacy `backend/.env`, on startup using
existing python-dotenv. Set `OPENAI_API_KEY=your_actual_key` in the root `.env`; see
`.env.example` for placeholders. Restart the backend after saving. Process
environment variables take precedence. Keep the file private and out of Git;
never set a frontend `VITE_` key. No credentials are returned or logged.

The provider is OpenAI, using Python's standard HTTP library and
`POST https://api.openai.com/v1/decisions`, model `gpt-6-luna`, with the frozen
JSON input and one named choice question, `paper_action`. Allowed choices are
buy/sell/hold/wait/close. This follows the official
[Decisions guide](https://developers.openai.com/api/docs/guides/decisions) and
[create reference](https://developers.openai.com/api/reference/resources/decisions/methods/create).
No SDK installation is required. `ARBITRADE_DECISION_MODEL` must match the
supported model; `ARBITRADE_PAPER_ORDER_SIZE` is a positive whole-share size
(default 1) for validating proposed buys/sells. Manual paper orders retain their
explicit quantity.

## API and storage

1. `POST /api/decision-snapshots` accepts account_id (live or active replay ID),
   symbol, interval, candle_timestamp, short_window and long_window. It returns
   a snapshot and SHA-256. An incomplete snapshot can be saved for review, but
   cannot call the provider or qualify for paper trading.
2. `GET /api/decision-snapshots/{id}` retrieves that immutable payload;
   `?include_records=true` also retrieves the frozen source evidence.
3. `POST /api/decisions` with `{"snapshot_id":"saved-id"}` returns an ID,
   provider/model, status, validation_status, proposal, quantity, explanation,
   normalized answer and independent model_call_kind/market_data_kind labels.
4. `GET /api/decisions/{id}` returns the durable result.

Two additive tables, decision_snapshots and decisions, live in the existing
state/config SQLite database. Payload and evidence hashes are checked on read.
Snapshots retain actual observations, receipts and as-of fills as evidence;
the input/chart includes up to the last 200 candles and their precomputed SMAs.
There is no route to edit a snapshot. This is application-level immutability,
not protection against a person rewriting the local database and its hashes.

## Time and validation rules

The cutoff is the calendar-aligned candle end. Source times and receipt times
must both be available by that cutoff (and by the current replay evaluation).
Replay reads only its revealed in-memory records. Later revisions and later fills
cannot enter an earlier snapshot. Cash/position are reconstructed from fills
available at the cutoff rather than today's balances. SMA warm-up, missing
account, forming candles and incomplete constituent coverage are explicit
missing inputs. Unknown volume stays unknown and does not invalidate price SMAs.

Buy/sell use the saved configured size. Buys require sufficient frozen cash at
the recorded close; sells cannot exceed held shares. Hold/close require a
position; wait requires a flat account. Close proposes the entire position.
These are checks against frozen facts; they do not promise a future fill price.
The model chooses an action only. Python supplies the factual explanation and
rule outcome, without inventing a model rationale.

Statuses distinguish valid (including hold), invalid_proposal, missing_input,
timeout, malformed_answer, refused, missing_credentials, configuration_error
and provider_error. Errors use sanitized codes; arbitrary provider text and
credentials are never saved. Missing snapshot input creates a durable result
without a provider call. Timeout is bounded and does not retry. Paper orders,
fills, balances and P&L are not mutated by decision creation. Constructed data
is explicitly ineligible for paper orders even when its proposal validates.

## Repeatable verification

```bash
PYTHONPATH=backend/.packages /usr/bin/python -m unittest backend.test_decisions -v
PYTHONPATH=backend/.packages /usr/bin/python -m scripts.decision_smoke --output /tmp/arbitrade-decision-results
```

The SmokeTest starts isolated services, opens Chromium, freezes and renders a
fixed snapshot before analysis, checks valid hold and controlled timeout/malformed
answers, compares stored results and every paper table, then cleans up. It strips
the key from the child environment and uses a fixture lifespan that does not load
`.env`. It makes no live provider request. Local socket support is required.
See [verification.md](verification.md) for observed results and the separate live
provider check status.
