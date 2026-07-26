# Vinbot — Development & Deployment Guide

A Retrieval-Augmented Generation (RAG) chatbot platform built by **Vinbox
Martech Pvt Ltd**. This instance is configured to answer questions about
Uttar Haryana Bijli Vitran Nigam (UHBVN) electricity rules, sales circulars,
instructions, tariffs and procedures. It is grounded on an embedded knowledge
base built from official UHBVN PDFs and served through a Vue web UI.

---

## 1. Overview

| Aspect | Detail |
|---|---|
| Backend | Python 3.11, FastAPI + Uvicorn |
| Frontend | Vue 3 + Vite + Tailwind CSS |
| Retrieval | OpenAI embeddings (`text-embedding-3-small`) + cosine similarity over a pickled vector store |
| Generation | OpenAI chat model (`gpt-4o-mini`), streamed token-by-token via Server-Sent Events (SSE) |
| Knowledge base | `backend/knowledge_db.pkl` — ~7,288 embedded chunks built from UHBVN PDFs |
| Sessions | In-memory, per-tab conversation history (process-local) |
| Environments | DEV `https://dev-vinbot.vinbox.in` · UAT `https://uat-vinbot.vinbox.in` · PROD `https://vinbot.vinbox.in` |

### How a request flows
1. The browser opens the environment URL and creates a session (`POST /api/session`).
2. The user sends a message (`POST /api/chat`).
3. The backend embeds the question, retrieves the most similar knowledge chunks,
   assembles a prompt (system instructions + history + retrieved context), and
   streams the model's reply back as SSE tokens.
4. The reply is rendered live in the UI and stored in the session history.

---

## 2. Architecture

### Reference topology (per environment: one app server behind one edge reverse proxy)

```
                 Internet
                    │  https://{env}vinbot.vinbox.in
                    ▼
        Public IP  <PUBLIC_IP>            (perimeter NAT)
                    │
                    ▼
   ┌───────────────────────────────────────────┐
   │ Edge server   <EDGE_SERVER_IP>             │   Edge nginx reverse proxy / LB
   │  • TLS termination (wildcard *.vinbox.in)  │   Host-based routing for all
   │  • server_name {env}vinbot.vinbox.in       │   *.vinbox.in sites
   └────────────────────┬────────────────────────┘
                        │  proxy_pass http://<APP_SERVER_IP>:<PORT>
                        ▼
   ┌───────────────────────────────────────────┐
   │ App server    <APP_SERVER_IP>              │   Application server
   │  • systemd: vinbot-{env}.service           │
   │  • uvicorn app.main:app  :<PORT> (1 worker)│   Serves BOTH the Vue UI
   │  • serves frontend/dist + /api             │   and the API on one origin
   │  • loads knowledge_db.pkl into memory      │
   └───────────────────────────────────────────┘
```

Where `{env}` / `<PORT>` are per environment — see the table in §9. This
mirrors the architecture already proven in production for the underlying
platform: one edge reverse proxy terminating TLS in front of a single Uvicorn
worker that serves both the API and the built SPA. `<PUBLIC_IP>`,
`<EDGE_SERVER_IP>` and `<APP_SERVER_IP>` are placeholders — fill in the actual
addresses when each environment is provisioned.

Key points:
- **One public entry per environment** reaches the edge nginx, which routes by
  hostname alongside other `*.vinbox.in` sites.
- **TLS is a shared wildcard** `*.vinbox.in` certificate — each `{env}vinbot.vinbox.in`
  host is covered automatically (no per-site certificate).
- **The backend serves the UI itself.** `app/main.py` mounts `frontend/dist` at
  `/`, so nginx only needs a single reverse-proxy block (no static files at the
  edge, no CORS).
- **Single Uvicorn worker per environment.** Sessions live in process memory,
  so each service runs one worker (see §14 for scaling).

---

## 3. Repository layout

```
Vinbot/
├── backend/
│   ├── app/
│   │   ├── main.py        # FastAPI app, routes, SSE, static mount
│   │   ├── config.py      # central config (env-driven), system prompt
│   │   ├── rag.py         # embeddings, cosine similarity, KB loading
│   │   ├── chat.py        # prompt assembly + streaming generation
│   │   ├── sessions.py    # in-memory session store
│   │   └── schemas.py     # Pydantic request/response models
│   ├── ingest.py          # build/append knowledge_db.pkl from text files
│   ├── extract_uhbvn.py   # PDF → text (text layer + OCR fallback)
│   ├── knowledge_maker.py # simpler full rebuild of the KB
│   ├── knowledge_db.pkl   # the embedded vector store (~103 MB)
│   ├── requirements.txt           # runtime deps
│   ├── requirements-ingest.txt    # extra deps for ingestion/OCR only
│   └── .env               # secrets/config (not committed)
├── frontend/
│   ├── src/ (App.vue, api.js, main.js, style.css)
│   ├── vite.config.js     # dev server + /api proxy
│   └── package.json
├── UHBVN_new/              # source PDFs for the structured (numeric) reports
└── deploy/                 # systemd units + nginx configs per environment
```

