# UI testing setup and browser recovery record

Updated November 10, 2026 (Eastern). The Playwright alternative is approved,
installed and verified. The original request and approval are preserved in
prompts/08a-restore-ui-testing.md and prompts/08b-run-ui-testing.md.

## Browser connection diagnosis

This chat runs on the SSH host omarchy. Integrated-browser discovery returned
no apps/browsers and direct iab opening reported unavailable. The Browser
plugin's diagnostics found system Chromium but missing OpenAI native messaging
host and extension on that remote host. This confirms missing extension setup;
it does not prove the underlying cause of local integrated-browser routing.
Neither the desktop settings nor the extension/native-host setup was changed.
The project now uses the separately approved automated testing path below.

## Installed dependency

The student explicitly approved project-scoped test dependencies and browser
binaries, with separate approval required for sudo/system packages. Registry
metadata confirmed playwright-core 1.65.0 requires Node >=20. Current Node is
26.13.0, npm 11.20.0 and /usr/bin/python 3.14.8. Installed with:

```bash
npm_config_cache=/tmp/arbitrade-npm-cache npm --prefix frontend install --save-dev --save-exact playwright-core@1.65.0
```

One package was added to frontend/node_modules. frontend/package.json and
package-lock.json now pin playwright-core 1.65.0 as a dev dependency. Other
existing pinned dependencies remained unchanged. npm audited 38 packages and
reported 0 vulnerabilities. No system-wide installation, sudo, Python virtual
environment, or browser binary download was needed. The actual UI checks
confirmed compatibility with installed Chromium 155.0.8059.84, launched with
its sandbox enabled.

## Repeatable UI SmokeTest

```bash
PYTHONPATH=backend/.packages /usr/bin/python -m scripts.ui_smoke --output /tmp/arbitrade-ui-results
```

The Python launcher starts FastAPI and Vite with a temporary SQLite database.
The JavaScript driver imports the project-scoped playwright-core, launches a
separate headless Chromium, clicks Check connection, selects all five
intervals, inspects candles and compares visible time/OHLCV/completion to backend
snapshots derived from stored observations. It exercises same-minute replacement,
rollover, source age and disconnected feed with a connected chart socket.
Desktop and mobile screenshots and report.json are saved. Services, browser
and temporary data are cleaned up. No test endpoints are added to the app.

Default data is explicitly labeled CONSTRUCTED replay / test_data=true. Receipt
and source times are fixed for replay, and the aggregation's evaluation time
advances to verify forming/ended transitions. Real source age continues to
advance in the UI; replay quotes correctly appear stale. The JSON report saves
source observations, receipt audit and per-phase aggregation snapshots.

Final result: **PASS**. Screenshots were visually inspected, including the
first streamed data, changed volume, prior ended candle, daily unknown volume,
disconnected feed and mobile chart. One socket-count test correction excluded
Vite HMR; visual review found and fixed the initial empty-chart viewport issue.
See [verification.md](verification.md) for the failures and reruns.

Results: [report.json](screenshots/ui-smoke-2026-11-10/report.json),
[desktop](screenshots/ui-smoke-2026-11-10/disconnected-desktop.png),
[mobile](screenshots/ui-smoke-2026-11-10/mobile.png),
[daily](screenshots/ui-smoke-2026-11-10/timeframe-1d.png).

## Actual Yahoo browser check

```bash
PYTHONPATH=backend/.packages /usr/bin/python -m scripts.ui_smoke --live --output /tmp/arbitrade-ui-live-results
```

The November 10 evening attempt displayed the connection result, real source
metadata and an empty regular-session chart. AAPL 348.16 at source time
2026-11-11T01:38:20+00:00 (November 10 at 8:38:20 PM Eastern) was stored, but
was outside the regular session. Result: **PENDING**, not PASS. Its screenshot
and report are in docs/screenshots/ui-live-2026-11-10. Rerun during a regular
session to complete the actual live candle-to-screen comparison.

A completed command can report PENDING in report.json when no in-session
candle arrives; examine that result field rather than treating exit 0 as a UI
pass. Assertion failures return nonzero and save failure evidence.
