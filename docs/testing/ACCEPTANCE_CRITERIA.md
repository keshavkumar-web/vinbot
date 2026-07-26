# Vinbot — Acceptance Criteria

Conditions that must hold for Vinbot to be considered ready for the RITES GeM
assessment / a given release. Each maps to a real, checkable artifact —
nothing here is aspirational without a way to verify it today.

| # | Criterion | Verified by |
|---|---|---|
| AC-01 | All automated unit tests pass | `reports/junit.xml` (0 failures) — run `pytest -v` |
| AC-02 | All automated integration tests pass | Same `reports/junit.xml`, `integration`-marked tests |
| AC-03 | Code coverage of `app/` meets or exceeds the recorded baseline | `reports/coverage.xml` / `reports/coverage-html/index.html` |
| AC-04 | Smoke tests pass against the target environment | `reports/smoke-test-report.md` (0 FAIL) |
| AC-05 | Postman/Newman collection passes against the target environment | `reports/newman-junit.xml` (0 failures) |
| AC-06 | Every requirement in the RTM has an Execution Status of Pass, or a documented, justified exception | `docs/testing/REQUIREMENT_TRACEABILITY_MATRIX.md` |
| AC-07 | No open Critical/High defect in `DEFECT_LOG_TEMPLATE.md` | Defect log for the release |
| AC-08 | UAT test cases executed with recorded results | `UAT_EXECUTION_SHEET.md` |
| AC-09 | Health endpoint reports `status: ok` and `knowledge_chunks > 0` on the target environment | Live `GET /api/health` |
| AC-10 | Security checklist items reviewed for the target environment | `SECURITY_TEST_CHECKLIST.md` |
| AC-11 | Documentation (README/INSTALL/API/USER/ADMIN manuals) matches the actual deployed behavior | Manual review against the live instance |

## Explicit non-goals (not acceptance blockers)

- A numeric performance/load SLA — none has been defined (see
  `PERFORMANCE_TEST_CHECKLIST.md`).
- 100% code coverage — not a stated target; the coverage % is tracked and
  reported, not gated at an arbitrary number.
- Customer/production sign-off — see `UAT_SIGNOFF_TEMPLATE.md`; this
  document uses placeholders and is completed by the customer, not fabricated
  here.
