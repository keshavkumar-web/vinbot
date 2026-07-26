> **Inherited baseline document.** This file describes an earlier,
> single-server RHEL 9 deployment path (no Nginx, plain HTTP) from the project
> Vinbot was created from, including real historical release notes under the
> old `generic_bot`/`uhbvn` naming. It is kept verbatim as genuine operational
> history and is **not** the current Vinbot deployment procedure — for
> installing/operating Vinbot's DEV/UAT/PROD environments, use
> `deploy/DEPLOY.md` instead.

# Deploying on a single RHEL 9 server (FastAPI serves the Vue build, HTTP/IP)

One uvicorn process serves both the API (`/api/*`) and the built Vue app
(everything else). No Nginx. Reached over plain HTTP by server IP.

Replace `SERVER_IP`, `botuser`, and paths to match your server.
Tested target: Red Hat Enterprise Linux 9.7.

## 0. Prerequisites
- A RHEL 9 server with SSH access and a sudo user.
- Inbound **port 80** open in BOTH firewalld and your cloud provider's
  security group / firewall.
- The project files (this repo) copied to e.g. `/opt/generic_bot`.

## 1. Install system packages
RHEL 9's default `python3` is 3.9 — too old for this code (it uses `str | None`
syntax, which needs Python >= 3.10). Install Python 3.12 from AppStream:
```bash
sudo dnf install -y python3.12 python3.12-pip git
python3.12 --version          # 3.12.x
```
Node 22 is needed only to BUILD the frontend (Vite 8 needs Node >= 20.19/22.12).
Use the NodeSource RPM repo for EL9:
```bash
curl -fsSL https://rpm.nodesource.com/setup_22.x | sudo bash -
sudo dnf install -y nodejs
node --version                # v22.x
```
> Alternative: build the frontend on your dev machine and upload `frontend/dist`
> to the server — then you don't need Node on the server at all (skip step 4).

## 2. Put the code on the server
```bash
sudo mkdir -p /opt/generic_bot
sudo chown $USER:$USER /opt/generic_bot
# then copy the project in (git clone or rsync).
```

## 3. Backend: virtualenv (Python 3.12) + dependencies + knowledge base
```bash
cd /opt/generic_bot/backend
python3.12 -m venv .venv       # MUST be 3.12 (or any >= 3.10), not RHEL's 3.9
source .venv/bin/activate
python --version               # confirm >= 3.10 before continuing
pip install --upgrade pip
pip install -r requirements.txt
```
> Already made a `.venv` with python3.9? Delete and recreate it:
> `deactivate; rm -rf .venv; python3.12 -m venv .venv; source .venv/bin/activate`

Set the OpenAI key (rotate the old one; keep it only here, locked down):
```bash
cp .env.example .env
nano .env                      # set OPENAI_API_KEY=sk-...
chmod 600 .env
```
Provide the knowledge base. Pick ONE:

**Option 1 (recommended) — upload the prebuilt `knowledge_db.pkl`** from your dev
machine (~100 MB, portable: it holds only plain Python lists/dicts). Fastest,
and avoids re-running OCR/embeddings:
```bash
# run on your dev machine:
scp backend/knowledge_db.pkl ecadmin@SERVER_IP:/opt/generic_bot/backend/
```

**Option 2 — re-embed on the server** (needs the key + internet). Upload the
extracted `knowledge/*.txt` (~6 MB) first, then:
```bash
python knowledge_maker.py        # knowledge/*.txt -> knowledge_db.pkl (batched)
```

**Option 3 — full rebuild from the original UHBVN PDFs** (re-runs OCR; needs the
`UHBVN/` folder, extra deps, and OpenAI-vision cost):
```bash
pip install -r requirements-ingest.txt
python extract_uhbvn.py          # UHBVN/*.pdf -> knowledge/*.txt (pypdf + OCR)
python knowledge_maker.py        # then embed
```

## 4. Frontend: build the static bundle
```bash
cd /opt/generic_bot/frontend
npm install
npm run build                  # outputs frontend/dist
```
`backend/app/main.py` auto-detects `../frontend/dist` and serves it.

## 5. Smoke-test before installing the service
```bash
cd /opt/generic_bot/backend
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
Startup log should print `Serving frontend from .../frontend/dist`.
From your laptop open `http://SERVER_IP:8000` — the chat UI loads and replies.
Also check `http://SERVER_IP:8000/api/health`. Then Ctrl+C.
(Port 8000 also needs to be open in firewalld for this test, or just test
locally on the server with `curl http://localhost:8000/api/health`.)

## 6. Run it as a service (auto-start, restart on crash)
```bash
sudo useradd --system --create-home botuser     # or reuse your sudo user
sudo chown -R botuser:botuser /opt/generic_bot

sudo cp /opt/generic_bot/deploy/generic-bot.service /etc/systemd/system/
sudo nano /etc/systemd/system/generic-bot.service    # check User= and paths
sudo systemctl daemon-reload
sudo systemctl enable --now generic-bot
sudo systemctl status generic-bot                    # active (running)
sudo journalctl -u generic-bot -f                    # live logs
```
The unit binds **port 80** as the non-root `botuser` via
`AmbientCapabilities=CAP_NET_BIND_SERVICE`. Then browse `http://SERVER_IP`.

## 7. Open the firewall (firewalld)
```bash
sudo firewall-cmd --permanent --add-service=http     # opens 80/tcp
sudo firewall-cmd --reload
sudo firewall-cmd --list-services                    # confirm 'http' is listed
```
Also confirm port 80 is allowed in your cloud security group.

