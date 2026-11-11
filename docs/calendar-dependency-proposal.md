# Exchange calendar dependency — approved and installed

Prompt 7a requires actual exchange sessions, holidays, early closes, and UTC
offset changes. `exchange_calendars` 4.13.2 is now installed in backend/.packages.
The integration imports successfully and passes real session/calendar tests.
A missing package in a future environment yields HTTP 503 rather than guessed sessions.

Proposed project-local additions:

| Package | Version | Purpose |
| --- | --- | --- |
| exchange-calendars | 4.13.2 | Regular trading sessions and special close rules |
| pyluach | 2.3.0 | Required calendar date calculations |
| toolz | 1.2.0 | Required calendar utility functions |
| korean-lunar-calendar | 0.4.0 | Required calendar date calculations |

Official PyPI metadata confirms these versions support Python 3.14. The
calendar package requires Python >=3.10,<4 and advertises Python 3.14 support.
Existing project-local numpy 2.5.4, pandas 3.1.1, and tzdata 2026.6 satisfy its
remaining requirements. The three added dependencies have no extra runtime
requirements. Use --no-deps to preserve the existing numpy/pandas packages.

After approval create backend/requirements-calendar.txt with the four pins
above, then run from the project root:

```bash
PYTHONPATH=/tmp/arbitrade-pip-26.3.whl /usr/bin/python -m pip install --only-binary=:all: --no-deps --target backend/.packages --cache-dir /tmp/arbitrade-pip-cache --report /tmp/arbitrade-calendar-install.json -r backend/requirements-calendar.txt
```

Reuse the already hash-verified temporary pip 26.3 wheel and /usr/bin/python.
Target: ignored backend/.packages. Affected files: new
backend/requirements-calendar.txt, package files/metadata under backend/.packages,
and pip cache/report under /tmp. No system packages, virtual environment,
frontend manifests, or existing Python requirements change.

After installation verify imports and real session schedules against Nasdaq's
published 2026 calendar, then run the full history tests and HTTP checks using
`PYTHONPATH=backend/.packages` for the backend process.

Sources:
- https://pypi.org/project/exchange-calendars/4.13.2/
- https://github.com/gerrymanoim/exchange_calendars
- https://www.nasdaq.com/market-activity/stock-market-holiday-schedule


The user approved this installation through the approval question. All four
packages installed successfully. pip warned that the existing target bin
folder was preserved; no --upgrade replacement was requested. Library imports,
real calendar rules, all 39 tests, history HTTP requests, and proxy smoke checks
passed. Installed versions and exact outcomes are in docs/verification.md.