---

## 4. Backend components

- **`app/main.py`** — exposes:
  - `GET  /api/health` — liveness + model names + knowledge chunk count
  - `POST /api/session` — create a session, returns `session_id`
  - `POST /api/chat` — stream the assistant reply as SSE
  - `POST /api/reset` — clear a session's history
  - Mounts `frontend/dist` at `/` when the build exists (single-origin serving).
- **`app/config.py`** — single source of truth. Reads env / `.env`, fails fast
  if `OPENAI_API_KEY` is missing, and holds the system prompt and all tunables.
- **`app/rag.py`** — loads the pickled KB lazily, creates query embeddings, and
  returns the top-`TOP_K` chunks above `MIN_SIMILARITY` by cosine similarity.
- **`app/chat.py`** — builds the message list (system prompt → history →
  retrieved context → user message) and streams deltas from the chat model.
- **`app/sessions.py`** — thread-safe in-memory store; trims history to
  `MAX_HISTORY_MESSAGES`. Process-local and non-persistent.

---

## 5. Frontend components

- **Vue 3 SPA** built with Vite, styled with Tailwind.
- **`src/api.js`** — thin client. All calls target the relative path `/api`,
  and the SSE body of `/api/chat` is parsed manually (POST + streamed reader).
- **Dev proxy** (`vite.config.js`) forwards `/api` from the Vite dev server
  (`:5173`) to the backend (`:8000`) so development is same-origin.
- **Production** — `npm run build` emits `frontend/dist`, which the backend
  serves directly. Markdown replies are rendered with `marked` and sanitized
  with `dompurify`.

---

## 6. Knowledge base & ingestion pipeline

The vector store `knowledge_db.pkl` is a list of records:
`{ source, chunk_id, text, embedding }`.

Pipeline: **PDFs → text → chunks → embeddings → pickle**

1. **Extract text** from the source PDFs:
   ```bash
   cd backend
   pip install -r requirements-ingest.txt   # pypdf + pymupdf (OCR)
   python extract_uhbvn.py                  # writes backend/knowledge/*.txt
   ```
   `extract_uhbvn.py` uses the PDF text layer where present and falls back to
   OpenAI vision OCR for scanned pages. It is resumable (skips existing `.txt`).

2. **Build the embedded DB** from the extracted text:
   ```bash
   python ingest.py                       # rebuild from backend/knowledge
   python ingest.py --pdf-dir ../UHBVN_new    # also extract simple PDFs first
   python ingest.py --append              # only embed new/changed sources
   ```
   (`knowledge_maker.py` is a simpler one-shot full rebuild.)

Chunking (`CHUNK_SIZE`, `CHUNK_OVERLAP`) and the embedding model come from
`app/config.py`. Embeddings are sent in batches of 100 to keep ingestion fast.

> Ingestion only needs to be re-run when the source documents change. The
> committed `knowledge_db.pkl` is what a deployed instance loads at startup.

---

## 7. Local development

### Backend
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r ../requirements.txt

# create backend/.env (see §8) with OPENAI_API_KEY
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
Check: `curl http://127.0.0.1:8000/api/health` → JSON with `knowledge_chunks`.

### Frontend
```bash
cd frontend
npm install
npm run dev                          # http://localhost:5173 (proxies /api → :8000)
```
Open `http://localhost:5173` and chat. Both servers run side-by-side in dev.

### Production build (local check)
```bash
cd frontend && npm run build         # emits frontend/dist
# restart the backend; it now serves the UI at http://127.0.0.1:8000/
```

---

## 8. Configuration reference

All values are read from the environment / `backend/.env` by `app/config.py`.

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | — (required) | OpenAI API key. App refuses to start without it. |
| `CHAT_MODEL` | `gpt-4o-mini` | Chat/generation model |
| `EMBED_MODEL` | `text-embedding-3-small` | Embedding model |
| `TOP_K` | `5` | Max retrieved chunks per query |
| `MIN_SIMILARITY` | `0.35` | Minimum cosine similarity to include a chunk |
| `MAX_HISTORY_MESSAGES` | `20` | Messages retained per session |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `1000` / `200` | Ingestion chunking |
| `KNOWLEDGE_DB_PATH` | `backend/knowledge_db.pkl` | Vector store path |
| `ALLOWED_ORIGINS` | `localhost:5173,...` | CORS origins (dev only; prod is same-origin) |
| `FRONTEND_DIST` | `frontend/dist` | Built UI directory to serve |

Example `backend/.env` (PROD):
```ini
OPENAI_API_KEY=sk-...
ALLOWED_ORIGINS=https://vinbot.vinbox.in
```
Keep `.env` readable only by the service account: `chmod 600 backend/.env`.

---

## 9. Environments & deployment

Vinbot runs as three isolated environments, identical in architecture, kept
apart by name, port and directory:

