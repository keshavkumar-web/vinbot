# Vinbot — Regression Test Cases

These guard specific defects/behaviors already fixed and documented in
`CHANGES.md` and `ARCHITECTURE.md` — the highest-value regressions to catch,
since each was a real, previously-shipped bug. Automated coverage is noted;
run the full automated suite (`pytest`) as the primary regression gate, and
these manual cases as a supplementary check against a live environment.

| TC ID | Regression guarded | Automated coverage | Manual check | Status |
|---|---|---|---|---|
| TC-REG-001 | Wrong column served for "how many connections" (original customer-reported defect — see `CHANGES.md` "the problem") | `tests/unit/test_tables.py::test_respond_returns_exact_value_with_provenance` | Ask "how many connections in Karnal" — must return the Total column value, not Domestic | |
| TC-REG-002 | Unknown place silently substituted with the Grand Total | `tests/unit/test_tables.py::test_respond_unknown_place_returns_clarify_not_wrong_value`, `tests/integration/test_sqlite_integration.py::test_chat_never_serves_wrong_value_for_unknown_place` | Ask about a nonexistent district — must clarify, never return the utility-wide total | |
| TC-REG-003 | Multi-part prose questions starved of grounding (0/4 -> 4/4 recall fix, `ARCHITECTURE.md` §7) | `tests/unit/test_rag.py::test_retrieve_context_multi_covers_every_sub_question` | Ask a 2-3 part compound policy question — every part should be grounded, not just the first | |
| TC-REG-004 | Follow-up losing the pinned dataset/metric across a chain (`CHANGES.md` 2026-07-01) | `tests/unit/test_followup.py::test_resolve_followup_carries_over_entity_when_metric_named` | "Domestic connections in Ambala" -> "Total?" -> "Load?" chain stays on the right subject each step | |
| TC-REG-005 | Transformer "failure rate" ambiguity (damage rate vs count, `CHANGES.md` 2026-07-05) | covered by `app/chat.py` transformer-rate branch (see `tests/unit/test_chat_router.py` router precedence tests) | Ask "transformer failure rate in Kurukshetra" — must resolve to the damage-rate figure, not "could not find" | |
| TC-REG-006 | A single-term definition question hijacked into a numeric clarify (`CHANGES.md` 2026-07-05) | `tests/unit/test_glossary.py::test_define_bare_short_abbreviation_is_not_hijacked` and related | Ask "what is PT?" right after a numeric conversation — must give the definition, not "which circle?" | |
| TC-REG-007 | Organisation-identity questions ("what is UHBVN?") wrongly refused (`CHANGES.md` 2026-07-02) | covered by `app/config.py` `SYSTEM_PROMPT` rule 1a (behavioral; exercised via live/UAT smoke, not mocked unit test) | Ask "what is UHBVN?" — must answer with the full form, never "could not find" | |
| TC-REG-008 | Session history bleeding across sessions | `tests/unit/test_session.py` (isolation tests) | Open two browser tabs (two sessions); confirm follow-ups in one never use the other's context | |
