# Vinbot — Defect Log

Central log of defects found through any test layer (unit, integration,
smoke, system, UAT). Empty until a real defect is found — no fabricated
entries.

| Defect ID | Found In (test/TC ID) | Severity | Description | Module | Status | Found By | Date Found | Fixed In |
|---|---|---|---|---|---|---|---|---|
| VB-001 | `backend/tests/smoke/smoke.py` — "Knowledge base loading" check | Medium | `backend/knowledge_db.pkl` (prose/RAG vector store) was not present in this local checkout (only `.bak`); `/api/health` correctly reported `knowledge_chunks: 0`. Structured/numeric answers were unaffected (SQLite store present, 10,838 facts); prose/policy answers had nothing to retrieve from. | Environment/data (not `app/*.py` code) | **Fixed** | Phase 3 test execution | 2026-07-26 | Phase 4 — restored from the validated `knowledge_db.pkl.bak` (7,565 chunks), then repaired a further real gap found during validation: the backup was missing the `Electricity_Department_Abbreviations.txt` glossary entirely (0 chunks). Ran `add_electricity_abbrev.py` to add it (146 chunks). Final: 7,711 chunks, all 3 glossary/RTS sources confirmed present. Re-verified: `/api/health` reports `knowledge_chunks: 7711`; a real grounded chat call ("What is the Late Payment Surcharge percentage?") correctly answered "1.25% per month... per the Compendium of Instructions dated 31.03.2023"; full pytest suite now 119/119 passed, 0 skipped (the previously-skipped shipped-KB test now runs and passes). |

Add further rows above this line as real defects are found; do not leave
placeholder rows once at least one real defect exists.

## Field definitions

- **Severity**: Critical (system unusable / wrong data served) / High
  (a documented requirement broken) / Medium (usability issue) / Low
  (cosmetic).
- **Status**: Open / In Progress / Fixed / Verified / Closed / Won't Fix.
- **Module**: the `app/*.py` file, frontend component, or deployment
  artifact affected.

## Severity guidance specific to Vinbot

Given the system's own safety principle ("never invent a figure" —
`app/config.py`'s `SYSTEM_PROMPT`), any defect where the bot **states an
incorrect figure or wrong district/row** must be logged as **Critical**
regardless of how minor it looks, since it directly contradicts the system's
core correctness guarantee (see `REQ-TABLES-05` /
`REQUIREMENT_TRACEABILITY_MATRIX.md`).
