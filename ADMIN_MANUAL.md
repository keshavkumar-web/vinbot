# Vinbot — Administrator Manual

Operating guide for whoever runs a deployed Vinbot instance (DEV, UAT, or
PROD). For first-time installation, see `deploy/DEPLOY.md`; for the
architecture this manual assumes, see `DOCUMENTATION.md`.

## 1. Environments at a glance

| | DEV | UAT | PROD |
|---|---|---|---|
| Domain | `dev-vinbot.vinbox.in` | `uat-vinbot.vinbox.in` | `vinbot.vinbox.in` |
| systemd unit | `vinbot-dev.service` | `vinbot-uat.service` | `vinbot-prod.service` |
| App directory | `/opt/vinbot-dev` | `/opt/vinbot-uat` | `/opt/vinbot-prod` |
| Service account | `vinbot-dev` | `vinbot-uat` | `vinbot-prod` |
| Uvicorn port | `8010` | `8020` | `8000` |

Each environment is fully isolated: its own directory, service account, `.env`
file (and therefore its own OpenAI API key), knowledge base copy, and systemd
unit. Nothing is shared between them.

## 2. Day-to-day service control

```bash
sudo systemctl status  vinbot-<env> --no-pager
sudo systemctl restart vinbot-<env>          # after an .env or code change
sudo systemctl stop     vinbot-<env>
sudo systemctl start    vinbot-<env>
sudo journalctl -u vinbot-<env> -f           # follow live logs
sudo journalctl -u vinbot-<env> -n 200 --no-pager   # last 200 lines
```

Substitute `<env>` with `dev`, `uat`, or `prod`.

## 3. Health check

```bash
curl -s http://127.0.0.1:<port>/api/health
```
Expected: `{"status":"ok", ..., "knowledge_chunks": <N>}` with `N > 0`. If
`knowledge_chunks` is `0`, the knowledge base file is missing or failed to
load — check the port/env row in §1, then see §6 (knowledge base) and §8
(troubleshooting).

This is a **liveness** check only — it does not verify OpenAI API
reachability or the structured (SQLite) fact store. Treat a `200` response
with `knowledge_chunks > 0` as "process is up," not as a full functional
guarantee.

## 4. Redeploying new code

```bash
sudo tar -xzf <release>.tar.gz -C /opt/vinbot-<env>
sudo chown -R vinbot-<env>:vinbot-<env> /opt/vinbot-<env>
cd /opt/vinbot-<env>/backend  && sudo -u vinbot-<env> .venv/bin/pip install -r /opt/vinbot-<env>/requirements.txt
cd /opt/vinbot-<env>/frontend && sudo -u vinbot-<env> npm ci && sudo -u vinbot-<env> npm run build
sudo systemctl restart vinbot-<env>
```
Standard promotion order: **DEV → UAT → PROD** (see `deploy/DEPLOY.md` §
"Promotion flow"). Always confirm the health check (§3) after restarting.

## 5. Secrets management

- Each environment's OpenAI key lives only in `/opt/vinbot-<env>/backend/.env`,
  `chmod 600`, owned by that environment's service account. Never commit `.env`
  to version control or copy one environment's `.env` into another.
- To rotate a key: update `.env`, then `sudo systemctl restart vinbot-<env>`.

## 6. Knowledge base maintenance

Two independent stores back the assistant:

| Store | File | Rebuilt by |
|---|---|---|
| Prose (circulars, press notes) | `backend/knowledge_db.pkl` | `python ingest.py` / `python knowledge_maker.py` |
| Structured (numeric reports) | `backend/uhbvn_tables.db` | `python build_tables.py` |

To add a new document:
```bash
# 1. Drop the new PDF into backend/knowledge/ (prose) or UHBVN_new/ (tabular)
# 2. Re-run the relevant build step, e.g.:
cd backend && source .venv/bin/activate
python ingest.py --append          # prose: only embeds new/changed sources
python build_tables.py             # structured: full rebuild from UHBVN_new/*.pdf
# 3. Restart the service
sudo systemctl restart vinbot-<env>
```
Each environment's knowledge base is independent — rebuilding in DEV does not
affect UAT or PROD. Never copy a `.pkl`/`.db` file between environments
without checking it was built from that environment's intended document set.

## 7. Backup (manual — no automated backup exists today)

Before any redeploy or knowledge-base rebuild, an administrator should
manually retain a copy of:
- `backend/knowledge_db.pkl`, `backend/uhbvn_tables.db` (rebuildable, but
  rebuilding costs OpenAI API calls and time)
- `backend/.env` (not recoverable if lost — store the key separately/securely)

There is currently no scheduled/automated backup job for these files; see the
Phase 5 monitoring workstream for whether this should be added.

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `502 Bad Gateway` at the domain | Edge server can't reach the app server's port | Check `vinbot-<env>.service` status; confirm it's bound and listening: `ss -ltnp \| grep <port>` |
| Reply appears all at once, not streamed | Nginx buffering the SSE stream | Ensure `proxy_buffering off;` in that environment's nginx site config |
| `knowledge_chunks: 0` in `/api/health` | `knowledge_db.pkl` missing/corrupt | Restore from backup or rebuild (§6) |
| Backend won't start | `OPENAI_API_KEY` missing/invalid | Check `/opt/vinbot-<env>/backend/.env`, restart |
| `Connection refused` from the edge server | Uvicorn bound to `127.0.0.1` when the edge expects a LAN IP (or vice versa) | Check the `--host` flag in the systemd unit matches the topology |
| Domain doesn't resolve | DNS `A` record missing/wrong | Point it at the environment's public IP |

## 9. Security responsibilities

- Run each environment's service as its own non-privileged account
  (`vinbot-dev` / `vinbot-uat` / `vinbot-prod`) — never as root.
- Keep the app server's Uvicorn port reachable only from its edge/reverse-proxy
  tier (network/security-group rule), never exposed directly to the internet.
- TLS is terminated at the edge; keep the wildcard certificate current.
- Restrict who has shell access to each environment's service account and
  `.env` file — treat UAT/PROD access as more sensitive than DEV.

## 10. Scaling

Sessions are held in the Uvicorn worker's process memory
(`backend/app/sessions.py`), so **each environment runs a single worker** —
this is a hard constraint, not a tuning choice. To scale an environment
beyond one worker/process:
1. Move the session store to a shared backend (e.g. Redis).
2. Only then raise `--workers` in that environment's systemd unit, or add
   additional app servers behind the edge nginx `upstream` block.

## 11. Reference

- Full architecture & config reference: `DOCUMENTATION.md`
- Deployment/installation steps: `deploy/DEPLOY.md`, `INSTALL.md`
- API contract: `API_DOCUMENTATION.md`
- End-user guide: `USER_MANUAL.md`
