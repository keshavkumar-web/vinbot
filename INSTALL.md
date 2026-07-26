# Vinbot — Installation Guide

This guide covers installing Vinbot **for local development**. For installing
a DEV/UAT/PROD server environment, see `deploy/DEPLOY.md`.

## Prerequisites

| Requirement | Version | Used for |
|---|---|---|
| Python | 3.11+ (3.10 minimum — code uses `str \| None` syntax) | Backend (FastAPI) |
| Node.js | 20+ | Frontend build (Vite) |
| OpenAI API key | — | Chat + embedding models (required; the backend refuses to start without one) |

## 1. Get the project

Copy/clone the `Vinbot/` project folder to your machine.

## 2. Backend install

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # Windows (PowerShell: .venv\Scripts\Activate.ps1)
# source .venv/bin/activate       # macOS/Linux
pip install -r requirements.txt
```

Create your local secrets file:
```bash
copy .env.example .env            # Windows
# cp .env.example .env            # macOS/Linux
```
Edit `backend/.env` and set:
```ini
OPENAI_API_KEY=sk-...your-key...
```
All other settings (`CHAT_MODEL`, `TOP_K`, `MIN_SIMILARITY`, `ALLOWED_ORIGINS`,
etc.) have working defaults in `app/config.py` — override only if needed. See
`API_DOCUMENTATION.md` §"Configuration" for the full list.

### 2a. Knowledge base

The repository already ships a built knowledge base
(`backend/knowledge_db.pkl`) and structured fact store
(`backend/uhbvn_tables.db`). **If these files are present, skip straight to
step 3** — you do not need to rebuild anything to run Vinbot locally.

Only rebuild if you are changing the source documents:
```bash
pip install -r requirements-ingest.txt   # one-time: pypdf + pymupdf
python extract_uhbvn.py                   # source PDFs -> backend/knowledge/*.txt
python knowledge_maker.py                 # knowledge/*.txt -> knowledge_db.pkl
python build_tables.py                    # UHBVN_new/*.pdf -> uhbvn_tables.db (structured facts)
```

### 2b. Run the backend

```bash
uvicorn app.main:app --reload --port 8000
```

Verify: open http://localhost:8000/api/health — should return JSON with
`knowledge_chunks` greater than 0. Interactive API docs at
http://localhost:8000/docs.

## 3. Frontend install

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 — the Vite dev server proxies `/api` requests to
the backend on port 8000, so **both processes must be running**.

## 4. Verify the install

1. http://localhost:8000/api/health → `{"status": "ok", ...}`.
2. http://localhost:5173 → chat UI loads, shows the welcome message.
3. Send a test question → reply streams in token-by-token.
4. Click **New chat** → the conversation clears.

If step 3 fails with a connection error, confirm both the backend (port 8000)
and frontend (port 5173) processes are running and that `OPENAI_API_KEY` is
set in `backend/.env`.

## Next steps

- **Deploying to a server** (DEV/UAT/PROD): `deploy/DEPLOY.md`.
- **API contract**: `API_DOCUMENTATION.md`.
- **Using the chat UI**: `USER_MANUAL.md`.
- **Operating a running instance**: `ADMIN_MANUAL.md`.
