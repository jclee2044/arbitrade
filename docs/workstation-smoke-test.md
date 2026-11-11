# Offline workstation SmokeTest

From the project root run:

```bash
./scripts/smoke-test
```

Optional evidence destination: `./scripts/smoke-test --output /tmp/arbitrade-smoke-results`.
Default evidence goes to `/tmp/arbitrade-workstation-smoke`; choose different
output folders to retain successive runs. The command exits nonzero on a missing
expected result, unavailable tool, occupied port, readiness failure or timeout.
It runs without source edits or software installation. AutoLoop corrections are
an agent activity outside this command.

The wrapper uses `/usr/bin/python` and the existing `backend/.packages`; Node,
Vue/Vite/Playwright from `frontend/node_modules` and installed `/usr/bin/chromium`
are reused. Free loopback ports **18000/15173** are required. Existing review
services on 8000/5173 are left running. No virtual environment, dependency manifest
or lockfile changes are needed locally. `ARBITRADE_PYTHON` and
`ARBITRADE_CHROMIUM` can select already provisioned runtimes; `playwright` as the
browser value uses Playwright's already installed browser. CI disables Chromium's
sandbox as required by typical hosted runners; local runs retain it.

The command starts FastAPI with `scripts.workstation_fixture:app`, waits for its
health endpoint, starts Vue through Vite, then opens headless real Chromium.
The fixture replaces the production lifespan, never loads backend/.env or starts
Yahoo, uses new temporary market/config SQLite files, and supplies an explicit
UTC clock and deterministic observations. Only the model and external feed are
stubbed: routes, native chart PNG, analyst/reviewer coordination, rule checks,
next-quote simulator, P&L and SQLite writes are real. Backend outbound
`socket.create_connection` is blocked; browser page requests are restricted to
loopback. No provider credentials are passed or required.

1. Open the recorded session in replay, add named SMA2, and inspect 15:04 UTC:
   `(13+19)/2 = 16`. Edit that same indicator to window3, save and verify
   `(7+13+19)/3 = 13` visibly and in SQLite.
2. Ask about chart, then analyze the native PNG. At the stub provider boundary,
   decode pixels and assert snapshot ID/symbol/candle/cutoff agree. Return
   wait/up/sufficient, check each visible answer and unchanged selected replay
   account fills. Repeat with provider_error and verify visible status/no fill.
   Saved PNG bytes must equal the provider-boundary bytes in the independent audit.
3. Return to live mode and Start paper automation in the browser. New constructed
   data routes to a fresh test account with $1,000, zero shares and zero fees.
   Configure size4 before buying, size1 before selling through the fixture-only
   control endpoint (there is no production per-side size UI). Deliver marks
   only after approved pending orders: buy4 at100 -> cash600/shares4;
   sell1 at110 -> cash710/shares3/realized10/unrealized30;
   close3 at105 -> cash1025/shares0/realized25/unrealized0.
   Intervening completed candles produce deterministic crossovers and holds.
   A reviewer-vetoed close and duplicate observation/claim/apply add no fill.
   Stop in the browser, deliver another completed candle/mark, and assert no new
   attempt/order/fill. The runner independently reads SQLite and verifies exactly
   three orders, fills/fees, all chart payload bytes, indicator window and final P&L.

Read `report.json`, `browser.json`, `services.log` and screenshots in the output
folder. Startup/browser/assertion failures return nonzero and retain evidence.
Browser closes in its finally block; runner finally stops its process groups
(driver, Vue, FastAPI), including timeouts and INT/TERM, and removes temporary
databases. Fixed ports fail before launch if already occupied. SIGKILL/power loss
cannot run application cleanup. Reports include whether launched processes exited.

## Push workflow

`.github/workflows/smoke-test.yml` runs this same command twice on pushes and
manual dispatch, then uploads evidence even on failure. Each invocation creates
a clean account/database. No Yahoo/OpenAI secrets are configured. The workflow is
prepared but **has not run on GitHub**: this directory is not a Git repository,
so there is no remote/push/run to inspect and no Git setup was attempted.

Bootstrap steps are reviewable in the workflow. They have **not been executed**
in this session. Per AGENTS.md, student review/approval of these installation
steps is required before enabling/running the first hosted push workflow:

- Python3.14/Node26.13.0 through setup actions, in ephemeral hosted tool caches.
- `python -m pip install fastapi==0.156.8 uvicorn==0.54.0 pydantic==2.14.1 python-dotenv==1.2.4 websockets==17.4 -r backend/requirements-calendar.txt`:
  runner Python site-packages only, for real API/WebSocket/calendar behavior.
  Versions match installed local distributions; declared Python minimums are
  <=3.14 (calendar also requires <4). Existing calendar manifest is reused.
- `npm --prefix frontend ci`: locked Vue/chart/Vite/Playwright into runner
  `frontend/node_modules`, without changing package.json or package-lock.json.
  Node26 satisfies installed Vite >=22.12 and Playwright >=20 requirements.
- In frontend: `npx --no-install playwright install --with-deps chromium`:
  Playwright1.65.0's Chromium revision1254 (158.0.8127.18) into the runner browser
  cache and its Linux system libraries via apt. It does not change source or
  manifests. Local verification uses existing Chromium155.0.8059.84 instead.

Hosted downloads/resolution/runner compatibility remain unverified until that
approved first run; local passes do not imply a GitHub Actions pass.

## Separate live observations

Offline passes make no claim about actual Yahoo, image-model accuracy or human
voice. Keep `scripts.verify_live`/docs/live-updates.md and earlier live evidence
in docs/verification.md separate. See docs/chart-questions.md for the recorded
live model discrepancy and docs/agent-review.md for the later real two-agent
example. See docs/live-speech.md for synthetic-input provider audio evidence;
the student's physical Mac microphone/speaker check remains explicitly deferred.
