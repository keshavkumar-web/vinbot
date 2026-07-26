# Terminal Commands — RITES GeM Assessment

Run in this order. All paths are relative to the `Vinbot/` project root.

## Setup (once, before the assessment)

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # Windows (PowerShell: .venv\Scripts\Activate.ps1)
pip install -r requirements.txt -r requirements-test.txt
cd ../postman
npm install
cd ..
```

## Scenario 1 — Unit testing

```bash
cd backend
pytest -v
```

## Scenario 2 — Integration testing (Newman)

```bash
cd postman
npm run test:local
```

(swap `test:local` for `test:dev` / `test:uat` / `test:prod` if demoing
against a deployed environment instead of localhost)

## Scenario 3 — System testing

```bash
# 1. confirm the target is healthy
curl http://localhost:8000/api/health

# 2. (in the browser) ask the live scenarios from docs/testing/E2E_TEST_CASES.md

# 3. show the generated Test Summary Report
cat ../reports/test-summary-report.md
```

## Supplementary — smoke testing

```bash
cd backend
python tests/smoke/smoke.py --start-server
```

## Supplementary — regenerate the dashboard

```bash
cd backend
python tests/generate_dashboard.py
```

## Supplementary — everything in one pass (what CI runs)

```bash
cd backend && pytest -v && python tests/generate_dashboard.py
cd ../postman && npm run test:local
```
