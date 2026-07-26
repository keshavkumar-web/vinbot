# Deploying Vinbot (DEV / UAT / PROD)

Production-grade setup: **Nginx** at the edge terminates TLS and reverse-proxies
to a single **Uvicorn** worker, which serves both the built Vue frontend and
the `/api` routes from one origin (no CORS needed). The same procedure is used
for all three environments — only the names, ports and directories differ.

## Environment reference

| | DEV | UAT | PROD |
|---|---|---|---|
| Domain | `dev-vinbot.vinbox.in` | `uat-vinbot.vinbox.in` | `vinbot.vinbox.in` |
| systemd unit | `vinbot-dev.service` | `vinbot-uat.service` | `vinbot-prod.service` |
| App directory | `/opt/vinbot-dev` | `/opt/vinbot-uat` | `/opt/vinbot-prod` |
| Service account | `vinbot-dev` | `vinbot-uat` | `vinbot-prod` |
| Uvicorn port | `8010` | `8020` | `8000` |
| Nginx site file | `vinbot-dev` | `vinbot-uat` | `vinbot-prod` |
| systemd unit source | `deploy/vinbot-dev.service` | `deploy/vinbot-uat.service` | `deploy/vinbot-prod.service` |
| Nginx config source | `deploy/nginx-vinbot-dev.conf` | `deploy/nginx-vinbot-uat.conf` | `deploy/nginx-vinbot-prod.conf` |

The steps below use `<ENV>` for the environment name (`dev` / `uat` / `prod`) —
substitute the row from the table above throughout.

## Prerequisites
- An Ubuntu/Debian server reachable from the edge/reverse-proxy tier.
- DNS: an **A record** for the environment's domain → the edge server's public IP
  (set this first; certbot needs it for UAT/PROD).
- Node.js 20+ and Python 3.11+ on the app server.

## 1. Server packages

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip nginx git
sudo adduser --system --group --home /opt/vinbot-<ENV> vinbot-<ENV>
sudo mkdir -p /opt/vinbot-<ENV> && sudo chown vinbot-<ENV>:vinbot-<ENV> /opt/vinbot-<ENV>
```

## 2. Copy the project

Copy the repo to `/opt/vinbot-<ENV>`, **excluding** `backend/.venv`,
`frontend/node_modules`, `frontend/dist` (rebuilt on the server). **Include**
`backend/knowledge_db.pkl` and `backend/uhbvn_tables.db` (the knowledge/fact stores).

```bash
# from your workstation:
rsync -av --exclude '.venv' --exclude 'node_modules' --exclude 'dist' \
      ./ user@server:/opt/vinbot-<ENV>/
```

## 3. Backend

```bash
cd /opt/vinbot-<ENV>/backend
sudo -u vinbot-<ENV> python3 -m venv .venv
sudo -u vinbot-<ENV> .venv/bin/pip install -U pip
sudo -u vinbot-<ENV> .venv/bin/pip install -r /opt/vinbot-<ENV>/requirements.txt
```

Create `/opt/vinbot-<ENV>/backend/.env` on the server (do NOT copy your local
one — each environment gets its own key and origin):
```ini
OPENAI_API_KEY=sk-...env-specific-key...
ALLOWED_ORIGINS=https://<environment-domain-from-table-above>
```
```bash
sudo chown vinbot-<ENV>:vinbot-<ENV> /opt/vinbot-<ENV>/backend/.env
sudo chmod 600 /opt/vinbot-<ENV>/backend/.env
```

## 4. systemd service

```bash
sudo cp /opt/vinbot-<ENV>/deploy/vinbot-<ENV>.service /etc/systemd/system/vinbot-<ENV>.service
sudo systemctl daemon-reload
sudo systemctl enable --now vinbot-<ENV>
curl -s http://127.0.0.1:<port-from-table-above>/api/health   # knowledge_chunks should be > 0
```

## 5. Frontend build

```bash
cd /opt/vinbot-<ENV>/frontend
npm ci
npm run build        # -> /opt/vinbot-<ENV>/frontend/dist
```

## 6. Nginx

```bash
sudo cp /opt/vinbot-<ENV>/deploy/nginx-vinbot-<ENV>.conf /etc/nginx/sites-available/vinbot-<ENV>
sudo ln -s /etc/nginx/sites-available/vinbot-<ENV> /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

## 7. HTTPS

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d <environment-domain-from-table-above>
```
Certbot rewrites the site to listen on 443 and adds an HTTP->HTTPS redirect.
(If the edge tier already carries a shared wildcard `*.vinbox.in` certificate,
as in the reference topology described in `DOCUMENTATION.md` §2, this step
may be a no-op — the new server block just needs to be added under that
existing certificate.)

## 8. Verify

- Visit `https://<environment-domain>` -> UI loads.
- Send a message -> reply streams word-by-word (if it dumps all at once, check
  `proxy_buffering off`).
- `curl https://<environment-domain>/api/health` -> chunk count matches the KB.

## Updating later

```bash
# new code:
cd /opt/vinbot-<ENV> && git pull         # or rsync
sudo -u vinbot-<ENV> backend/.venv/bin/pip install -r requirements.txt
cd frontend && npm ci && npm run build
sudo systemctl restart vinbot-<ENV>
```

## Promotion flow (DEV → UAT → PROD)

Vinbot follows a standard three-stage promotion: changes land in **DEV** first,
are validated, then the same artifact/build is deployed to **UAT** for
acceptance testing, and only then to **PROD**. Because each environment is a
fully separate directory/service/`.env`, promoting a build means repeating
steps 2–7 above against the next environment's row in the table — no shared
state to migrate.

## Scaling note

Sessions live in process memory (`backend/app/sessions.py`), so each
environment runs as a **single Uvicorn worker**. To run multiple workers /
machines for an environment, move its session store to Redis first, then
raise `--workers`.
