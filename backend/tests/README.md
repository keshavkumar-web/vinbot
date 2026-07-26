# Vinbot Backend — Test Suite

## Project test structure

```
backend/tests/
├── conftest.py              Shared fixtures (isolated env, mocked OpenAI, temp DB/KB)
├── unit/                    Fast, fully-mocked tests — one file per app/ module
│   ├── test_health.py         GET /api/health
│   ├── test_session.py        POST /api/session + SessionStore
│   ├── test_reset.py          POST /api/reset
│   ├── test_chat_route.py     POST /api/chat route contract (SSE framing, errors)
│   ├── test_config.py         app/config.py (incl. missing-key, env overrides)
│   ├── test_glossary.py       app/glossary.py
│   ├── test_intent.py         app/intent.py
│   ├── test_followup.py       app/followup.py
│   ├── test_rag.py            app/rag.py
│   ├── test_tables.py         app/tables.py
│   └── test_chat_router.py    app/chat.py routing precedence
├── integration/             Real FastAPI app + real SQLite/pickle, OpenAI mocked
│   ├── test_api_integration.py
│   ├── test_sqlite_integration.py
│   ├── test_knowledge_base_integration.py
│   └── test_streaming_integration.py
├── smoke/                   Standalone script against a REAL running instance
│   ├── smoke.py                (see smoke/README.md — independent of pytest)
│   └── README.md
└── generate_dashboard.py    Reads reports/junit.xml + coverage.xml -> reports/dashboard.{html,md}
```

Every test maps to at least one requirement in
`../../docs/testing/REQUIREMENT_TRACEABILITY_MATRIX.md`, and every test file's
purpose/SDLC stage is explained in `../../docs/testing/TEST_RATIONALE.md`.

## Prerequisites

- Python 3.11+ (the app itself requires `>= 3.10`; see `deploy/install-service.sh`)
- A virtual environment is recommended (matches the project's existing convention)

## Installing test dependencies

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # Windows (PowerShell: .venv\Scripts\Activate.ps1)
# source .venv/bin/activate       # macOS/Linux
pip install -r requirements.txt -r requirements-test.txt
```

No real `OPENAI_API_KEY` is required to run unit/integration tests —
`conftest.py` sets a dummy key and mocks every OpenAI call. A real key IS
required for `tests/smoke/smoke.py` against a live server (see
`smoke/README.md`) and for Newman (see `../../postman/README.md`).

## Running unit tests

```bash
cd backend
pytest -v tests/unit
```

## Running integration tests

```bash
cd backend
pytest -v tests/integration
```

## Running everything (unit + integration)

```bash
cd backend
pytest -v
```

`pytest.ini` marks tests `unit` / `integration` / `slow` — to run only one
marker: `pytest -m unit` / `pytest -m integration` / `pytest -m "not slow"`.

To speed up a full run across CPU cores (pytest-xdist, installed but not on
by default — see pytest.ini's comment on why): `pytest -n auto`.

## Running smoke tests

Smoke tests are a **separate, standalone script** — not part of the pytest
run — because they test a real running instance over real HTTP, not mocked
internals. See `smoke/README.md` for full usage; quick start:

```bash
cd backend
python tests/smoke/smoke.py --start-server
```

## Generating coverage

Coverage is generated **automatically on every `pytest` run** (configured in
`pytest.ini`'s `addopts` — see `.coveragerc` for source/omit rules), so
plain `pytest -v` already writes:
- `../reports/coverage.xml` (machine-readable, Cobertura format)
- `../reports/coverage-html/index.html` (browsable HTML report)
- a terminal summary (`--cov-report=term-missing`)

To generate coverage on its own, without the other report flags:
```bash
pytest --cov=app --cov-report=term-missing --cov-report=html:../reports/coverage-html
```

## Generating HTML reports

Also automatic on every `pytest` run: `../reports/pytest-report.html`
(via `pytest-html`, `--self-contained-html` so it needs no separate assets).

## Generating JUnit XML reports

Also automatic on every `pytest` run: `../reports/junit.xml` — this is what
CI systems (see `.github/workflows/test.yml`) and
`tests/generate_dashboard.py` both read.

## Regenerating the Test Execution Dashboard

After a pytest run (so `../reports/junit.xml` and `../reports/coverage.xml`
exist):
```bash
python tests/generate_dashboard.py
```
Writes `../reports/dashboard.html` and `../reports/dashboard.md` with the
real totals from that run — see the script's own docstring; it refuses to
run if the report files it needs aren't there yet, rather than guessing.
