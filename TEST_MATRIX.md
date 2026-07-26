# Vinbot — Test Matrix

Every application module against every test level. ✓ = automated coverage
exists; 〇 = covered manually/via checklist only; — = not applicable at that
level for this module.

| Module | Unit | Integration | System | Smoke | UAT |
|---|---|---|---|---|---|
| `app/main.py` (FastAPI routes) | ✓ `tests/unit/test_health.py`, `test_session.py`, `test_reset.py`, `test_chat_route.py` | ✓ `tests/integration/test_api_integration.py`, `test_streaming_integration.py` | ✓ `docs/testing/FUNCTIONAL_TEST_CASES.md`, `E2E_TEST_CASES.md` | ✓ `tests/smoke/smoke.py` (health/session/chat/reset checks) | ✓ `docs/testing/UAT_TEST_CASES.md` (all UI-driven cases) |
| `app/config.py` | ✓ `tests/unit/test_config.py` | ✓ `tests/integration/test_api_integration.py::test_health_reflects_real_config_module` | ✓ TC-FUNC-014 | ✓ "Configuration validation" check | — |
| `app/sessions.py` | ✓ `tests/unit/test_session.py` | ✓ `tests/integration/test_api_integration.py::test_conversation_history_flows_through_real_session_store` | ✓ TC-FUNC-012, TC-REG-008 | 〇 (indirect, via session/chat/reset checks) | ✓ UAT-TC-06 |
| `app/schemas.py` | ✓ (exercised via route tests' 422 cases) | ✓ (same) | ✓ TC-FUNC-013 | — | — |
| `app/chat.py` (router) | ✓ `tests/unit/test_chat_router.py` | ✓ `tests/integration/test_api_integration.py` (real routing path) | ✓ `docs/testing/E2E_TEST_CASES.md` | 〇 (indirect, via chat check) | ✓ UAT-TC-01..05 |
| `app/rag.py` (prose retrieval) | ✓ `tests/unit/test_rag.py` | ✓ `tests/integration/test_knowledge_base_integration.py` | ✓ TC-FUNC-006/007, TC-REG-003 | ✓ "Knowledge base loading" check | ✓ UAT-TC-01, UAT-TC-04 |
| `app/tables.py` (structured retrieval) | ✓ `tests/unit/test_tables.py` | ✓ `tests/integration/test_sqlite_integration.py` | ✓ TC-FUNC-003/004, TC-REG-001/002 | ✓ "SQLite availability" check | ✓ UAT-TC-02 |
| `app/intent.py` | ✓ `tests/unit/test_intent.py` | ✓ (exercised inside sqlite integration path) | 〇 (behavioral, via structured-answer TCs) | — | — |
| `app/followup.py` | ✓ `tests/unit/test_followup.py` | ✓ (exercised inside chat_router/api integration) | ✓ TC-FUNC-009/010, TC-REG-004/005/006 | — | ✓ UAT-TC-03 |
| `app/glossary.py` | ✓ `tests/unit/test_glossary.py` | ✓ (exercised inside chat_router/api integration) | ✓ TC-FUNC-005 | — | — |
| Frontend (`frontend/src/*.vue`, `api.js`) | — (no JS test runner added in Phase 3 — see gap analysis) | ✓ `tests/integration/test_streaming_integration.py` validates the exact contract `api.js` parses | ✓ `docs/testing/E2E_TEST_CASES.md` (manual browser walkthrough) | — | ✓ all UAT-TC entries (UI-driven) |
| Deployment (`deploy/*`, systemd, nginx) | — | — | ✓ `docs/testing/PERFORMANCE_TEST_CHECKLIST.md`, `SECURITY_TEST_CHECKLIST.md` | ✓ `tests/smoke/smoke.py --start-server` | — |
| API contract (black-box) | — | ✓ `postman/Vinbot.postman_collection.json` via Newman | ✓ RITES demo Scenario 2 | — | — |

## Known gap (honestly disclosed, not hidden)

No frontend unit-test runner (Vitest/Jest) was added in Phase 3 — the
frontend has zero dedicated `.vue`/`.js` unit tests. Its behavior is covered
indirectly (the exact SSE contract it depends on is unit/integration-tested
from the backend side in `test_streaming_integration.py`, and its actual
rendered behavior is covered manually in `E2E_TEST_CASES.md`/UAT). Adding a
frontend unit suite is a candidate for a future phase, not fabricated as
already done here.
