# Readiness Checklist — RITES GeM Assessment

Run through this before the assessor arrives.

## Environment

- [ ] `backend/.venv` created and activated
- [ ] `pip install -r requirements.txt -r requirements-test.txt` completed with no errors
- [ ] `backend/.env` has a real `OPENAI_API_KEY`
- [ ] `backend/knowledge_db.pkl` and `backend/uhbvn_tables.db` present
- [ ] `postman/` has run `npm install`
- [ ] Node.js 18+ available (`node --version`)

## Dry run (do this the day before, not live)

- [ ] `cd backend && pytest -v` — passes, `reports/` populated
- [ ] `python tests/generate_dashboard.py` — dashboard regenerates without error
- [ ] `cd postman && npm run test:local` — passes against a locally-running instance
- [ ] `python tests/smoke/smoke.py --start-server` — all checks PASS or SKIP, none FAIL
- [ ] Open `reports/pytest-report.html`, `reports/coverage-html/index.html`,
      `reports/newman-report.html`, `reports/dashboard.html` — all render correctly

## Live demo readiness

- [ ] Screens from `screens-to-show.md` arranged and ready
- [ ] `docs/testing/RITES_DEMO_SCRIPT.md` reviewed
- [ ] Know where `docs/testing/REQUIREMENT_TRACEABILITY_MATRIX.md` and
      `reports/test-summary-report.md` are, in case the assessor asks for them directly
- [ ] A fallback plan if live network/OpenAI access is unavailable during the
      demo: fall back to Scenario 1 (unit tests, fully mocked, no network
      dependency) as the primary demonstration

## Honesty check (do not skip)

- [ ] Confirm `reports/test-summary-report.md` reflects an ACTUAL run from
      today or very recently — never present stale or hand-edited numbers
- [ ] Confirm the Defect Log (`docs/testing/DEFECT_LOG_TEMPLATE.md`) is
      up to date — if there are known open issues, be ready to speak to them
      directly rather than avoid the topic
