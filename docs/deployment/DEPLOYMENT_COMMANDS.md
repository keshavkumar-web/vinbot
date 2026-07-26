# Vinbot — Deployment Commands (ready-to-run, per environment)

Fully expanded versions of `deploy/DEPLOY.md`'s steps — no `<ENV>` placeholders
— for DEV, UAT, and PROD. **These have not been run against any server**: no
DEV/UAT/PROD host exists yet (see `DEPLOYMENT_GAP_ANALYSIS.md`). Run them once
a server is provisioned and reachable via SSH as `user@<server>`.

The release artifact to ship is `release/vinbot_deploy_2026-07-26.tar.gz`
(built locally in this session). It now includes a fully restored and
validated `backend/knowledge_db.pkl` (7,711 chunks) and `backend/uhbvn_tables.db`
— no separate transfer of either file is needed. `backend/.env` is correctly
excluded — create a fresh, environment-specific one on each server (step 4
below), never copy the local dev one.

---

## DEV — `dev-vinbot.vinbox.in`

```bash
# 1. Server packages + service account
sudo apt update
sudo apt install -y python3-venv python3-pip nginx
sudo adduser --system --group --home /opt/vinbot-dev vinbot-dev
sudo mkdir -p /opt/vinbot-dev && sudo chown vinbot-dev:vinbot-dev /opt/vinbot-dev

# 2. Ship and unpack the release (knowledge_db.pkl + uhbvn_tables.db are both inside)
scp release/vinbot_deploy_2026-07-26.tar.gz user@<dev-server>:/tmp/
ssh user@<dev-server> 'sudo tar -xzf /tmp/vinbot_deploy_2026-07-26.tar.gz -C /opt/vinbot-dev && sudo chown -R vinbot-dev:vinbot-dev /opt/vinbot-dev'

# 3. Backend
ssh user@<dev-server> '
  cd /opt/vinbot-dev/backend
  sudo -u vinbot-dev python3 -m venv .venv
  sudo -u vinbot-dev .venv/bin/pip install -U pip
  sudo -u vinbot-dev .venv/bin/pip install -r /opt/vinbot-dev/requirements.txt
'

# 4. Secrets — create on the server, DO NOT reuse the local dev key
ssh user@<dev-server> "sudo -u vinbot-dev tee /opt/vinbot-dev/backend/.env" <<'EOF'
OPENAI_API_KEY=sk-...dev-specific-key...
ALLOWED_ORIGINS=https://dev-vinbot.vinbox.in
EOF
ssh user@<dev-server> 'sudo chmod 600 /opt/vinbot-dev/backend/.env'

# 5. systemd
ssh user@<dev-server> '
  sudo cp /opt/vinbot-dev/deploy/vinbot-dev.service /etc/systemd/system/vinbot-dev.service
  sudo systemctl daemon-reload
  sudo systemctl enable --now vinbot-dev
  curl -s http://127.0.0.1:8010/api/health
'

# 6. Frontend (rebuild server-side per deploy/DEPLOY.md; the tarball also
#    ships a pre-built dist/ as a fallback, but rebuilding is authoritative)
ssh user@<dev-server> 'cd /opt/vinbot-dev/frontend && npm ci && npm run build'

# 7. Nginx
ssh user@<dev-server> '
  sudo cp /opt/vinbot-dev/deploy/nginx-vinbot-dev.conf /etc/nginx/sites-available/vinbot-dev
  sudo ln -sf /etc/nginx/sites-available/vinbot-dev /etc/nginx/sites-enabled/
  sudo nginx -t && sudo systemctl reload nginx
'

# 8. HTTPS (only after the DNS record below exists and has propagated)
ssh user@<dev-server> 'sudo certbot --nginx -d dev-vinbot.vinbox.in'

# 9. Verify
curl -s https://dev-vinbot.vinbox.in/api/health
```

**DNS prerequisite (not yet done — see gap analysis)**: an `A` record for
`dev-vinbot` pointing at the edge server's public IP.

---

## UAT — `uat-vinbot.vinbox.in`

Identical to DEV, with every `dev` above replaced by `uat` and port `8010`
replaced by `8020`:

