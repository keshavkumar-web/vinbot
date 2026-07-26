# Vinbot — Security Test Checklist

Checks grounded in what the codebase and deployment docs actually implement
(`ADMIN_MANUAL.md` §9, `DOCUMENTATION.md` §13) — not a generic OWASP checklist
padded with items Vinbot doesn't claim to address.

## Secrets management

- [ ] `backend/.env` is `chmod 600` and owned by the environment's service
      account (`vinbot-dev`/`vinbot-uat`/`vinbot-prod`) on every deployed
      server — confirm via `ls -l`.
- [ ] `OPENAI_API_KEY` is never present in application logs
      (`journalctl -u vinbot-<env>`) or in `git`/version-control history.
- [ ] `.env` is listed in `.gitignore` (confirm it is not committed).
- [ ] Each environment (DEV/UAT/PROD) uses a **different** OpenAI API key —
      confirm no key is shared across environments.

## Network exposure

- [ ] The app server's Uvicorn port (8010/8020/8000 per environment) is
      reachable ONLY from that environment's edge/reverse-proxy tier, not
      directly from the internet (`ADMIN_MANUAL.md` §9).
- [ ] TLS is terminated at the edge for every public-facing domain
      (`dev-/uat-/vinbot.vinbox.in`); confirm no plain-HTTP endpoint is
      publicly reachable in UAT/PROD.

## CORS

- [ ] `ALLOWED_ORIGINS` (`app/config.py`) in production is set to the
      environment's own domain only — never `*` — confirm via
      `GET /api/health` response headers or server `.env` contents on a
      non-prod system you control.
- [ ] Automated: `tests/unit/test_config.py::test_allowed_origins_parses_comma_separated_list`
      confirms the parsing itself is correct; this checklist item confirms
      the deployed VALUE is correct, which a unit test cannot see.

## Input validation

- [ ] Automated: `POST /api/chat` rejects an empty message (422) —
      `tests/unit/test_chat_route.py::test_chat_empty_message_returns_422`.
- [ ] Automated: an unknown `session_id` is rejected (404), not silently
      creating a new session — `tests/unit/test_chat_route.py`,
      `tests/unit/test_reset.py`.
- [ ] Manual: attempt a very large `message` payload; confirm
      `client_max_body_size` (Nginx, `deploy/nginx-vinbot-*.conf`, `5m`)
      rejects oversized bodies before they reach the app.

## Process privilege

- [ ] Each environment's systemd unit runs as its own **non-root** service
      account (`vinbot-dev.service` / `vinbot-uat.service` /
      `vinbot-prod.service`, `User=` line) — confirm via
      `systemctl show vinbot-<env> -p User`.

## Dependency hygiene

- [ ] `backend/requirements.txt` versions reviewed for known CVEs before a
      PROD deploy (currently unpinned — see `ADMIN_MANUAL.md`/gap analysis;
      pinning is a Phase 4/5 candidate, not fabricated as already done here).
- [ ] `postman/package.json` (`newman`) and any Node tooling reviewed the
      same way before use in CI.

## What this checklist deliberately does NOT claim

- No penetration test has been performed — this is a checklist for
  configuration/process hygiene, not a substitute for one.
- No WAF/rate-limiting is currently implemented anywhere in the stack;
  if required, it is a gap to raise, not a checkbox to tick here.
