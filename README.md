# Vinbot

A retrieval-augmented (RAG) chatbot platform, built by **Vinbox Martech Pvt
Ltd**. This deployment is configured for **UHBVN (Uttar Haryana Bijli Vitran
Nigam)** with a **FastAPI** backend and a **Vue 3 + Vite + Tailwind** frontend.
It answers from UHBVN's own documents — the Compendium of Sales Circulars &
Instructions, individual Sales Circulars, Press Notes, etc. — and streams
replies token-by-token.

```
Vinbot/
├── backend/                  FastAPI service + RAG logic + ingestion
│   ├── app/
│   │   ├── config.py         models, retrieval thresholds, paths, prompt
│   │   ├── rag.py            embeddings, cosine retrieval, KB loading
│   │   ├── chat.py           streaming chat generator
│   │   ├── sessions.py       in-memory per-session history
│   │   ├── schemas.py        request/response models
│   │   └── main.py           API: /api/session, /api/chat (SSE), /api/reset, /api/health
│   ├── knowledge/            extracted UHBVN documents (txt) — the KB source
│   ├── extract_uhbvn.py      PDF -> txt (pypdf text + OpenAI-vision OCR for scans)
│   ├── knowledge_maker.py    builds knowledge_db.pkl from knowledge/ (batched)
│   ├── requirements.txt      runtime deps
│   └── requirements-ingest.txt  extra deps for extract_uhbvn.py (pypdf, pymupdf)
├── frontend/                 Vue chat UI (streaming)
├── UHBVN_new/                source PDFs for the structured (numeric) reports (git-ignored)
└── deploy/                   systemd units + nginx configs + install scripts (DEV/UAT/PROD)
```

> See `INSTALL.md` for a step-by-step setup walkthrough, `API_DOCUMENTATION.md`
> for the API contract, `USER_MANUAL.md` for the chat UI, and `ADMIN_MANUAL.md`
> for operating a deployed instance.

## 1. Backend setup

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # Windows (PowerShell: .venv\Scripts\Activate.ps1)
# source .venv/bin/activate       # macOS/Linux
pip install -r requirements.txt
```

Provide an OpenAI key (recommended over the fallback in `config.py`):

```bash
copy .env.example .env            # then edit OPENAI_API_KEY
```

### Build the knowledge base

The knowledge base is built in two steps. **If you already have a
`knowledge_db.pkl`, you can skip both and just run the API.**

**Step A — extract the UHBVN PDFs to text** (only when (re)building from PDFs):

```bash
pip install -r requirements-ingest.txt   # pypdf + pymupdf (one-time)
python extract_uhbvn.py                   # UHBVN/*.pdf -> knowledge/*.txt
```

`extract_uhbvn.py` uses the PDF text layer where present, and **OCRs scanned
pages via the OpenAI vision model** (no Tesseract/poppler needed). It is
resumable — a `.txt` that already exists is skipped; delete it to re-extract.

**Step B — embed the text into the vector store:**

```bash
python knowledge_maker.py         # knowledge/*.txt -> knowledge_db.pkl (batched)
```

> The current KB is ~7,700 chunks (`knowledge_db.pkl` ≈ 100 MB). Embeddings are
> sent in batches of 100, so a full rebuild is dozens of API calls, not thousands.

### Run the API

```bash
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000/api/health — it reports the loaded knowledge-chunk
count. Interactive docs at http://localhost:8000/docs.

## 2. Frontend setup

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The dev server proxies `/api` to the backend on
port 8000, so both must be running.

## 3. Testing

Vinbot has a full test suite: pytest unit + integration tests, a standalone
smoke-test script, and a Postman/Newman API suite.

```bash
cd backend
pip install -r requirements-test.txt
pytest -v                          # unit + integration; auto-writes ../reports/
python tests/smoke/smoke.py --start-server
cd ../postman && npm install && npm run test:local
```

See `backend/tests/README.md` for full usage, `TEST_MATRIX.md` for
module-vs-test-level coverage, and `docs/testing/` for the system/UAT/RITES
assessment documentation set. Generated reports (JUnit XML, HTML, coverage,
dashboard) land in `reports/`.

## How it works

1. The UI requests a `session_id` (`POST /api/session`).
2. Each message is sent to `POST /api/chat`; the backend embeds the question,
   retrieves the top matching UHBVN knowledge chunks (cosine similarity), and
   calls the chat model with the system prompt + history + retrieved context.
3. The reply streams back as Server-Sent Events and renders live (Markdown).
4. History is kept server-side per session (sliding window of the last
   `MAX_HISTORY_MESSAGES` messages). "New chat" clears it.

## Notes

- The in-memory session store is per-process. For multiple workers/instances,
  back it with Redis or a database.
- `knowledge_db.pkl` is a pickle; only load files you generated yourself.
- Re-run **Step A + Step B** whenever the UHBVN source PDFs change; re-run just
  **Step B** when you edit the `knowledge/*.txt` files directly.
- OCR of scanned regulatory documents is strong but not flawless — spot-check
  critical figures (specific charges, dates) against the source PDF.
