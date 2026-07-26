# Vinbot — Functional Test Cases

Manually-executable versions of the automated scenarios in
`backend/tests/`, for a human tester without a Python environment. Execute
against DEV or UAT via the chat UI or `curl`/Postman. Record results in
`UAT_EXECUTION_SHEET.md` or a copy of this file per run.

| TC ID | Req ID | Title | Steps | Expected Result | Actual Result | Status |
|---|---|---|---|---|---|---|
| TC-FUNC-001 | REQ-API-01 | Health check | `GET /api/health` | HTTP 200, `status: "ok"` | | |
| TC-FUNC-002 | REQ-API-03 | Start a new chat | Open the app URL | Welcome message shown, no error banner (see `USER_MANUAL.md`) | | |
| TC-FUNC-003 | REQ-TABLES-06 | Ask a known numeric question | Ask "How many connections in Karnal?" | An exact figure with a `(Source: ..., Row: ..., Column: ...)` citation | | |
| TC-FUNC-004 | REQ-TABLES-05 | Ask about an unknown place | Ask "How many connections in Atlantis?" | A clarifying question — never a number | | |
| TC-FUNC-005 | REQ-GLOSS-01 | Ask a definition question | Ask "What is SDO?" | The abbreviation's definition, no citation needed | | |
| TC-FUNC-006 | REQ-RAG-06 | Ask a grounded policy question | Ask a question answerable from a loaded circular | A grounded answer, citing the circular/clause | | |
| TC-FUNC-007 | (system prompt rule 2) | Ask an out-of-KB question | Ask something not covered by any loaded document | The exact sentence: "I could not find this information in the knowledge base." | | |
| TC-FUNC-008 | (system prompt rule 5/6) | Ask an out-of-scope question | Ask "Who won the cricket match yesterday?" | A polite decline, no attempt to answer | | |
| TC-FUNC-009 | REQ-FOLLOWUP-04 | Follow-up resolution | Ask "connections in Karnal", then reply "Domestic" | The Domestic figure for Karnal, not a fresh clarification | | |
| TC-FUNC-010 | REQ-ROUTER-04 | Comparison follow-up | After two figures are shown, ask "which is higher?" | A deterministic comparison of the two values already shown | | |
| TC-FUNC-011 | REQ-API-06 | Streaming behavior | Ask any question and observe the reply | Text appears progressively (token-by-token), not all at once | | |
| TC-FUNC-012 | REQ-API-04 / REQ-SESS-05 | New chat / reset | Click "New chat" mid-conversation | History clears; a follow-up no longer resolves against the old context | | |
| TC-FUNC-013 | REQ-API-05 | Invalid request handling | Submit an empty message (if reachable via the API directly) | HTTP 422 | | |
| TC-FUNC-014 | REQ-CFG-01 | Missing configuration | (Admin-only, non-prod) Start the backend without `OPENAI_API_KEY` | Process refuses to start with a clear error | | |
| TC-FUNC-015 | REQ-INT-06 | Knowledge base loaded | `GET /api/health` | `knowledge_chunks` > 0 | | |
