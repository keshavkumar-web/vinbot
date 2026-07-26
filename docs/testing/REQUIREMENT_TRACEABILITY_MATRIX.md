# Vinbot — Requirement Traceability Matrix (RTM)

Every requirement below is drawn from actual, observable behavior in the
Vinbot codebase (an endpoint contract, a documented routing rule, a safety
guarantee stated in a module's own docstring) — none are invented. Every test
listed actually exists in `backend/tests/`.

**Execution Status** is filled in from a real run, never assumed. See
`reports/test-summary-report.md` and `reports/junit.xml` for the run this
matrix's status column reflects. A status of `Not Run` means the suite has
not yet been executed since this matrix was last updated.

**Last executed**: 2026-07-26, this environment (updated after Phase 4's
knowledge-base restoration) — `pytest`: **119/119 passed, 0 skipped**;
`Newman`: 17/17 assertions passed; `smoke.py`: **10/10 checks passed**. The
`knowledge_db.pkl` gap that previously caused 1 pytest skip and 1 smoke FAIL
(see VB-001 in `DEFECT_LOG_TEMPLATE.md`) has been fixed. Full detail:
`reports/test-summary-report.md`.

## API layer (app/main.py)

| Req ID | Requirement | Module | API | Test Case | Expected Result | Status |
|---|---|---|---|---|---|---|
| REQ-API-01 | Health endpoint reports liveness | app/main.py | GET /api/health | test_health.py::test_health_returns_ok_status | `status: "ok"`, HTTP 200 | Pass |
| REQ-API-02 | Health endpoint reports model config + KB size, incl. empty-KB edge case | app/main.py, app/rag.py | GET /api/health | test_health.py::test_health_reports_configured_models / ..._zero_chunks_on_empty_knowledge_base / ..._chunk_count_after_kb_loaded | Fields match app/config.py; 0 when KB empty | Pass |
| REQ-API-03 | Session creation returns a unique, non-empty session id | app/main.py, app/sessions.py | POST /api/session | test_session.py::test_create_session_returns_session_id / ..._returns_unique_ids | 200, distinct ids | Pass |
| REQ-API-04 | Reset clears history for a valid session; 404 for unknown | app/main.py | POST /api/reset | test_reset.py (all) | 200/`ok:true`, or 404 | Pass |
| REQ-API-05 | Chat rejects unknown session (404) and invalid/empty message (422) | app/main.py, app/schemas.py | POST /api/chat | test_chat_route.py::test_chat_unknown_session_returns_404 / ..._empty_message_returns_422 / ..._missing_fields_returns_422 | 404 / 422 as documented | Pass |
| REQ-API-06 | Chat streams the reply as SSE `token`/`done` frames with anti-buffering headers | app/main.py | POST /api/chat | test_chat_route.py::test_chat_streams_tokens_then_done; test_streaming_integration.py | Correct frame sequence + headers | Pass |
| REQ-ERR-01 | A mid-stream exception yields an SSE `error` frame instead of crashing the connection | app/main.py | POST /api/chat | test_chat_route.py::test_chat_yields_error_frame_on_exception | Partial tokens + trailing `error` frame | Pass |

## Session handling (app/sessions.py)

| Req ID | Requirement | Module | API | Test Case | Expected Result | Status |
|---|---|---|---|---|---|---|
| REQ-SESS-01 | Each session's history is isolated by id | app/sessions.py | n/a (unit) | test_session.py::test_store_create_then_exists / ..._returns_empty_history_for_new_session | New session -> empty, isolated history | Pass |
| REQ-SESS-02 | Appended messages persist in order | app/sessions.py | n/a | test_session.py::test_store_append_adds_message | History reflects appended message | Pass |
| REQ-SESS-03 | `get()` returns a copy, not a live reference | app/sessions.py | n/a | test_session.py::test_store_get_returns_a_copy_not_a_live_reference | External mutation doesn't corrupt store | Pass |
| REQ-SESS-04 | History is trimmed to `MAX_HISTORY_MESSAGES` (sliding window) | app/sessions.py, app/config.py | n/a | test_session.py::test_store_trims_history_to_max_history_messages | Length capped, most recent kept | Pass |
| REQ-SESS-05 | Reset clears history but keeps the session id valid | app/sessions.py | n/a | test_session.py::test_store_reset_clears_history_but_keeps_session_id | `exists()` still true, history `[]` | Pass |

## Configuration (app/config.py)

| Req ID | Requirement | Module | API | Test Case | Expected Result | Status |
|---|---|---|---|---|---|---|
| REQ-CFG-01 | Process refuses to start without `OPENAI_API_KEY` | app/config.py | n/a (import-time) | test_config.py::test_missing_openai_api_key_raises_at_import | Non-zero exit, clear error message | Pass |
| REQ-CFG-02 | Env-var overrides apply for models/thresholds/CORS/history-window | app/config.py | n/a | test_config.py (override tests) | Reloaded module reflects overrides | Pass |

## Glossary (app/glossary.py)

| Req ID | Requirement | Module | API | Test Case | Expected Result | Status |
|---|---|---|---|---|---|---|
| REQ-GLOSS-01 | A definition question resolves deterministically from the glossary | app/glossary.py | (via POST /api/chat) | test_glossary.py::test_define_with_full_question_phrasing / ..._dash_style_entry | Exact definition text returned | Pass |
| REQ-GLOSS-02 | Unknown term / bare short abbreviation must NOT resolve (no false positive) | app/glossary.py | (via POST /api/chat) | test_glossary.py::test_define_unknown_term_returns_none / ..._bare_short_abbreviation_is_not_hijacked | `None` (defers to other routing) | Pass |
| REQ-GLOSS-03 | A category-list request returns every entry in that category | app/glossary.py | (via POST /api/chat) | test_glossary.py::test_list_category_returns_matching_entries / ..._no_match_returns_none | Full category list, or `None` | Pass |
| REQ-GLOSS-04 | A batch of definition questions resolves only if EVERY segment is known | app/glossary.py | (via POST /api/chat) | test_glossary.py::test_define_multi_batch_of_known_terms / ..._mixed_batch_with_unknown_term_returns_none | Joined answers, or `None` | Pass |

## Intent selection (app/intent.py)

| Req ID | Requirement | Module | API | Test Case | Expected Result | Status |
|---|---|---|---|---|---|---|
| REQ-INTENT-01 | The model never emits a value; malformed output fails CLOSED to `clarify` | app/intent.py | (via POST /api/chat) | test_intent.py::test_normalise_none_input_degrades_to_clarify / ...invalid_status... / test_extract_malformed_json_degrades_to_clarify / ..._empty_content... | Degrades to `clarify`, never a fabricated `answer` | Pass |
| REQ-INTENT-02 | Confidence/selection fields are robustly parsed and invalid entries dropped | app/intent.py | n/a | test_intent.py::test_normalise_non_numeric_confidence_defaults_to_zero / ..._string_confidence_is_coerced / ..._drops_selections_missing_dataset / ..._ignores_non_dict_selection_entries | Safe defaults, malformed entries dropped | Pass |
| REQ-INTENT-03 | The catalog shown to the model caps sample entities per dataset | app/intent.py | n/a | test_intent.py::test_render_catalog_limits_entities_shown | Entities list truncated to `max_entities` | Pass |

## Follow-up handling (app/followup.py)

| Req ID | Requirement | Module | API | Test Case | Expected Result | Status |
|---|---|---|---|---|---|---|
| REQ-FOLLOWUP-01 | A self-contained question is never rewritten using stale context | app/followup.py | (via POST /api/chat) | test_followup.py::test_is_self_contained | Correct True/False per case | Pass |
| REQ-FOLLOWUP-02 | Meta-questions and comparison questions are correctly classified | app/followup.py | (via POST /api/chat) | test_followup.py::test_is_meta_question_* / test_is_comparison_question_* | Correct classification | Pass |
| REQ-FOLLOWUP-03 | Comparisons are computed deterministically from grounded facts, never invented | app/followup.py | (via POST /api/chat) | test_followup.py::test_compare_facts_higher_lower / ..._difference / ..._returns_none_with_fewer_than_two_values | Correct comparison text, or `None` | Pass |
| REQ-FOLLOWUP-04 | An elliptical follow-up inherits only the dimension it doesn't name | app/followup.py, app/tables.py | (via POST /api/chat) | test_followup.py::test_resolve_followup_carries_over_entity_when_metric_named | Correct merged routing plan | Pass |
| REQ-FOLLOWUP-05 | Follow-up resolution defers safely (never guesses) when nothing resolvable or DB unavailable | app/followup.py | (via POST /api/chat) | test_followup.py::test_resolve_followup_returns_none_when_nothing_to_resolve / ..._returns_none_without_db | `None`, no crash | Pass |

## RAG / prose retrieval (app/rag.py)

| Req ID | Requirement | Module | API | Test Case | Expected Result | Status |
|---|---|---|---|---|---|---|
| REQ-RAG-01 | Cosine similarity scoring is correct and zero-vector-safe | app/rag.py | n/a | test_rag.py::test_cosine_similarity_* | Correct scores, no div-by-zero | Pass |
| REQ-RAG-02 | A multi-part question is split into sub-questions for retrieval | app/rag.py | (via POST /api/chat) | test_rag.py::test_split_questions_multi_part_turn / ..._single_question_stays_whole | Correct split / non-split | Pass |
| REQ-RAG-03 | Query expansion adds known abbreviation/consumer-phrase synonyms | app/rag.py | (via POST /api/chat) | test_rag.py::test_expand_query_* | Expansion added only when matched | Pass |
| REQ-RAG-04 | Circular-ID / RTS-service lexical lookups supplement vector search | app/rag.py | (via POST /api/chat) | test_rag.py::test_find_id_chunks_* / test_find_rts_chunks_* | Correct lexical hits | Pass |
| REQ-RAG-05 | Retrieved chunks are rendered with source attribution for the prompt | app/rag.py | n/a | test_rag.py::test_format_context_renders_source_and_text | `[Source: X]` prefix present | Pass |
| REQ-RAG-06 | Retrieval ranks the most relevant chunk first; empty KB returns nothing | app/rag.py | GET /api/health (KB size) | test_rag.py::test_retrieve_context_ranks_matching_chunk_first / ..._empty_knowledge_base_returns_empty_list | Correct top rank; `[]` on empty KB | Pass |
| REQ-RAG-07 | A multi-part turn's retrieval covers every sub-question, not just one | app/rag.py | (via POST /api/chat) | test_rag.py::test_retrieve_context_multi_covers_every_sub_question; test_knowledge_base_integration.py | Every sub-question's source represented | Pass |

## Structured / numeric retrieval (app/tables.py)

| Req ID | Requirement | Module | API | Test Case | Expected Result | Status |
|---|---|---|---|---|---|---|
| REQ-TABLES-01 | Numeric cell parsing handles thousands separators and leaked row-label letters | app/tables.py | n/a | test_tables.py::test_parse_number | Correct `(value, lead)` per case | Pass |
| REQ-TABLES-02 | Multi-row/merged PDF table headers are reconstructed into one column name | app/tables.py | n/a (ingestion) | test_tables.py::test_build_columns_reconstructs_split_header | Correct merged column names | Pass |
| REQ-TABLES-03 | An explicitly-named column wins over the aggregate; a bare quantity defaults to the aggregate | app/tables.py | (via POST /api/chat) | test_tables.py::test_snap_metric_* | Correct column resolution | Pass |
| REQ-TABLES-04 | A named district resolves; an unnamed one defaults to the utility-wide total | app/tables.py | (via POST /api/chat) | test_tables.py::test_find_entity_matches_named_district / ..._defaults_to_grand_total_when_no_place_named | Correct row(s) resolved | Pass |
| REQ-TABLES-05 | An unrecognised place is refused, NEVER substituted with another row (the original customer-reported bug) | app/tables.py | (via POST /api/chat) | test_tables.py::test_find_entity_refuses_unknown_place / ..._respond_unknown_place_returns_clarify_not_wrong_value; test_sqlite_integration.py::test_chat_never_serves_wrong_value_for_unknown_place | `[]` / `clarify`, never the Grand Total | Pass |
| REQ-TABLES-06 | `respond()` returns an exact, source-attributed value end-to-end; low confidence clarifies; missing DB / procedural questions fall back to prose | app/tables.py | POST /api/chat | test_tables.py::test_respond_returns_exact_value_with_provenance / ..._low_confidence_returns_clarify / ..._procedural_question_routes_to_prose... / ..._database_unavailable_falls_back_to_prose; test_sqlite_integration.py::test_chat_answers_from_real_sqlite_fact_store | Exact figure + provenance, or correct fallback | Pass |

## Router precedence (app/chat.py)

| Req ID | Requirement | Module | API | Test Case | Expected Result | Status |
|---|---|---|---|---|---|---|
| REQ-ROUTER-01 | A pending transformer clarification is resolved before any other routing | app/chat.py | POST /api/chat | test_chat_router.py::test_pending_transformer_clarification_resolved_first | Clarification answered first | Pass |
| REQ-ROUTER-02 | A glossary batch/category match short-circuits before RAG | app/chat.py | POST /api/chat | test_chat_router.py::test_glossary_batch_short_circuits_before_rag / ..._category_list_short_circuits | RAG never invoked | Pass |
| REQ-ROUTER-03 | A structured-table answer/clarify short-circuits before RAG | app/chat.py | POST /api/chat | test_chat_router.py::test_structured_table_answer_short_circuits_before_rag / ..._clarify_is_returned_without_rag | RAG never invoked | Pass |
| REQ-ROUTER-04 | A comparison question is answered deterministically, never by the LLM | app/chat.py | POST /api/chat | test_chat_router.py::test_comparison_question_answered_deterministically | Deterministic text, RAG never invoked | Pass |
| REQ-ROUTER-05 | A meta-question is answered from history alone, without a new lookup | app/chat.py | POST /api/chat | test_chat_router.py::test_meta_question_answered_from_history_without_rag | Answer derived from history only | Pass |
| REQ-ROUTER-06 | When nothing else matches, the turn falls through to grounded RAG generation | app/chat.py | POST /api/chat | test_chat_router.py::test_falls_through_to_rag_when_nothing_else_matches | RAG path produces the reply | Pass |

## Integration (real app + real SQLite/pickle, OpenAI mocked)

| Req ID | Requirement | Module | API | Test Case | Expected Result | Status |
|---|---|---|---|---|---|---|
| REQ-INT-01 | Full session -> chat -> reset lifecycle works through the real API | app/main.py | full lifecycle | test_api_integration.py::test_full_session_chat_reset_lifecycle | All steps succeed in sequence | Pass |
| REQ-INT-02 | Chat on a non-existent session is rejected at the API layer | app/main.py | POST /api/chat | test_api_integration.py::test_chat_without_a_session_is_rejected | 404 | Pass |
| REQ-INT-03 | Health reflects the real config module's values | app/main.py, app/config.py | GET /api/health | test_api_integration.py::test_health_reflects_real_config_module | Values match `app.config` | Pass |
| REQ-INT-04 | Conversation history persists in the real, shared SessionStore | app/main.py, app/sessions.py | POST /api/chat | test_api_integration.py::test_conversation_history_flows_through_real_session_store | Store reflects the turn | Pass |
| REQ-INT-05 | A real SQLite fact store answers a real chat request end-to-end | app/tables.py, app/main.py | POST /api/chat | test_sqlite_integration.py (both tests) | Exact figure w/ provenance; unknown place safe | Pass |
| REQ-INT-06 | A real knowledge pickle loads and is reflected in health; a missing file degrades gracefully | app/rag.py | GET /api/health | test_knowledge_base_integration.py (all) | Correct chunk count; `[]` on missing file | Pass |
| REQ-INT-07 | The chat response is a genuine multi-frame stream with anti-buffering headers | app/main.py | POST /api/chat | test_streaming_integration.py | Frames arrive incrementally; headers correct | Pass |

## Postman / Newman (API contract, black-box)

| Req ID | Requirement | Module | API | Test Case | Expected Result | Status |
|---|---|---|---|---|---|---|
| REQ-PM-01 | Health, session, chat, reset all respond correctly against a live instance | app/main.py | all 4 endpoints | postman/Vinbot.postman_collection.json — "Health" / "Create Session" / "Chat - grounded question" / "Reset Session" | All `pm.test` assertions pass | Pass |
| REQ-PM-02 | Error handling: unknown session (404), invalid body (422) | app/main.py | POST /api/chat, /api/reset | postman/Vinbot.postman_collection.json — "Error Handling" folder | 404 / 422 as documented | Pass |

## Smoke (real running instance)

| Req ID | Requirement | Module | API | Test Case | Expected Result | Status |
|---|---|---|---|---|---|---|
| REQ-SMOKE-01 | A deployed instance starts, is healthy, and its core endpoints work within an acceptable response time | whole app | all | backend/tests/smoke/smoke.py (10 checks) | All checks PASS or SKIP (never silently faked) | **Pass — 10/10** (fixed in Phase 4; see VB-001 in `DEFECT_LOG_TEMPLATE.md` for the restoration this required) |

**Coverage check**: every test file listed above under `backend/tests/unit/`,
`backend/tests/integration/`, `backend/tests/smoke/`, and every request in
`postman/Vinbot.postman_collection.json`, appears against at least one
Requirement ID in this matrix.
