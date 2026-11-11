# Analyst and reviewer decisions

Explicit Start/Stop paper automation can now apply approved decisions through a
separate guarded path; manual questions remain read-only. See
[paper-automation.md](paper-automation.md) for current execution/dedup rules.

Every new `POST /api/decisions` now runs an analyst and, when it has a validated
choice to review, a separate reviewer. Both calls use the existing OpenAI
Decisions adapter and gpt-6-luna. Each role is called at most once, with a timeout;
there are no automatic retries. A missing or invalid analyst answer skips review.
This panel remains read-only for paper balances, orders, fills and P&L.

Use the existing **Freeze selected candle → Request model proposal**, or
**Ask about chart → Analyze captured chart** flow. The result now displays both
role outputs/models, shared snapshot/hash, reviewer verdict, observed account
facts, final checks and execution eligibility. Expand **Inspect role instructions
and answers** to see exactly which questions and normalized answers were saved.

The analyst proposes buy/sell/hold/wait/close. The reviewer receives that actual
choice, its named answers, backend facts and the identical saved snapshot. For
chart analysis it also receives the identical saved PNG; both image hashes are
retained. These are independent calls with different instructions, not a second
label on the analyst's response.

The reviewer returns one named choice, `review_verdict`:

| Verdict | Meaning |
| --- | --- |
| accept | Reviewer considers the proposal supported |
| reject_insufficient_cash | Purchase exceeds cash |
| reject_position | Position does not support action/size |
| reject_unsupported_signal | Strategy or crossover does not support proposal |
| reject_insufficient_evidence | Evidence is missing, unreadable or conflicting |

Python explains the observed values rather than inventing a reviewer rationale.
It displays cash, cost of one share, configured purchase cost, held shares and
crossover. For example, the controlled fixture's buy100 at19 costs1900 against
948cash. A reviewer acceptance cannot override that failure.

## Final rules and storage

Account rules remain long-only: buy must be affordable at frozen close, sell
cannot exceed holdings, hold/close require a position and wait requires flat cash.
The explicit strategy rules are **buy on up crossover; sell/close on down
crossover**. Hold preserves an existing position; wait stays flat. Both roles are
told those rules and Python enforces them independently. Visual conflicts,
unreadable/insufficient evidence and invalid outputs remain failures even if a
reviewer accepts.

A review can pass for a valid hold or wait without creating an executable order.
`review.final_check.passed` means the role/account/strategy/evidence checks passed.
`paper_order_eligible` additionally requires complete non-constructed application
data and an actionable buy/sell/close. Constructed fixtures stay ineligible.
Nothing in this endpoint submits an order, even when eligibility is true.

The existing decisions/snapshots/image records are reused. An additive
`decision_reviews` table stores the two roles, models, questions, actual normalized
outputs, snapshot hash, shared image hashes, supporting facts and final check under
the same decision ID. GET `/api/decisions/{id}` includes the `review` object.
Historical decisions without reviews are preserved as originally recorded.

Eligibility starts false and stays false while review is pending. Reviewer
rejections yield `review_rejected`; timeouts/invalid replies yield
`review_timeout`/`review_malformed_answer` (other provider failures retain their
sanitized status prefix). Python failures retain `invalid_proposal`,
`unsupported_signal` or original image/input statuses. Reviewer acceptance cannot
erase an analyst/backend failure. A pending or interrupted review is ineligible.
Normal HTTP timeout is20seconds per role with a21second outer bound. A timed-out
worker cannot later promote its result; no retry is scheduled.

## Verification

```bash
PYTHONPATH=backend/.packages /usr/bin/python -m unittest backend.test_decision_review -v
PYTHONPATH=backend/.packages /usr/bin/python -m scripts.review_smoke --output /tmp/arbitrade-review-results
```

The browser SmokeTest starts isolated services, freezes a known up crossover,
checks accepted hold, reviewer rejection, jointly accepted unaffordable buy,
reviewer timeout and malformed reply, compares visible results with SQLite and
all paper tables, then cleans up. Its call log proves one call per role per
reviewed decision and matching snapshot hashes. It uses controlled replies,
constructed records and no real credentials. Unit tests also cover strategy veto,
identical image/named answers, provider mutation isolation, pending eligibility
and an actual worker timeout.

Separately, one live two-call chart example on November11,2026 used recorded Yahoo
AAPL/1m15:52 UTC (10:52 Eastern), cutoff15:53 UTC. Analyst answered
**wait/down/sufficient**, reviewer answered **accept**, and Python's down crossover
and flat1000cash account agreed. Final checks passed; wait is not actionable and
no order was placed. Both role outputs and shared snapshot/image hashes match
SQLite. See screenshots/review-live-2026-11-11/report.json and
[verification.md](verification.md) for actual and controlled observations separately.

No new package or credential setup is needed. The existing private backend/.env
and [OpenAI Decisions request format](https://developers.openai.com/api/reference/resources/decisions/methods/create)
are reused.
