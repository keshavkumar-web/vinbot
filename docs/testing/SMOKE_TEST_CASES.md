# Vinbot — Smoke Test Cases

Manual companion to `backend/tests/smoke/smoke.py` (which automates all of
these against a real running instance). Use this table when demonstrating
smoke testing without running the script, or to sanity-check its output.

| TC ID | Check | Command / Action | Expected Result | Status |
|---|---|---|---|---|
| TC-SMOKE-001 | FastAPI starts successfully | Start uvicorn / open the environment URL | Process comes up without error | |
| TC-SMOKE-002 | Health endpoint | `curl {baseUrl}/api/health` | HTTP 200, `status: "ok"` | |
| TC-SMOKE-003 | Session creation | `curl -X POST {baseUrl}/api/session` | HTTP 200, non-empty `session_id` | |
| TC-SMOKE-004 | Chat endpoint | `curl -X POST {baseUrl}/api/chat` with a valid session/message | HTTP 200, `Content-Type: text/event-stream` | |
| TC-SMOKE-005 | SSE streaming | Observe the chat response body | Well-formed `data:` frames ending in `done` or `error` | |
| TC-SMOKE-006 | SQLite availability | On the app server: open `backend/uhbvn_tables.db` | File exists, `PRAGMA integrity_check` returns `ok` | |
| TC-SMOKE-007 | Knowledge base loading | `curl {baseUrl}/api/health` | `knowledge_chunks` > 0 | |
| TC-SMOKE-008 | Configuration validation | `curl {baseUrl}/api/health` | `chat_model` / `embed_model` populated | |
| TC-SMOKE-009 | Reset endpoint | `curl -X POST {baseUrl}/api/reset` with the session above | HTTP 200, `{"ok": true}` | |
| TC-SMOKE-010 | Average response time | Repeat the health check 5-10 times | Average within the agreed threshold (default 1000 ms in `smoke.py`) | |

**Automated equivalent**: `python backend/tests/smoke/smoke.py --base-url <env-url>`
(see `backend/tests/smoke/README.md`). The script's own
`reports/smoke-test-report.md` is authoritative; this table exists for a
manual/live-demo walkthrough only.
