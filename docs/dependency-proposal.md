# Dependencies: current status and Yahoo proposal

## Completed

User-approved Vite security patch applied: 8.3.2 -> 8.3.7. Vue 3.5.45 and
Lightweight Charts 5.3.0 remain installed. npm audit now reports zero
vulnerabilities. Production build and HTTP proxy/recovery checks pass.
System Python is /usr/bin/python 3.14.8 with FastAPI 0.156.8 and Uvicorn 0.54.0.

## Yahoo dependencies — approved and installed

yfinance 1.8.0 and websockets 17.4 are installed in backend/.packages and
import successfully with PYTHONPATH=backend/.packages. System pip remains absent. The package database has no python-yfinance. Python is
externally managed. Reuse /usr/bin/python and install into project-local
backend/.packages; no virtual environment or system Python changes are proposed.

| Package/tool | Version | Purpose and compatibility |
| --- | --- | --- |
| yfinance | 1.8.0 | Yahoo AsyncWebSocket client; pure Python wheel; requires websockets >=13 |
| websockets | 17.4 | WebSocket transport; Python >=3.11; CPython 3.14 Linux x86_64 wheel available |
| pip | 26.3 | Temporary installer loaded from an official wheel in /tmp; Python >=3.10 |

PyPI metadata confirms compatible-looking Python 3.14/ABI3 or pure-Python
wheels for major transitive dependencies including numpy, pandas, curl_cffi,
lxml, peewee, and protobuf. Full binary-only resolution, installation, and imports passed.
Use binary wheels only; if resolution fails, stop and review rather than
building or changing versions without approval.

Created backend/requirements-yahoo.txt with the approved contents:

```text
yfinance==1.8.0
websockets==17.4
```

Run from /home/jlrj/Documents/arbitrade:

```bash
curl --fail --location --output /tmp/arbitrade-pip-26.3.whl https://files.pythonhosted.org/packages/07/25/ee8c38ae72d66b844ce8eb9711ba905dba21ca1a8a0c960057c41cd23337/pip-26.3-py3-none-any.whl
printf '%s  %s\n' f3b60b20ffaadd4415ed7957212a38ac63fa4c5fa375bd0f4a797777940fad13 /tmp/arbitrade-pip-26.3.whl | sha256sum --check -
PYTHONPATH=/tmp/arbitrade-pip-26.3.whl /usr/bin/python -m pip --version
PYTHONPATH=/tmp/arbitrade-pip-26.3.whl /usr/bin/python -m pip install --only-binary=:all: --target backend/.packages --cache-dir /tmp/arbitrade-pip-cache --dry-run --report /tmp/arbitrade-yahoo-plan.json -r backend/requirements-yahoo.txt
PYTHONPATH=/tmp/arbitrade-pip-26.3.whl /usr/bin/python -m pip install --only-binary=:all: --target backend/.packages --cache-dir /tmp/arbitrade-pip-cache --report /tmp/arbitrade-yahoo-install.json -r backend/requirements-yahoo.txt
```

The wheel is an importable zip archive used as a temporary installer; pip is
not installed into system Python. Verify the hash before running it. Target:
backend/.packages, including transitive dependencies and metadata. Files
created/changed: backend/requirements-yahoo.txt, ignored backend/.packages,
and the named installer, cache, and JSON reports under /tmp. No existing
Python or frontend manifests/lockfiles change. No sudo is needed.
The complete resolved and installed transitive versions are recorded in docs/verification.md.

Verified subscription command:

```bash
PYTHONPATH=backend/.packages /usr/bin/python -m backend.yahoo_stream --ticker AAPL --timeout 30
```

The command imports and prints installed versions, subscribes for at most
30 seconds plus up to five seconds of cleanup, prints one matching update,
and closes. It reports whether subscribe completed (socket opened and request
sent) separately from whether a price update was received. No Yahoo login or
watchlist is needed. The check opened a subscription and received an AAPL price update successfully;
see docs/verification.md for the observed values. The bounded subscription closed.

References: https://ranaroussi.github.io/yfinance/reference/yfinance.websocket.html
and official PyPI metadata for yfinance, websockets, and pip.


## Calendar dependency update

The user approved exchange-calendars 4.13.2 and its three missing dependencies.
They are installed project-locally; see docs/calendar-dependency-proposal.md
and backend/requirements-calendar.txt. No dependency proposal is pending.
