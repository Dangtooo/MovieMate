# MovieMate automated tests

The suite runs offline against temporary SQLite databases. It does not require a
running web server, Google account, Gemini/TMDB API keys, or an Ollama instance.

## Install and run

From the project root in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

For a new checkout, create the virtual environment first with `python -m venv .venv`.
The test configuration sets its own signing key and in-memory application database
before importing the backend, so a local `.env` is not required. Query fixtures
use a separate temporary SQLite file with rollback between cases.

Coverage, including the full backend (also the seed module):

```powershell
.\.venv\Scripts\python.exe -m pytest --cov=backend --cov-report=term-missing --cov-report=html
```

Open `htmlcov/index.html` to inspect uncovered lines. Coverage is code execution,
not a measure of recommendation relevance or production readiness.

## Test groups

| File | Behavior checked |
| --- | --- |
| `test_api.py` | Catalog, authentication, review ownership, watchlists, origin checks, rate limits |
| `test_sqlite.py` | Exact JSON genre matching, foreign-key cascades, UTC detail-cache timestamps |
| `test_trailers.py` | Vietnamese/English/original-language fallback and official trailer preference |
| `test_chat_adk.py` | Existing tool, ranking, ADK Runner, grounding and upstream-error regressions |
| `test_chat_contract.py` | Current chat JSON/headers, request validation, signed guest ownership, login/logout isolation, selected IDs, retry after failure, bounded memory |
| `test_chat_sessions.py` | Expiry using a fake clock, LRU eviction, busy capacity, per-session locking and release on exceptions |
| `test_adk_lifecycle.py` | Real ADK Runner with a scripted BaseLlm, tool corrections, model-call budget, history truncation, hidden thought handling, client cleanup, end-to-end HTTP/tool/SQLite flow |
| `test_tool_validation.py` | Invalid or contradictory model filter arguments rejected before retrieval |
| `test_tmdb_transport.py` | Mock HTTP response boundary, cache expiry/languages, sanitized failures, optional video failure |
| `test_container_start.py` | Render origin defaults, HTTPS cookie configuration, signing secret/port validation, optional seed and single-worker startup |

Run only the new ADK lifecycle checks:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_adk_lifecycle.py -v
```

## Isolation and scope

- `conftest.py` clears real service credentials before application imports and
  disables OpenTelemetry SDK export in the test process.
- Real synchronous/asynchronous HTTP transports and Requests are blocked. A test
  that forgets to mock retrieval fails instead of spending API quota.
- The FastAPI TestClient uses its in-process transport, so it still exercises
  routes, validation, cookies, dependencies, middleware and responses.
- Conversation stores, rate limits and TMDB caches are reset for every test.
- ADK lifecycle tests execute the actual pinned ADK `Agent`/`Runner` and function
  tools; only the model and TMDB boundary are simulated. Tests that mock the
  entire `run_agent` function exercise service/API behavior separately.
- No test calls a live language model, validates live trailer playback, measures
  recommendation quality, or exercises browser layout. Those need separate
  integration/evaluation checks.
- The current Starlette TestClient emits a deprecation warning for its httpx
  integration. This warning is left visible and is not a test failure.
