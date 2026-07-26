# Vinbot — Smoke Tests

A standalone script (`smoke.py`) that validates a **real, running** Vinbot
instance over real HTTP. It does not use pytest and does not mock anything —
it is deliberately independent of the unit/integration suite (`../unit/`,
`../integration/`), which use mocks and never touch a live server.

## What it checks

| # | Check | How |
|---|---|---|
| 1 | FastAPI starts successfully | Launches uvicorn (with `--start-server`) and polls `/api/health`, or confirms an already-running target responds |
| 2 | Health endpoint | `GET /api/health` returns `200` with `status: "ok"` |
| 3 | Session creation | `POST /api/session` returns a non-empty `session_id` |
| 4 | Chat endpoint | `POST /api/chat` returns `200` with `Content-Type: text/event-stream` |
| 5 | SSE streaming | The response body contains well-formed SSE frames ending in `done` or `error` |
| 6 | SQLite availability | Opens `uhbvn_tables.db` and runs `PRAGMA integrity_check` (local targets only — skipped for a remote target unless `--db-path` is given) |
| 7 | Knowledge base loading | `knowledge_chunks` in the health response is `> 0` |
| 8 | Configuration validation | `chat_model` / `embed_model` are present in the health response |
| 9 | Reset endpoint | `POST /api/reset` returns `{"ok": true}` |
| 10 | Average response time | Averages `N` repeated health-check calls against a configurable threshold |

Every check reports **PASS**, **FAIL**, or **SKIP** (skip = genuinely not
checkable for this target, e.g. filesystem checks against a remote server —
never silently reported as a pass).

## Prerequisites

- The target instance must have a **real** `OPENAI_API_KEY` configured
  (check #4/#5 make a real OpenAI call through the app) — this script cannot
  and does not mock that.
- Python 3.11+ available to run the script (no extra pip packages required —
  it only uses the standard library).

## Usage

```bash
# Against an already-running local dev server (uvicorn already started separately)
cd backend
python tests/smoke/smoke.py

# Have the script start the server itself, test it, then shut it down
python tests/smoke/smoke.py --start-server

# Against a deployed environment
python tests/smoke/smoke.py --base-url https://dev-vinbot.vinbox.in
python tests/smoke/smoke.py --base-url https://uat-vinbot.vinbox.in
python tests/smoke/smoke.py --base-url https://vinbot.vinbox.in

# Tune thresholds / repeats
python tests/smoke/smoke.py --repeat 10 --threshold-ms 800

# Check a local uhbvn_tables.db copy while pointed at a remote target
python tests/smoke/smoke.py --base-url https://uat-vinbot.vinbox.in --db-path ../backend/uhbvn_tables.db
```

Exit code is `0` if every check PASSed (SKIPs don't fail the run), `1` if any
check FAILed — safe to use as a CI/deployment gate.

## Report

Every run writes `reports/smoke-test-report.md` (relative to the project
root) with the real PASS/FAIL/SKIP outcome, measured durations, and detail
message for each check — regenerated fresh on every run, never hand-edited.