```bash
sudo adduser --system --group --home /opt/vinbot-uat vinbot-uat
sudo mkdir -p /opt/vinbot-uat && sudo chown vinbot-uat:vinbot-uat /opt/vinbot-uat
scp release/vinbot_deploy_2026-07-26.tar.gz user@<uat-server>:/tmp/
ssh user@<uat-server> 'sudo tar -xzf /tmp/vinbot_deploy_2026-07-26.tar.gz -C /opt/vinbot-uat && sudo chown -R vinbot-uat:vinbot-uat /opt/vinbot-uat'
ssh user@<uat-server> '
  cd /opt/vinbot-uat/backend
  sudo -u vinbot-uat python3 -m venv .venv
  sudo -u vinbot-uat .venv/bin/pip install -U pip
  sudo -u vinbot-uat .venv/bin/pip install -r /opt/vinbot-uat/requirements.txt
'
ssh user@<uat-server> "sudo -u vinbot-uat tee /opt/vinbot-uat/backend/.env" <<'EOF'
OPENAI_API_KEY=sk-...uat-specific-key...
ALLOWED_ORIGINS=https://uat-vinbot.vinbox.in
EOF
ssh user@<uat-server> 'sudo chmod 600 /opt/vinbot-uat/backend/.env'
ssh user@<uat-server> '
  sudo cp /opt/vinbot-uat/deploy/vinbot-uat.service /etc/systemd/system/vinbot-uat.service
  sudo systemctl daemon-reload
  sudo systemctl enable --now vinbot-uat
  curl -s http://127.0.0.1:8020/api/health
'
ssh user@<uat-server> 'cd /opt/vinbot-uat/frontend && npm ci && npm run build'
ssh user@<uat-server> '
  sudo cp /opt/vinbot-uat/deploy/nginx-vinbot-uat.conf /etc/nginx/sites-available/vinbot-uat
  sudo ln -sf /etc/nginx/sites-available/vinbot-uat /etc/nginx/sites-enabled/
  sudo nginx -t && sudo systemctl reload nginx
'
ssh user@<uat-server> 'sudo certbot --nginx -d uat-vinbot.vinbox.in'
curl -s https://uat-vinbot.vinbox.in/api/health
```

**Then run, against this environment**:
```bash
python backend/tests/smoke/smoke.py --base-url https://uat-vinbot.vinbox.in
cd postman && npm run test:uat
```

---

## PROD — `vinbot.vinbox.in`

Same pattern again (`prod`, port `8000`) — **do not run until**:
- DEV and UAT above have both been validated (smoke + Newman green), and
- the rollback-procedure gap (`DEPLOYMENT_GAP_ANALYSIS.md` §14) has been closed.

```bash
sudo adduser --system --group --home /opt/vinbot-prod vinbot-prod
sudo mkdir -p /opt/vinbot-prod && sudo chown vinbot-prod:vinbot-prod /opt/vinbot-prod
scp release/vinbot_deploy_2026-07-26.tar.gz user@<prod-server>:/tmp/
ssh user@<prod-server> 'sudo tar -xzf /tmp/vinbot_deploy_2026-07-26.tar.gz -C /opt/vinbot-prod && sudo chown -R vinbot-prod:vinbot-prod /opt/vinbot-prod'
ssh user@<prod-server> '
  cd /opt/vinbot-prod/backend
  sudo -u vinbot-prod python3 -m venv .venv
  sudo -u vinbot-prod .venv/bin/pip install -U pip
  sudo -u vinbot-prod .venv/bin/pip install -r /opt/vinbot-prod/requirements.txt
'
ssh user@<prod-server> "sudo -u vinbot-prod tee /opt/vinbot-prod/backend/.env" <<'EOF'
OPENAI_API_KEY=sk-...prod-specific-key...
ALLOWED_ORIGINS=https://vinbot.vinbox.in
EOF
ssh user@<prod-server> 'sudo chmod 600 /opt/vinbot-prod/backend/.env'
ssh user@<prod-server> '
  sudo cp /opt/vinbot-prod/deploy/vinbot-prod.service /etc/systemd/system/vinbot-prod.service
  sudo systemctl daemon-reload
  sudo systemctl enable --now vinbot-prod
  curl -s http://127.0.0.1:8000/api/health
'
ssh user@<prod-server> 'cd /opt/vinbot-prod/frontend && npm ci && npm run build'
ssh user@<prod-server> '
  sudo cp /opt/vinbot-prod/deploy/nginx-vinbot-prod.conf /etc/nginx/sites-available/vinbot-prod
  sudo ln -sf /etc/nginx/sites-available/vinbot-prod /etc/nginx/sites-enabled/
  sudo nginx -t && sudo systemctl reload nginx
'
ssh user@<prod-server> 'sudo certbot --nginx -d vinbot.vinbox.in'   # or confirm the shared wildcard already covers it
curl -s https://vinbot.vinbox.in/api/health
python backend/tests/smoke/smoke.py --base-url https://vinbot.vinbox.in
cd postman && npm run test:prod
```

---

## Rollback (adapted from the baseline project's older procedure — not yet formalized for this 3-env layout, see gap analysis §14)

```bash
# BEFORE applying an update, snapshot the current app code:
ssh user@<server> 'sudo -u vinbot-<env> cp -a /opt/vinbot-<env>/backend/app /opt/vinbot-<env>/backend/app.bak.$(date +%F)'

# if the new deploy misbehaves:
ssh user@<server> '
  sudo -u vinbot-<env> rm -rf /opt/vinbot-<env>/backend/app
  sudo -u vinbot-<env> mv /opt/vinbot-<env>/backend/app.bak.YYYY-MM-DD /opt/vinbot-<env>/backend/app
  sudo systemctl restart vinbot-<env>
'
```
