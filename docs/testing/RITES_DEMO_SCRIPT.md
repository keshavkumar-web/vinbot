# Vinbot — RITES GeM Live Demonstration Script

A live-demo runbook: what to run, in what order, and what the assessor
should see. Every command below runs against the REAL implementation — none
of this is staged or faked.

## Pre-demo checklist (run once, before the assessor arrives)

- [ ] `backend/.venv` exists and has `requirements.txt` + `requirements-test.txt` installed.
- [ ] `backend/.env` has a real `OPENAI_API_KEY` (needed for the chat/smoke/Newman demos).
- [ ] `backend/knowledge_db.pkl` and `backend/uhbvn_tables.db` are present.
- [ ] `postman/` has run `npm install` at least once.
- [ ] `reports/` exists and is writable.
- [ ] A terminal is open at the project root, and a second at `Vinbot/backend/`.
- [ ] (Optional, for the UAT scenario) confirm `https://uat-vinbot.vinbox.in` is reachable, or be ready to demo against local dev instead.

## Scenario 1 — "Show unit testing"

```bash
cd Vinbot/backend
pytest -v
```
What the assessor sees: every test in `tests/unit/` and `tests/integration/`
running with a PASS/FAIL per test name (pytest.ini's `addopts` already runs
`-v`-equivalent detail plus coverage). This single command also
auto-generates, into `Vinbot/reports/`:
`junit.xml`, `pytest-report.html`, `coverage.xml`, `coverage-html/`.

Optional follow-up: open `../reports/pytest-report.html` and
`../reports/coverage-html/index.html` in a browser to show the HTML views.

## Scenario 2 — "Show integration testing"

```bash
cd Vinbot/postman
npm run test:local        # or test:dev / test:uat, matching whichever server is up
```
What the assessor sees: Newman running every request in
`Vinbot.postman_collection.json` (Health, Create Session, Chat, Reset, Error
Handling) with a pass/fail count printed to the terminal, and
`../reports/newman-report.html` / `../reports/newman-junit.xml` written.
Open the HTML report to show all APIs passing with response details.

Alternative (GUI): open Postman, import the collection + the relevant
environment file, select it, and click **Run** to show the Collection
Runner live.

## Scenario 3 — "Show system testing"

1. Open the UAT environment (or local dev if UAT isn't reachable):
   `https://uat-vinbot.vinbox.in`
2. Execute 2-3 end-to-end scenarios live from `E2E_TEST_CASES.md`, e.g.:
   - TC-E2E-002: "How many domestic connections in Karnal?" -> exact figure + citation.
   - TC-E2E-003: "Count in Ambala" -> reply "Domestic" -> correct follow-up resolution.
   - TC-E2E-005: an out-of-KB question -> the exact "could not find" sentence.
3. Show the Test Summary Report:
   ```bash
   cat Vinbot/reports/test-summary-report.md
   ```
   (or open it in an editor/browser) — this is generated from the actual
   last `pytest` + Newman + smoke run, not hand-written.

## Supplementary — smoke testing and the dashboard

```bash
cd Vinbot/backend
python tests/smoke/smoke.py --start-server
python tests/generate_dashboard.py
```
Shows the 10-point smoke check against a freshly-started instance, then
regenerates `../reports/dashboard.html`/`.md` from the real `junit.xml` +
`coverage.xml` produced moments earlier.

## If something fails during the demo

Do not hide it. Point to `DEFECT_LOG_TEMPLATE.md` / `BUG_REPORT_TEMPLATE.md`
and note that a real failure is exactly what these test layers exist to
catch — the value being demonstrated is that failures are visible and
traceable (`REQUIREMENT_TRACEABILITY_MATRIX.md`), not that failures never
happen.
