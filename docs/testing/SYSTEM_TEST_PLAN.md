# Vinbot — System Test Plan

## 1. Objective

Verify that Vinbot (backend + frontend, as deployed to DEV/UAT/PROD per
`deploy/DEPLOY.md`) meets its functional and non-functional requirements as
an integrated system — beyond the unit/integration level already covered by
`backend/tests/`.

## 2. Scope

**In scope**: the FastAPI backend's 4 endpoints, the Vue chat UI, the
structured (SQLite) and prose (RAG) answer paths, conversational follow-up
handling, session lifecycle, and the deployment/health surface described in
`ADMIN_MANUAL.md`.

**Out of scope**: the correctness/completeness of UHBVN's underlying policy
documents (content accuracy of the source circulars themselves), load testing
at a defined RPS target (no such target has been specified — see
`PERFORMANCE_TEST_CHECKLIST.md`), and any environment Vinbox Martech does not
control (the assessor's own network, OpenAI's service availability).

## 3. Test levels covered by this plan

| Level | Document |
|---|---|
| Functional | `FUNCTIONAL_TEST_CASES.md` |
| Regression | `REGRESSION_TEST_CASES.md` |
| Smoke | `SMOKE_TEST_CASES.md` (manual companion to `backend/tests/smoke/smoke.py`) |
| Performance | `PERFORMANCE_TEST_CHECKLIST.md` |
| Security | `SECURITY_TEST_CHECKLIST.md` |
| End-to-end | `E2E_TEST_CASES.md` |
| Acceptance | `ACCEPTANCE_CRITERIA.md` |
| UAT | `UAT_PLAN.md` and related |

## 4. Environments

Per `DOCUMENTATION.md` §9: DEV (`dev-vinbot.vinbox.in`), UAT
(`uat-vinbot.vinbox.in`), PROD (`vinbot.vinbox.in`). System testing in this
document is intended to run against **DEV or UAT**, never PROD.

## 5. Entry criteria

- `pytest` (unit + integration) passes with 0 failures (see
  `reports/junit.xml`).
- The target environment's `/api/health` reports `status: "ok"` and
  `knowledge_chunks > 0`.
- `backend/tests/smoke/smoke.py` passes against the target environment.

## 6. Exit criteria

- All test cases in `FUNCTIONAL_TEST_CASES.md` and `E2E_TEST_CASES.md`
  executed with a recorded Pass/Fail result.
- Any Fail has a corresponding entry in `DEFECT_LOG_TEMPLATE.md`.
- `ACCEPTANCE_CRITERIA.md` items are all met, or explicitly waived with
  justification.

## 7. Roles

| Role | Responsibility |
|---|---|
| Test Executor | Runs the automated suite + manual test cases, records results |
| Technical Reviewer | Reviews failures, triages defects |
| Business Reviewer (UAT) | Confirms business-facing scenarios (see UAT docs) |

Names are intentionally left as roles, not individuals — see
`UAT_SIGNOFF_TEMPLATE.md` for where a real name/date is required and must not
be fabricated.

## 8. Deliverables

- `TEST_EXECUTION_REPORT` — see `reports/test-summary-report.md` (generated
  from a real run, not hand-written).
- `reports/dashboard.html` / `.md` — real pass/fail/coverage totals.
- Updated Execution Status column in `REQUIREMENT_TRACEABILITY_MATRIX.md`.
