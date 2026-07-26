# Vinbot — End-to-End Test Cases

Full user journeys through the real UI + API together, as a user or assessor
would actually experience them. Automated equivalents exist at the
integration level (`backend/tests/integration/`) for the API side; these
scenarios add the browser/UI layer manual verification a Python test cannot
perform (see `USER_MANUAL.md` for the UI behavior referenced below).

| TC ID | Scenario | Steps | Expected Result | Status |
|---|---|---|---|---|
| TC-E2E-001 | First-time visitor asks a grounded question | 1. Open the app URL. 2. Wait for the welcome message. 3. Type "What documents are required for a new domestic connection?" and send. | Session created silently; reply streams in Markdown-formatted, grounded text | |
| TC-E2E-002 | Numeric lookup with citation | Ask "How many domestic connections in Karnal?" | Exact figure + source citation, matches `FUNCTIONAL_TEST_CASES.md` TC-FUNC-003 | |
| TC-E2E-003 | Multi-turn follow-up conversation | 1. "Count in Ambala" 2. Reply "Domestic" when asked which count 3. Ask "and for Jhajjar?" | Each turn correctly narrows/updates using prior context (see `REGRESSION_TEST_CASES.md` TC-REG-004) | |
| TC-E2E-004 | Comparison across two turns | After two district figures are shown, ask "which is higher?" | Deterministic comparison naming both districts and values | |
| TC-E2E-005 | Ungrounded question refusal | Ask something no loaded document covers | Exact refusal sentence, no fabricated figure | |
| TC-E2E-006 | Out-of-scope refusal | Ask an unrelated general-knowledge question | Polite decline, on-topic redirection | |
| TC-E2E-007 | New chat resets context | 1. Have a multi-turn conversation. 2. Click "New chat". 3. Ask a bare follow-up like "Domestic" alone. | The bot cannot resolve the follow-up (no prior context) — treated as a fresh, ambiguous question | |
| TC-E2E-008 | Connection failure handling | Stop the backend, then reload the UI | "Could not reach the backend" banner shown, not a blank/broken page (see `USER_MANUAL.md` troubleshooting table) | |
| TC-E2E-009 | Streaming is genuinely incremental | Ask any longer question and watch the reply render | Text appears progressively, not as one instantaneous block | |
| TC-E2E-010 | Health/monitoring surface | `GET /api/health` while the UI is in active use | Reports `status: ok` and a stable `knowledge_chunks` count throughout | |

**Automated coverage**: TC-E2E-001/002/007/009/010 have direct API-level
equivalents in `backend/tests/integration/`; TC-E2E-003/004 in
`backend/tests/unit/test_followup.py` and `test_chat_router.py` (with mocked
collaborators) plus this manual UI-level pass; TC-E2E-005/006/008 depend on
either live model behavior or the browser UI and are **manual-only** —
correctly so, since they cannot be verified without a live key or a browser.