## 8. SELinux (enforcing by default on RHEL)
```bash
getenforce                     # usually 'Enforcing'
```
A custom systemd service in `/opt` normally runs unconfined and binds port 80
fine (80 is already labelled `http_port_t`). If the service fails to start,
bind, or read files, SELinux is the likely cause — diagnose, don't blindly
disable:
```bash
sudo journalctl -u generic-bot -e          # see the actual error
sudo ausearch -m avc -ts recent            # SELinux denials, if any
sudo restorecon -Rv /opt/generic_bot       # fix file contexts if needed
```
To confirm SELinux is the cause (testing only): `sudo setenforce 0` temporarily,
retest, then `sudo setenforce 1` and build a proper rule with `audit2allow`
rather than leaving it permissive.

## Updating after code changes
```bash
# 1. SNAPSHOT the current app first (this is your rollback — no git on the box).
sudo cp -a /opt/generic_bot/backend/app \
           /opt/generic_bot/backend/app.bak.$(date +%F)

# 2. Apply the update (git pull, OR extract a release tarball over the tree).
cd /opt/generic_bot && git pull            # or: tar -xzf uhbvn_update_YYYY-MM-DD.tar.gz
cd frontend && npm run build               # ONLY if the UI changed
cd ../backend && source .venv/bin/activate && pip install -r requirements.txt
sudo systemctl restart generic-bot

# 3. Verify, then watch logs.
curl -s http://localhost:8000/api/health   # {"status":"ok",...}
sudo journalctl -u generic-bot -f
```
**Rollback** (if the new build misbehaves):
```bash
sudo rm -rf /opt/generic_bot/backend/app
sudo mv /opt/generic_bot/backend/app.bak.YYYY-MM-DD /opt/generic_bot/backend/app
sudo systemctl restart generic-bot
```

### TWO knowledge stores — BOTH are required
The bot has **two** data files in `backend/`, and BOTH must be on the server:
- `knowledge_db.pkl` — the prose / vector store (circulars). ~108 MB.
- `uhbvn_tables.db` — the **structured numeric** store (SQLite facts). ~2.7 MB.
  **If this file is missing, every numeric question silently falls back to prose**
  (the structured router returns "prose" when the DB isn't found), so figures like
  "how many connections" are answered from circulars instead of the fact store.
  Upload it alongside the pkl: `scp backend/uhbvn_tables.db ecadmin@SERVER:/opt/uhbvn/backend/`

### Release 2026-06-28 — actual prod target `/opt/uhbvn`, service `uhbvn.service`
> Confirmed live layout: app at `/opt/uhbvn`, runs as user `uhbvn` via
> `uhbvn.service` (`uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1`)
> behind nginx; Python 3.11. (The `deploy/generic-bot.service` file is a stale
> template pointing at `/opt/generic_bot:80` — not the active unit.)

This release also **first-ships the structured numeric system** to this server
(prod was still the original RAG-only bot: no `app/tables.py`, no `uhbvn_tables.db`).
Ships as `uhbvn_deploy_2026-06-28.tar.gz` (full `app/` + `uhbvn_tables.db` + eval
scripts). **No new dependencies, no frontend build.**
```bash
# upload from dev box
scp uhbvn_deploy_2026-06-28.tar.gz ecadmin@SERVER:/tmp/
# on the server (keep uhbvn ownership)
sudo -u uhbvn bash -c '
  cd /opt/uhbvn &&
  cp -a backend/app backend/app.bak.$(date +%F) &&
  tar -xzf /tmp/uhbvn_deploy_2026-06-28.tar.gz -C /opt/uhbvn &&
  find backend/app -name __pycache__ -type d -exec rm -rf {} +'
sudo systemctl restart uhbvn
curl -s http://localhost:8000/api/health        # {"status":"ok",...}
# post-deploy gate (needs key in backend/.env)
cd /opt/uhbvn/backend && source .venv/bin/activate
python eval_tables.py && python eval_rag.py && python validate_e2e.py
```
Rollback: `sudo -u uhbvn bash -c 'cd /opt/uhbvn && rm -rf backend/app && mv backend/app.bak.$(date +%F) backend/app'; sudo systemctl restart uhbvn`
- The numeric path now calls the LLM per numeric query (was offline keyword
  matching); if OpenAI is unreachable it falls back to prose RAG (safe — RAG is
  forbidden to invent figures). Expect ~1.2 s added on numeric queries and a
  larger context on multi-part prose turns. RAM: +~45 MB for a cached embedding
  matrix, built lazily on the first multi-part question.

## Updating the knowledge base
The bot answers only from `knowledge_db.pkl`. To change what it knows:
- **New/edited UHBVN documents** → rebuild the KB (see §3 Options 2/3 — re-embed
  the `knowledge/*.txt`, or full PDF→OCR→embed), then upload the new
  `knowledge_db.pkl` (or rebuild in place) and `sudo systemctl restart generic-bot`.
- Restarting the service is required because the KB is loaded into memory at
  startup.

## Important caveats (accurate to this codebase)
- **Python must be >= 3.10.** RHEL 9 default 3.9 crashes on import (`str | None`).
  Use the python3.12 venv from step 3.
- **Run a SINGLE process/worker.** Session history lives in memory
  (`app/sessions.py`). Multiple uvicorn workers would each hold different
  sessions, so a user could hit a worker that doesn't know their `session_id`
  (HTTP 404). To scale out, move sessions to Redis first.
- **HTTP only = unencrypted.** Messages travel in plaintext — fine for testing
  or an internal network, NOT for real public/customer traffic. Add a domain +
  HTTPS before going live.
- **Rotate the OpenAI key** committed earlier; keep the new one only in
  `backend/.env` (chmod 600).
- Concurrency is fine on one worker: FastAPI runs the sync `/api/chat` endpoint
  and its streaming generator in a threadpool, so one slow OpenAI call does not
  block others.
