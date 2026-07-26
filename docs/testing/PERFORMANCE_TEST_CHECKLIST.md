# Vinbot — Performance Test Checklist

Vinbot has no formally specified performance SLA today (no load target is
documented anywhere in `DOCUMENTATION.md`/`ADMIN_MANUAL.md`). This checklist
covers what CAN be honestly checked against the real architecture, without
inventing a target that was never agreed. Known, architecturally-imposed
constraints are called out explicitly rather than glossed over.

## Known architectural constraints (not defects — documented design choices)

- [ ] Confirm each environment runs **exactly one Uvicorn worker**
      (`ps` / `systemctl status vinbot-<env>` — see `ADMIN_MANUAL.md` §10).
      This is required because sessions live in process memory
      (`app/sessions.py`) — running more than one worker would silently
      split users across incompatible session stores.
- [ ] Confirm retrieval is an in-process linear scan over the embedded
      chunks (`app/rag.py`) — there is no vector index; latency scales with
      knowledge base size.

## Response-time checks (via `backend/tests/smoke/smoke.py`)

- [ ] `GET /api/health` average response time recorded (`smoke.py`'s
      "Average response time" check) — baseline, not a guessed target.
- [ ] `POST /api/chat` first-token latency observed manually (time from
      request to the first SSE `token` frame) — no automated assertion
      exists for this (it depends on OpenAI's own latency, outside Vinbot's
      control), but it should be recorded per run for trend comparison.

## Concurrency

- [ ] Confirm FastAPI's sync `/api/chat` handler runs in a threadpool (per
      `DOCUMENTATION.md`'s note: "concurrency is fine on one worker... one
      slow OpenAI call does not block others") — verify with 2 concurrent
      manual chat requests that neither blocks the other's streaming.

## Resource usage

- [ ] Record process RSS memory at idle and after loading the full knowledge
      base (`knowledge_db.pkl` is ~100 MB on disk; `ARCHITECTURE.md` notes
      an additional ~45 MB for the cached embedding matrix on first
      multi-part query).
- [ ] Record `uhbvn_tables.db` size and confirm it fits comfortably in
      available disk/RAM for the target server.

## What this checklist deliberately does NOT claim

- No specific requests-per-second target — none has been set by Vinbox
  Martech or the customer. If RITES requires one, capture it as a
  requirement first, then extend this checklist with a load-test plan
  (e.g. k6/Locust) rather than fabricating a number here.
- No stress/soak test results — not yet executed; add real results here
  only after an actual run, never as a placeholder pass.
