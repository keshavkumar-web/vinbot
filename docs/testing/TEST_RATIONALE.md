# Vinbot — Test Rationale

Why each test file exists, which module it validates, and which SDLC stage
(per the RITES GeM assessment framework) it satisfies. Cross-reference with
`REQUIREMENT_TRACEABILITY_MATRIX.md` for the requirement-level detail and
`TEST_MATRIX.md` for the module-vs-stage coverage grid.

| Test file | Module validated | Why it exists | SDLC stage |
|---|---|---|---|
| `tests/unit/test_health.py` | `app/main.py` (`GET /api/health`) | The only liveness signal ops/monitoring has today (per `ADMIN_MANUAL.md` §3) — must be provably correct, including when the KB is empty | Unit |
| `tests/unit/test_session.py` | `app/main.py` (`POST /api/session`), `app/sessions.py` | Session identity is the foundation every other endpoint depends on; the sliding-window trim is a documented but previously untested invariant | Unit |
| `tests/unit/test_reset.py` | `app/main.py` (`POST /api/reset`) | Confirms the "New chat" UI action (see `USER_MANUAL.md`) behaves correctly, including the unknown-session error path | Unit |
| `tests/unit/test_chat_route.py` | `app/main.py` (`POST /api/chat`) | The SSE contract (`API_DOCUMENTATION.md`) is what the frontend (`frontend/src/api.js`) parses byte-for-byte; a framing regression breaks the UI silently | Unit |
| `tests/unit/test_config.py` | `app/config.py` | Config failures are the #1 real-world deploy failure mode (`ADMIN_MANUAL.md` §8 troubleshooting table: "Backend fails to start — missing OPENAI_API_KEY") — this is the only place that exact failure is exercised | Unit |
| `tests/unit/test_glossary.py` | `app/glossary.py` | Glossary answers bypass the LLM entirely for reliability; its caching behavior (module-level index) is a real correctness hazard if untested | Unit |
| `tests/unit/test_intent.py` | `app/intent.py` | Intent selection's core safety property ("never emit a value, fail closed") is exactly what prevents the customer-reported "wrong values from tables" defect (`CHANGES.md`) from recurring | Unit |
| `tests/unit/test_followup.py` | `app/followup.py` | Conversational context is the most complex, most failure-prone layer (per `CHANGES.md`'s 2026-07-01/07-02 release history); its deterministic slot-carry logic needs explicit regression coverage | Unit |
| `tests/unit/test_rag.py` | `app/rag.py` | The multi-part-question retrieval fix (`ARCHITECTURE.md` §7) was a real, previously-shipped bug fix (0/4 -> 4/4 recall) — this is now a permanent regression guard | Unit |
| `tests/unit/test_tables.py` | `app/tables.py` | This module exists specifically to fix the original "wrong column/wrong row" defect; its safety guarantees (never substitute an unknown place) are the highest-value thing to protect | Unit |
| `tests/unit/test_chat_router.py` | `app/chat.py` | The router's precedence order is subtle (12+ branches) and undocumented in code beyond comments; a reordering regression would silently change answer quality | Unit |
| `tests/integration/test_api_integration.py` | `app/main.py` + `app/chat.py` + `app/sessions.py` together | Unit tests mock collaborators individually; this proves the real wiring between them works end-to-end | Integration |
| `tests/integration/test_sqlite_integration.py` | `app/tables.py` + `app/main.py` | Proves the structured path's safety guarantee holds through the REAL HTTP+SQLite stack, not just the Python function call | Integration |
| `tests/integration/test_knowledge_base_integration.py` | `app/rag.py` + `app/main.py` | Proves the on-disk pickle format the app actually ships loads correctly, including the "file missing" failure mode operators hit in practice | Integration |
| `tests/integration/test_streaming_integration.py` | `app/main.py` (SSE transport) | The anti-buffering headers (`X-Accel-Buffering`, `Cache-Control`) only matter if the response is genuinely streamed — this proves it isn't buffered before returning | Integration |
| `postman/Vinbot.postman_collection.json` | Whole API, black-box | Validates the API contract from outside the process (as a real client/reverse-proxy would see it), independent of the Python test process | Integration |
| `backend/tests/smoke/smoke.py` | Whole running instance | The only check that exercises a REAL deployed process (real uvicorn, real OpenAI call, real response time) — everything else uses mocks by design | Smoke |
| `docs/testing/SYSTEM_TEST_PLAN.md` + `FUNCTIONAL_TEST_CASES.md` + `REGRESSION_TEST_CASES.md` + `E2E_TEST_CASES.md` | Whole application, scenario-level | Documents manually-executable, end-to-end functional scenarios that automated tests express in code but a human assessor can also run by hand | System |
| `docs/testing/PERFORMANCE_TEST_CHECKLIST.md` / `SECURITY_TEST_CHECKLIST.md` | Whole application, non-functional | Non-functional requirements (response time, secret handling, CORS) aren't exercised by functional tests and need their own checklist | System |
| `docs/testing/UAT_*.md` (5 files) | Whole application, business-facing | Confirms the system meets the actual business need (answering UHBVN questions correctly) from a non-technical reviewer's perspective | UAT |
