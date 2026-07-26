# Vinbot — Deployment Gap Analysis

**Date**: 2026-07-26
**Scope**: DEV, UAT, PROD readiness, per `deploy/DEPLOY.md`.
**Method**: every item below was actually checked from this environment (file
existence, directory contents, live DNS resolution, dependency/tooling
presence) — nothing here is assumed. Items that genuinely cannot be checked
from a Windows workstation with no access to the target Linux servers are
marked accordingly rather than guessed.

**No fixes have been applied.** This is a read-only analysis.

> **Update (same day, Phase 4 execution)**: §4 (`knowledge_db.pkl`
> availability), §6 (frontend build readiness), and the frontend-related
> items in §2/§3 have since been resolved — the frontend was built and
> `knowledge_db.pkl` was restored and validated (7,711 chunks, all sources
> confirmed present). The root `.env` cleanup (§1) has also been applied.
> The remaining sections below (servers, DNS, per-environment secrets,
> firewall, Linux permissions, rollback procedure) are unchanged and still
> reflect the current, real state. See
> `docs/deployment/DEPLOYMENT_COMMANDS.md` and this session's final
> deployment readiness summary for the up-to-date picture.

---

## 1. Required files

| Item | Status | Evidence |
|---|---|---|
| `deploy/vinbot-dev.service` / `-uat` / `-prod` | PASS | All 3 present, reviewed in Phase 4 review |
| `deploy/nginx-vinbot-dev.conf` / `-uat` / `-prod` | PASS | All 3 present, ports match systemd units |
| `deploy/DEPLOY.md` | PASS | Present, step-by-step, covers all 3 environments |
| `backend/.env.example` | PASS | Present, documents required variables |
| `backend/requirements.txt` | PASS | Present (unpinned — out of scope for this phase per your decision) |
| `frontend/package.json` | PASS | Present, `build` script defined (`vite build`) |
| Per-environment `backend/.env` (dev/uat/prod, real per-env secrets) | BLOCKER | Do not exist. Only a single local-dev `backend/.env` exists (real key, meant for local dev only) |
| Root-level `.env` (unused duplicate secret) | WARNING | Present, contains a duplicate real `OPENAI_API_KEY`, never read by the app (`config.py` resolves `.env` relative to `backend/app/`, not repo root). Approved for deletion, **not yet deleted** per your instruction to wait. |

## 2. Required directories

| Item | Status | Evidence |
|---|---|---|
| `backend/.venv/` (local dev only) | PASS | Present, created in Phase 3, has runtime + test deps installed |
| `frontend/node_modules/` | BLOCKER | Does not exist — `npm install` never run in this checkout |
| `frontend/dist/` | BLOCKER | Does not exist — `npm run build` never run; `app/main.py` degrades safely to API-only if absent, but the UI will not be served without it |
| `reports/` | PASS | Present (Phase 3 test artifacts) |
| `/opt/vinbot-dev`, `/opt/vinbot-uat`, `/opt/vinbot-prod` (target servers) | BLOCKER | Cannot be checked — no target Linux server exists/is reachable from here. Must be created per `deploy/DEPLOY.md` §1 on each provisioned host. |

## 3. Environment variables

