# Screens to Show — RITES GeM Assessment

Have these ready in separate tabs/windows before starting.

## 1. Terminal — backend

Working directory: `Vinbot/backend`, virtual environment activated.
Used for: `pytest -v`, `python tests/smoke/smoke.py`, `python tests/generate_dashboard.py`.

## 2. Terminal — postman

Working directory: `Vinbot/postman`.
Used for: `npm run test:local` (or `test:dev`/`test:uat`).

## 3. Browser tab — the live chat UI

`http://localhost:8000` (local dev / demo instance) or
`https://uat-vinbot.vinbox.in` if the UAT environment is reachable.
Used for: Scenario 3 ("Show system testing") end-to-end questions.

## 4. Browser tab — pytest HTML report

`Vinbot/reports/pytest-report.html` (open after running `pytest -v`).

## 5. Browser tab — coverage HTML report

`Vinbot/reports/coverage-html/index.html`.

## 6. Browser tab — Newman HTML report

`Vinbot/reports/newman-report.html` (open after `npm run test:local`).

## 7. Browser tab — Test Execution Dashboard

`Vinbot/reports/dashboard.html`.

## 8. Editor tab — key documents

- `docs/testing/REQUIREMENT_TRACEABILITY_MATRIX.md`
- `reports/test-summary-report.md`
- `docs/testing/RITES_DEMO_SCRIPT.md`

## 9. Postman desktop app (optional, for the GUI alternative)

With `Vinbot.postman_collection.json` and the relevant
`Vinbot-<env>.postman_environment.json` already imported and selected.
