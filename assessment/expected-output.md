# Expected Output — RITES GeM Assessment

Reference shape of a successful run for each command in
`terminal-commands.md`. The samples below are the REAL output captured on
**2026-07-26** the last time this framework was executed end-to-end in this
environment (see `reports/test-summary-report.md` for the authoritative,
always-current numbers) — if a live run differs, trust the live run and the
`reports/` directory over this file, and update this file from that run
afterward.

## `pytest -v`

Real tail of the actual run:

```
tests/unit/test_tables.py::test_respond_returns_exact_value_with_provenance PASSED [ 96%]
tests/unit/test_tables.py::test_respond_low_confidence_returns_clarify PASSED [ 97%]
tests/unit/test_tables.py::test_respond_unknown_place_returns_clarify_not_wrong_value PASSED [ 98%]
tests/unit/test_tables.py::test_respond_procedural_question_routes_to_prose_without_calling_extractor PASSED [ 99%]
tests/unit/test_tables.py::test_respond_database_unavailable_falls_back_to_prose PASSED [100%]

=========================== short test summary info ===========================
SKIPPED [1] tests/integration/test_knowledge_base_integration.py:50: backend/knowledge_db.pkl not present in this checkout
================= 118 passed, 1 skipped, 3 warnings in 2.94s ==================
```

Exit code `0`. Coverage table and report-file confirmations (`../reports/coverage-html`,
`../reports/coverage.xml`, `../reports/pytest-report.html`, `../reports/junit.xml`)
print just above that summary line.

## `npm run test:local` (Newman)

Real summary table from the actual run:

```
┌─────────────────────────┬───────────────────┬───────────────────┐
│                         │          executed │            failed │
├─────────────────────────┼───────────────────┼───────────────────┤
│              iterations │                 1 │                 0 │
│                requests │                 8 │                 0 │
│            test-scripts │                 8 │                 0 │
│      prerequest-scripts │                 0 │                 0 │
│              assertions │                17 │                 0 │
├─────────────────────────┴───────────────────┴───────────────────┤
│ total run duration: 3.2s                                        │
│ average response time: 326ms [min: 3ms, max: 2.5s, s.d.: 842ms] │
└─────────────────────────────────────────────────────────────────┘
```
(the 2.5s max is the real "Chat" request's live OpenAI call — everything
else responds in single-digit milliseconds)

## `python tests/smoke/smoke.py --start-server`

Real output — note this run genuinely found 1 failure (disclosed, not hidden):

```
[PASS] FastAPI starts successfully (2539 ms) - uvicorn came up and answered http://127.0.0.1:8000/api/health
[PASS] Health endpoint (2 ms) - 200 OK, status='ok'
[PASS] Session creation (16 ms) - session_id=51847ae737f0...
[PASS] Chat endpoint (2230 ms) - 200 OK, content-type=text/event-stream; charset=utf-8
[PASS] SSE streaming - 25 frame(s), ends with 'done'
[PASS] SQLite availability - uhbvn_tables.db OK, 10838 fact rows
[FAIL] Knowledge base loading - knowledge_chunks is 0 — knowledge_db.pkl missing or empty
[PASS] Configuration validation - chat_model='gpt-4o-mini', embed_model='text-embedding-3-small'; local .env present
[PASS] Reset endpoint (20 ms) - session cleared
[PASS] Average response time - avg=17 ms over 5 call(s) (min=14, max=23, threshold=1000.0 ms)

=== 9 passed, 1 failed, 0 skipped ===
Report written to .../reports/smoke-test-report.md
```
Exit code `1` (non-zero, because of the real FAIL above — see
`reports/test-summary-report.md` §3 for the root cause: `knowledge_db.pkl`
genuinely isn't present in this checkout).

## `python tests/generate_dashboard.py`

```
Wrote .../reports/dashboard.md
Wrote .../reports/dashboard.html
pytest: 118/119 passed, 62.89% coverage
```

## If output doesn't match

That's a real signal, not a formatting issue to paper over — check
`reports/junit.xml` / `reports/newman-junit.xml` directly, and log a defect
using `docs/testing/BUG_REPORT_TEMPLATE.md` if it's a genuine regression.