| | DEV | UAT | PROD |
|---|---|---|---|
| Domain | `dev-vinbot.vinbox.in` | `uat-vinbot.vinbox.in` | `vinbot.vinbox.in` |
| systemd unit | `vinbot-dev.service` | `vinbot-uat.service` | `vinbot-prod.service` |
| App directory | `/opt/vinbot-dev` | `/opt/vinbot-uat` | `/opt/vinbot-prod` |
| Service account | `vinbot-dev` | `vinbot-uat` | `vinbot-prod` |
| Uvicorn port | `8010` | `8020` | `8000` |
| Nginx site | `vinbot-dev` | `vinbot-uat` | `vinbot-prod` |

Full step-by-step install/update instructions for each environment are in
**`deploy/DEPLOY.md`**; the systemd units and nginx site files live in `deploy/`.

---

## 10. Verification (go-live checklist, per environment)

Substitute `<ENV_DOMAIN>`, `<APP_SERVER_IP>` and `<PORT>` from the table in §9.

1. `curl -s http://<APP_SERVER_IP>:<PORT>/api/health` on the app server → JSON, chunks > 0.
2. `curl -sk --resolve <ENV_DOMAIN>:443:127.0.0.1 https://<ENV_DOMAIN>/api/health`
   on the edge server → same JSON.
3. `nslookup <ENV_DOMAIN>` → the environment's public IP.
4. Browser → `https://<ENV_DOMAIN>` → padlock, UI loads.
5. Send a message → reply **streams word-by-word**.

---

## 11. Operations

```bash
# --- App server (substitute the environment: dev / uat / prod) ---
sudo systemctl status vinbot-<env> --no-pager
sudo systemctl restart vinbot-<env>          # after .env or code change
sudo journalctl -u vinbot-<env> -f           # live logs

# Redeploy new code:
sudo tar -xzf <release>.tar.gz -C /opt/vinbot-<env> && sudo chown -R vinbot-<env>:vinbot-<env> /opt/vinbot-<env>
cd /opt/vinbot-<env>/backend  && sudo -u vinbot-<env> .venv/bin/pip install -r /opt/vinbot-<env>/requirements.txt
cd /opt/vinbot-<env>/frontend && sudo -u vinbot-<env> npm ci && sudo -u vinbot-<env> npm run build
sudo systemctl restart vinbot-<env>

# --- Edge server (nginx) ---
sudo nginx -t && sudo systemctl reload nginx
sudo tail -f /var/log/nginx/<env-domain>.access.log
sudo tail -f /var/log/nginx/<env-domain>.error.log
```

---

## 12. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `502 Bad Gateway` at the domain | Edge server can't reach the app server's port | Check `vinbot-<env>.service` on the app server and that it binds the expected IP (`ss -ltnp \| grep <PORT>`) |
| Reply appears all at once | nginx buffering the SSE stream | Ensure `proxy_buffering off;` in the vhost |
| `knowledge_chunks: 0` | `knowledge_db.pkl` missing | Restore/rebuild the KB in `/opt/vinbot-<env>/backend/` |
| Backend fails to start | Missing `OPENAI_API_KEY` | Set it in `/opt/vinbot-<env>/backend/.env`, restart |
| `Connection refused` from the edge server | uvicorn bound to `127.0.0.1` only | Bind `--host <APP_SERVER_IP>`, restart |
| Domain doesn't resolve | DNS record missing/wrong | Point the environment's `A` record at its public IP |

---

## 13. Security & hardening

- **Secrets** live only in `/opt/vinbot-<env>/backend/.env` (`chmod 600`, owned
  by that environment's service user); never commit them.
- **Restrict the backend port.** The app server's Uvicorn port only needs to be
  reachable from the edge server for that environment. Limit it via a
  network/security-group rule, deny others.
- **TLS** is handled at the edge (wildcard `*.vinbox.in`); backend traffic stays
  internal over the private network.
- **Run as a non-privileged, per-environment user** (`vinbot-dev` / `vinbot-uat`
  / `vinbot-prod`), not root — this also keeps the three environments'
  filesystem permissions isolated from each other.
- **Environment isolation.** DEV/UAT/PROD use separate directories, service
  accounts, `.env` files and OpenAI API keys, so a DEV/UAT change or credential
  leak cannot affect PROD.

---

## 14. Scaling notes

The single constraint on scaling out is the **in-memory session store**
(`app/sessions.py`): chat history lives in the worker process, so each
environment's service runs one Uvicorn worker. To run multiple workers or
multiple instances (typically only relevant for PROD):

1. Move sessions to a shared store (e.g. Redis).
2. Then raise `--workers`, or add app servers and list them in the edge nginx
   `upstream vinbot_prod_backend { ... }` block.

The retrieval step is an in-process linear scan over the embedded chunks; for
substantially larger knowledge bases, consider a dedicated vector database
(e.g. FAISS, Qdrant, pgvector) behind `app/rag.py`.
