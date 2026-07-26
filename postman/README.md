# Vinbot — Postman / Newman Integration Suite

`Vinbot.postman_collection.json` exercises the real API contract documented in
`../API_DOCUMENTATION.md`: session lifecycle, chat (incl. SSE headers/frame
shape), reset, health, and error handling (unknown session, invalid body).

## Prerequisites

- **Node.js 18+** and npm.
- The target instance must be reachable and have a real `OPENAI_API_KEY`
  configured server-side (the "Chat" request makes a real chat call).

## Install

```bash
cd postman
npm install
```

## Run with the Postman GUI

Import `Vinbot.postman_collection.json` and whichever
`Vinbot-<env>.postman_environment.json` you need, select that environment,
then **Run** the collection (Collection Runner). All requests run in
top-to-bottom order — `Create Session` must run before `Chat`/`Reset`, which
the Collection Runner does by default.

## Run headlessly with Newman

```bash
npm run test:local     # http://localhost:8000
npm run test:dev       # https://dev-vinbot.vinbox.in
npm run test:uat       # https://uat-vinbot.vinbox.in
npm run test:prod      # https://vinbot.vinbox.in
```

Each script runs the full collection and writes, into the project's shared
`reports/` directory:
- `reports/newman-report.html` — HTML report (`newman-reporter-htmlextra`)
- `reports/newman-junit.xml` — JUnit XML (consumed by
  `backend/tests/generate_dashboard.py` and `.github/workflows/test.yml`)
- a `cli` summary printed to the terminal

Exit code is non-zero if any request's tests failed — safe to use as a CI gate.

## Adding a new environment

Copy an existing `Vinbot-<env>.postman_environment.json`, change `name` and
the `baseUrl` value, and add a matching `test:<env>` script to `package.json`.