| Item | Status | Evidence |
|---|---|---|
| `OPENAI_API_KEY` documented in `.env.example` | PASS | Present with clear instructions |
| `OPENAI_API_KEY` set locally (dev) | PASS | Present in `backend/.env`, verified working (Phase 3 live smoke test made a real successful OpenAI call) |
| Per-environment `OPENAI_API_KEY` (distinct key per env, per `deploy/DEPLOY.md` §3) | BLOCKER | Not created for DEV/UAT/PROD — no target servers exist yet to hold them |
| `ALLOWED_ORIGINS` per environment (should be each env's own HTTPS domain) | BLOCKER | Only the generic local-dev value exists (`http://localhost:5173,...`); DEV/UAT/PROD values (`https://dev-vinbot.vinbox.in` etc.) not yet set anywhere |
| Other tunables (`CHAT_MODEL`, `TOP_K`, etc.) | PASS | Have safe defaults in `app/config.py`; no environment-specific override is required to deploy |

## 4. `knowledge_db.pkl` availability

| Item | Status | Evidence |
|---|---|---|
| `backend/knowledge_db.pkl` in this checkout | BLOCKER | Confirmed absent (only `knowledge_db.pkl.bak` exists) — same finding as Phase 3's smoke test (`knowledge_chunks: 0`) |
| Impact if deployed as-is | — | Structured/numeric answers (SQLite-backed) would work; prose/policy-circular answers would return "could not find" for everything, since there would be nothing to retrieve |
| Recovery path documented | PASS | `README.md` / `ADMIN_MANUAL.md` §6 document rebuilding via `python knowledge_maker.py`, or copying the real file from the existing production server |

## 5. SQLite database availability

| Item | Status | Evidence |
|---|---|---|
| `backend/uhbvn_tables.db` in this checkout | PASS | Present and verified live in Phase 3 — `PRAGMA integrity_check` OK, 10,838 fact rows |
| Trust-gate metadata (`datasets` table) | PASS | Present; structured answers verified working end-to-end in Phase 3 |

## 6. Frontend build readiness

| Item | Status | Evidence |
|---|---|---|
| Node.js / npm available (this workstation) | PASS | Node v22.19.0, npm 10.9.3 confirmed |
| Node.js / npm available (target servers) | BLOCKER | Cannot verify — no target servers exist. `deploy/DEPLOY.md` prerequisites call for Node 20+ |
| `frontend/dist/` actually built | BLOCKER | Not built (see §2) — one command away (`npm ci && npm run build`) but not yet done |

## 7. Backend startup readiness

| Item | Status | Evidence |
|---|---|---|
| `uvicorn app.main:app` starts cleanly with a valid key | PASS | Verified live in Phase 3 (`--start-server` smoke test, healthy in 2.5s) |
| Fails loudly without a key (correct fail-fast behavior) | PASS | Verified in Phase 3 unit test (`test_missing_openai_api_key_raises_at_import`) |
| Single-worker constraint respected in all 3 systemd units | PASS | All three units specify `--workers 1` |
| Target-server Python 3.11+ available | BLOCKER | Cannot verify — no target servers exist. `deploy/DEPLOY.md` prerequisites call for Python 3.11+ (app requires >= 3.10) |

## 8. SSL certificate requirements

| Item | Status | Evidence |
|---|---|---|
| Documented approach (shared wildcard `*.vinbox.in`, per existing UHBVN prod topology) | PASS | Clearly documented in `DOCUMENTATION.md` §2 and `deploy/DEPLOY.md` §7 |
| Certificate actually covers the new `vinbot`/`dev-vinbot`/`uat-vinbot` hostnames | WARNING | Not verifiable from here (no access to the edge server's certificate store). A wildcard `*.vinbox.in` cert *should* cover these by definition, but this must be confirmed operationally before go-live, not assumed |
| Certbot fallback path (per-domain cert) documented | PASS | `deploy/DEPLOY.md` §7 covers this alternative |

## 9. DNS requirements

| Item | Status | Evidence |
|---|---|---|
| `vinbox.in` resolves | PASS | Live lookup: `152.52.69.53` |
| `uhbvn.vinbox.in` resolves (existing, unrelated prod reference point) | PASS | Live lookup: `152.52.69.22` (confirms the domain/DNS zone is real and active) |
| `vinbot.vinbox.in` (PROD) resolves | **BLOCKER** | Live lookup performed: **"DNS name does not exist"** — no A record exists yet |
| `uat-vinbot.vinbox.in` (UAT) resolves | **BLOCKER** | Live lookup performed: **"DNS name does not exist"** |
| `dev-vinbot.vinbox.in` (DEV) resolves | **BLOCKER** | Live lookup performed: **"DNS name does not exist"** |

## 10. Firewall / required ports

| Item | Status | Evidence |
|---|---|---|
| Documented port plan (8010/8020/8000 internal; 80/443 public at the edge) | PASS | Consistent across systemd units, nginx configs, and `DOCUMENTATION.md` |
| Internal app-server port reachable ONLY from the edge tier (security requirement, `SECURITY_TEST_CHECKLIST.md`) | BLOCKER | Cannot verify — no servers/security groups exist yet to configure or check |
| Public 80/443 open at the edge for the new hostnames | BLOCKER | Cannot verify — depends on the (unprovisioned) edge server's firewall/security-group rules |

## 11. Linux user permissions

| Item | Status | Evidence |
|---|---|---|
| Per-environment service accounts (`vinbot-dev`, `vinbot-uat`, `vinbot-prod`) | BLOCKER | Do not exist anywhere — no Linux server to create them on. Creation command documented (`deploy/DEPLOY.md` §1) |
| Non-root execution enforced in systemd units | PASS | All 3 units specify `User=`/`Group=` as the environment's own account, never root |
| `.env` file permission plan (`chmod 600`, owned by service account) | PASS | Documented in `deploy/DEPLOY.md` §3 and `SECURITY_TEST_CHECKLIST.md`; cannot be verified until a real file/server exists |

## 12. Log directory readiness

| Item | Status | Evidence |
|---|---|---|
| Application logs (stdout -> journald via systemd) | PASS | No dedicated log directory needed — `journalctl -u vinbot-<env>` is the documented mechanism (`ADMIN_MANUAL.md` §2), works out of the box on any systemd host |
| Nginx access/error logs | PASS | Default `/var/log/nginx/` locations, no custom directory required |
| Log rotation / retention policy | WARNING | Not configured beyond OS/journald defaults — already flagged as a gap in the Phase 1 audit; not a blocker to deploying, but a real operational gap |
| Centralized log aggregation | WARNING | None exists (confirmed in Phase 1 audit) — acceptable for an initial deployment, a real gap for production support at scale |

## 13. Backup requirements

| Item | Status | Evidence |
|---|---|---|
| Manual backup guidance for `.env` / `knowledge_db.pkl` / `uhbvn_tables.db` | PASS | Documented in `ADMIN_MANUAL.md` §7 |
| Automated/scheduled backup job | WARNING | None exists (explicitly disclosed in `ADMIN_MANUAL.md` §7 as "no automated backup exists today") — acceptable to launch with manual discipline, but a real gap |
| Database/knowledge-store backup verified restorable | WARNING | Never tested (no backup has been taken yet, since no environment exists) |

## 14. Rollback prerequisites

| Item | Status | Evidence |
|---|---|---|
| Rollback procedure for the CURRENT 3-environment `deploy/DEPLOY.md` | **BLOCKER** | **No rollback section exists** in `deploy/DEPLOY.md` (checked directly) — it has an "Updating later" section but no documented "if the new build misbehaves, do X" step |
| Rollback procedure existed in the OLDER, single-server deployment guide (root `DEPLOY.md`, inherited baseline) | PASS (reference only) | That older guide DOES document a snapshot-before-update / restore-on-failure pattern (`backend/app.bak.$(date +%F)`) — a reasonable pattern to adapt, but it has not been carried into the new per-environment procedure |
| Versioned/tagged releases to roll back to | WARNING | No git repository exists for this project (confirmed in the Phase 1 audit) — rollback would depend on keeping dated release tarballs/directory copies, which is not yet formalized for the new environments |

---

## Summary

### 1. Deployment blockers (must resolve before any environment goes live)

1. No DEV/UAT/PROD servers provisioned (app dir, service account, ports, firewall — all depend on this).
2. DNS records missing for all 3 new hostnames (verified live: `vinbot.vinbox.in`, `uat-vinbot.vinbox.in`, `dev-vinbot.vinbox.in` all fail to resolve).
3. No per-environment `.env` files / secrets exist.
4. Frontend not built (`frontend/dist/` missing) — trivial to fix once a build environment exists, but blocking as-is.
5. `backend/knowledge_db.pkl` missing — deployable, but prose/policy answers would be non-functional until restored.
6. No rollback procedure defined for the new 3-environment deployment process.

### 2. Recommended deployment order

1. **DEV first** — lowest risk, validates the procedure itself (server provisioning, systemd, nginx, DNS, frontend build) end-to-end before touching anything customer-facing.
2. **UAT second** — only after DEV is confirmed healthy (smoke test + Newman passing against it) and the business/UAT test cases in `docs/testing/UAT_TEST_CASES.md` are ready to run.
3. **PROD last** — only after UAT sign-off (`docs/testing/UAT_SIGNOFF_TEMPLATE.md`) is completed, and only once the rollback gap (§14) has a defined procedure — not before.

### 3. Estimated deployment time

Assuming a server is already provisioned (OS installed, reachable) for each environment:

| Step | Estimate |
|---|---|
| Server packages + service account (§1 of `deploy/DEPLOY.md`) | 10–15 min |
| Copy project (`rsync`, incl. ~100MB `knowledge_db.pkl` once restored) | 10–20 min (network-dependent) |
| Backend venv + dependency install | 5–10 min |
| `.env` creation | 5 min |
| systemd service install + health check | 5 min |
| Frontend `npm ci && npm run build` | 5–10 min |
| Nginx config + reload | 5–10 min |
| DNS propagation wait (after adding the A record) | **Highly variable: minutes to a few hours** — not active work, but blocks final verification and certbot |
| HTTPS (certbot, if not covered by the existing wildcard) | 5 min (once DNS has propagated) |
| **Active hands-on time, per environment** | **~50–80 minutes** |
| **Wall-clock time, per environment (incl. DNS wait)** | **2–6 hours**, dominated by DNS propagation, not the deployment steps themselves |
| **All 3 environments, sequential, over multiple sessions** | **1–2 working days**, mostly waiting on DNS/approvals between stages, not continuous effort |

These are estimates for a deployment that goes smoothly; they exclude time to actually provision the servers themselves (outside this repo's control) and any UAT sign-off wait time.

### 4. Risk assessment

| Risk | Likelihood | Impact | Notes |
|---|---|---|---|
| Deploying without `knowledge_db.pkl` | High (if rushed) | High — prose answers silently become "could not find" for everything | Easy to catch: the smoke test's "Knowledge base loading" check already catches this (proven in Phase 3) |
| No rollback procedure and a bad deploy to PROD | Medium | High | This is the most significant process gap found in this analysis — recommend defining one before the PROD step specifically |
| DNS/cert misconfiguration causing an outage on cutover | Low–Medium | Medium | Mitigated by deploying DEV/UAT first and verifying the exact same procedure works before PROD |
| Reusing the local dev OpenAI key across environments | Medium (if rushed) | Medium — cost/quota bleed, harder incident attribution | `deploy/DEPLOY.md` already instructs against this explicitly |
| Unpinned `requirements.txt` pulling a breaking dependency update on a fresh install | Low–Medium | Medium | Explicitly out of scope for this phase per your instruction; flagged for future action |
| No automated backup before first deploy | Low | Medium | Manual backup guidance exists; acceptable for an initial launch if followed |

Overall: **no single blocker here is hard to fix** — they are all standard "day one" infrastructure/ops gaps (servers, DNS, secrets, one build command, one missing data file, one missing doc section), not architectural problems. The application and its testing framework (Phases 1–3) are in good shape; what's missing is entirely deployment-side.

### 5. Final Go / No-Go recommendation

**No-Go — today, as-is.** Six real blockers (§1) exist, three of them (DNS, servers, secrets) are infrastructure that must be provisioned outside this repository before any `deploy/DEPLOY.md` step can succeed at all.

**Conditional Go for DEV**, once:
- A DEV server is provisioned and reachable,
- `dev-vinbot.vinbox.in` DNS is created,
- a DEV-specific `.env` exists,
- `frontend/dist/` is built,
- `knowledge_db.pkl` is restored/rebuilt.

**UAT and PROD remain No-Go** until DEV has been validated end-to-end with this exact procedure, and — specifically for PROD — until a rollback procedure is documented and agreed (§14), given no such procedure exists today for the new 3-environment layout.
