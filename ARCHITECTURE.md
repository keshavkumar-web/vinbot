# Vinbot — Architecture & File Reference

_Last updated: 2026-06-28_

> **2026-06-28 — LLM intent layer.** The numeric path no longer routes through a
> hardcoded keyword map (`DATASET_CATALOG`, now removed). An LLM reads a catalog
> built live from SQLite and returns a structured `{dataset, metric, entity}`
> selection; the value is still looked up deterministically from SQLite. See
> §7 "LLM intent router". Validated end-to-end at **100% intent accuracy,
> 0% false-positive rate** (`validate_e2e.py`).

A map of **which file does what**, and **what we changed** in each. For the
parameter values (chunk size, models, thresholds) see `CHANGES.md`.

Legend: 🆕 new file · ✏️ modified this project · ▫️ unchanged.

---

## 1. How a question flows through the system

```
Browser (frontend/dist)
   │  POST /api/chat  (Server-Sent Events)
   ▼
app/main.py            ── FastAPI endpoints, streams the reply
   ▼
app/chat.py            ── ROUTER: tables.respond() first; prose -> vector RAG
   ├─────────────► app/tables.py   (structured SQLite lookup, exact, deterministic)
   │                   │
   │                   ├─ build_schema()  reads trusted datasets/columns/rows from SQLite
   │                   ├─ app/intent.py   LLM picks {dataset, metric, entity} as JSON
   │                   │                  (NEVER a value; low confidence -> clarify)
   │                   └─ resolve + exact SQLite lookup -> answer / clarify / not_found
   │
   └─────────────► app/rag.py      (vector search over circulars) ─► OpenAI LLM
```

Conversational context runs BEFORE routing:

```
history + latest message ─► followup.contextualize (LLM rewrite)
    "Domestic" (after "Count in Ambala?") ─────────► "Domestic count in Ambala"
    "And for shifting of meter?" ──────────────────► "Who is the designated officer for shifting of meter?"
    already-standalone / topic change ─────────────► returned unchanged
        └─► the standalone question then enters the router below (numbers still
            from SQLite, prose still from RAG — the rewrite only clarifies intent)
```

Numeric routing in detail (replaces the old keyword catalog):

```
question ─► _PROCEDURAL_RE pre-filter ──(procedural)──► prose (Vector RAG)
         └► build_schema(SQLite) ─► app.intent LLM ─► {status, confidence, selections[]}
              │                                          status=prose ─────► Vector RAG
              │                                          confidence<0.5 ───► clarify
              └► snap_metric() + resolve_entity() ─► exact SQLite read
                    value found ─► answer (+ Source/Row/Column)
                    cell absent ─► not_found     unknown place ─► clarify
```

Two independent knowledge stores feed those two paths:

```
NUMBERS  : UHBVN_new/*.pdf ──build_tables.py──► uhbvn_tables.db (SQLite facts)
POLICY   : knowledge/*.txt ──ingest.py────────► knowledge_db.pkl (embeddings)
```

---

## 2. Backend application — `backend/app/`

| File | Status | What it does |
|---|---|---|
| `main.py` | ▫️ | FastAPI app. Endpoints: `/api/health`, `/api/session`, `/api/chat` (SSE stream), `/api/reset`. Adds CORS, and serves the built frontend (`frontend/dist`) from the same process. |
| `config.py` | ✏️ | Single source of truth for all tunables: models, chunk size, retrieval thresholds, paths, CORS origins, and the **system prompts**. |
| `chat.py` | ✏️ | Orchestration + **router**. First `contextualize()`s the turn (follow-up resolution), then decides structured-vs-prose, returns deterministic numeric answers, or streams the LLM reply for policy questions. |
| `followup.py` | 🆕 | The **conversational-context layer**. Rewrites the latest message into a standalone question using recent history (resolves clarification answers, follow-ups, short replies like "Domestic"/"Rural"/"Zone-I"). Generic — the LLM does coreference, no entity hardcoded; a topic change returns unchanged. Never answers/adds a value. Injectable + lazy OpenAI import. |
| `intent.py` | 🆕 | The **LLM intent layer**. Builds the catalog prompt, calls the chat model in JSON mode, and normalises the reply to `{status, confidence, selections[]}`. Selects identifiers only — never a value. Imports OpenAI lazily, so `tables`/ingestion stay key-free. |
| `rag.py` | ✏️ | The **prose / vector** retrieval layer: loads `knowledge_db.pkl`, embeds the query, cosine-similarity top-K. Now **decomposes multi-part turns** into sub-questions (`split_questions`) and retrieves each separately (`retrieve_context_multi`, round-robin merge) so a turn asking several things doesn't starve most of them of grounding. |
| `tables.py` | ✏️ | The **structured / numeric** engine: PDF table extraction, the SQLite fact store, the trust gate, and the resolver (`respond()`). Routing now uses `intent.py` (LLM) + `build_schema`/`snap_metric`/`resolve_entity` instead of `DATASET_CATALOG`. **Core of the fix.** |
| `sessions.py` | ▫️ | In-memory per-session chat history (why the service runs a single worker). |
| `schemas.py` | ▫️ | Pydantic request/response models for the API. |
| `__init__.py` | ▫️ | Package marker. |

---

## 3. Backend scripts & config — `backend/`

| File | Status | What it does |
|---|---|---|
| `build_tables.py` | 🆕 | CLI to **(re)build `uhbvn_tables.db`** from `UHBVN_new/*.pdf` (calls `tables.build()`). |
| `eval_tables.py` | ✏️ | **Offline test harness** (18 cases): precision, recall, routing, typos, safety. Injects the expected intent via a stub so it runs without a key. Run after any change. |
| `eval_intent_live.py` | 🆕 | Same cases through the **real LLM** router (needs key). Regression gate for prompt/model changes (expect 18/18). |
| `validate_e2e.py` | 🆕 | **Full end-to-end validation**: smokes both flows via `chat.stream_answer`, runs the 5-category battery, and reports intent accuracy / clarification rate / false-positive rate / end-to-end accuracy. |
| `eval_rag.py` | 🆕 | **Multi-part RAG recall regression** (needs key): asserts that a compound prose turn still surfaces in-KB facts (LPS 1.25%, ACD, net metering, CGRF 45 days…). Guards requirement #2 against the smeared-embedding bug. |
| `eval_followup.py` | 🆕 | **Conversational follow-up regression** (needs key): Part A checks the rewriter (clarification answer / follow-up / short reply / topic-change), Part B runs multi-turn conversations end-to-end (e.g. "Count in Ambala"→"Domestic" → 295,224). |
| `ingest.py` | ▫️ | Builds the **prose vector store** (`knowledge_db.pkl`) from `knowledge/*.txt` (chunk → embed). |
| `knowledge_maker.py` | ▫️ | Older/companion vector-store builder (chunk + batched embed). |
| `extract_uhbvn.py` | ▫️ | One-time PDF→text + OCR for the **prose** circulars into `knowledge/`. |
| `requirements.txt` | ▫️ | **Runtime** deps (FastAPI, openai, numpy…). Note: PyMuPDF intentionally NOT here. |
| `requirements-ingest.txt` | ▫️ | **Ingest-only** deps (`pypdf`, `pymupdf`) needed to build the stores. |
| `.env` | 🆕(local) | Holds `OPENAI_API_KEY` and `ALLOWED_ORIGINS`. Not committed. |
| `.env.example` | ▫️ | Template for `.env`. |

---

## 4. Data artifacts — `backend/` and project root

| Path | Status | What it holds |
|---|---|---|
| `UHBVN_new/` (36 PDFs) | 🆕 | Source **numeric reports** (connections, load, transformers, year-wise series…). |
| `uhbvn_tables.db` | 🆕 | SQLite **fact store**: `facts(dataset,row,column,value,unit,period,source)` + a `datasets` meta table with the trust flag. ~10,838 facts. |
| `knowledge/` (*.txt) | ▫️ | Extracted **prose** (sales circulars, compendium, press notes). |
| `knowledge_db.pkl` | ▫️ | Embedded prose chunks for vector search (~7,288 chunks). |

---

## 5. Frontend — `frontend/`

| File | Status | What it does |
|---|---|---|
| `src/main.js` | ▫️ | The chat UI (Vue). |
| `src/api.js` | ▫️ | API client; calls `/api/...` (same origin) and parses the SSE stream. |
| `index.html`, `vite.config.js`, `tailwind.config.js`, `postcss.config.js` | ▫️ | App shell + build config. |
| `dist/` | ▫️ | Built UI served by `app/main.py` in the single-server setup. |

---

## 6. Deployment — `deploy/`

Three environments, same architecture, isolated by name/port/directory (see
`DEPLOY.md` for the full guide):

| File | Status | What it does |
|---|---|---|
| `vinbot-dev.service` | 🆕 | systemd unit for DEV: `uvicorn app.main:app` on port 8010 (single worker). |
| `vinbot-uat.service` | 🆕 | systemd unit for UAT: port 8020 (single worker). |
| `vinbot-prod.service` | 🆕 | systemd unit for PROD: port 8000 (single worker). |
| `nginx-vinbot-dev.conf` | 🆕 | Reverse proxy config for `dev-vinbot.vinbox.in`. |
| `nginx-vinbot-uat.conf` | 🆕 | Reverse proxy config for `uat-vinbot.vinbox.in`. |
| `nginx-vinbot-prod.conf` | 🆕 | Reverse proxy config for `vinbot.vinbox.in`. |

---

## 7. What changed in each modified/new file

### 🆕 `app/tables.py` — the whole numeric engine
- **Extraction**: PyMuPDF `find_tables()` keeps rows/columns intact; multi-row/merged
  headers reconstructed; numbers normalised; one cell = one fact. (`import fitz` is
  **lazy** so the serving app doesn't need PyMuPDF.)
- **Targeted parser** for `consumers.pdf` (irregular side-by-side layout) → correct
  "Consumer Base" / "New Consumers Added" labels.
- **Trust gate** (`_build_meta`): quarantines datasets whose rows are mostly numbers
  (mis-parsed) or whose **column names are garbage** (>80 chars). Quarantined data
  never answers — it says "Data not found" instead of risking a wrong value.
- **Resolver** (`respond()`): keyword → dataset; column = explicitly named (typo-tolerant,
  exact-preferred) else the default **Total**; row = named district / **year / particular**,
  else the Grand-Total row, else the **whole small series**; unknown place → refuse;
  ambiguous → clarify; result capped at 24 rows.
- **Deterministic answers** with `(Source, Row, Column)` provenance — the number never
  passes through the LLM.

### ✏️ `app/chat.py`
- Added the **router** in `stream_answer()`: tries `tables.respond()` first; on
  `answer/clarify/not_found` it returns that **deterministically**; otherwise falls
  back to vector RAG.
- Set chat completion `temperature=0` (stops the LLM improvising figures).
- Removed the now-unused LLM-structured message builder.
- Unchanged by the 2026-06-28 intent work — the `respond()` status contract is
  identical, so the router code did not move.

### 🆕 `app/intent.py` — LLM intent layer (2026-06-28)
- `INTENT_PROMPT` instructs the model to **only select identifiers** copied from a
  catalog, **never emit a value**, default a bare quantity question to the `Total`
  column, return multiple `selections` for compound questions, and choose `prose`
  for procedural/out-of-scope/unknown-topic questions.
- `render_catalog()` serialises the SQLite-derived schema (trusted datasets + exact
  columns + sampled rows, ~3.3K input tokens).
- `extract()` calls the chat model in **JSON mode** (`temperature=0`); `normalise()`
  **fails closed** — any malformed reply degrades to `clarify`, never to an answer.
- `default_extractor()` is injected into `tables.respond()`; tests inject a stub.

### ✏️ `app/tables.py` — routing rewired (DATASET_CATALOG removed)
- `build_schema()` builds the catalog from SQLite (trusted datasets only).
- `snap_metric()` validates the LLM's metric against **real** columns (exact, then
  fuzzy, then an aggregate safety net); `resolve_entity()` validates the row and
  still **refuses unknown places** (e.g. "on the Moon").
- `respond(query, db_path=None, *, extractor=None)` — confidence gate
  (`MIN_CONFIDENCE = 0.5`), per-selection clarify, deterministic SQLite read. The
  number never passes through the LLM. Old file kept at `tables_catalog_backup.py.bak`.

### ✏️ `app/config.py`
- Hardened the prose `SYSTEM_PROMPT`: rule **3a** (never state a figure not in the
  retrieved text; no "example" figures; cite the circular) and **3b** (answer only
  what's asked; skip ungrounded sub-questions).
- Added multi-part retrieval knobs: `RAG_SUBQ_TOPK` (4), `RAG_MAX_CONTEXT_CHUNKS`
  (28), `RAG_MAX_SUBQUESTIONS` (16).

### ✏️ `app/rag.py` — multi-part recall fix (2026-06-28)
- **Problem:** a turn asking several things ("documents? AND deposit? AND net
  metering?") was embedded as ONE smeared vector; the whole-turn top-5 retrieval
  returned generic chunks covering **none** of the specifics, so the bot wrongly
  said "I don't have it" for facts that ARE in the KB (requirement-#2 violation,
  proven: LPS 1.25% is in the Compendium but was denied).
- **Fix:** `split_questions()` breaks the turn on newlines/`?`/list-markers and on
  a conjunction-before-an-interrogative ("…connection, and what is…"), without
  splitting "terms and conditions". `retrieve_context_multi()` batch-embeds the
  sub-questions, scores them against a cached embedding matrix (vectorised), and
  round-robin-merges so every sub-question contributes its best chunks.
- **Result:** the 9-question battery went from **0/4 → 4/4** fact coverage; the
  numeric path and 0% false-positive rate are unchanged.

### 🆕 `app/followup.py` — conversational follow-ups (2026-07-01)
- **Problem:** the router is stateless, so "Domestic" (after "Count in Ambala?"),
  "Rural", "Zone-I", or "And for shifting of meter?" were treated as fresh
  questions and failed.
- **Fix (generic, no entity logic):** `chat.contextualize()` calls an LLM to
  rewrite the latest message into a **standalone question** using the last few
  turns — clarification answers, follow-ups and short replies all resolve through
  the one mechanism; an already-complete or off-topic message is returned
  unchanged (context expires on a topic change). The rewritten query then enters
  the SAME router, so **numbers still come only from SQLite and prose from RAG** —
  this layer never answers or emits a value. Runs only when history exists; on any
  rewrite error it falls back to the raw message (no regression). Toggle:
  `ENABLE_FOLLOWUP_CONTEXT` (default on), window `FOLLOWUP_HISTORY_TURNS` (6).
- **Companion fix in `tables.py`:** `resolve_entity` now ranks candidate rows by
  how many hint tokens they share and keeps only the best, so a specific
  "Kurukshetra Rural" resolves to that one row instead of every "* Rural" row —
  while a bare "Kurukshetra" still returns Rural+Urban. No district/zone is
  special-cased.
- **Validation:** `eval_followup.py` 8/8; full suite still green.

### 🆕 `build_tables.py`, `eval_tables.py`
- New CLI to build the fact store, and the regression/eval harness.

### Documents
- 🆕 `CHANGES.md` — change log + all parameter values.
- 🆕 `ARCHITECTURE.md` — this file.

---

## 8. Coverage status (which numeric reports answer)

- **Answering (verified):** connections, connected load, damaged/distribution
  transformers, collection efficiency, consumers (base/new), year-wise energy
  received/billed & losses, HT-LT ratio, connected-load growth, digital transactions,
  RDS/Urban feeders, power theft, recovery/arrears, service delivery, substations/MVA.
- **Declining by design (never wrong):** the big multi-section files —
  `defaulting_amount`, the per-year `fy_*`, OA-level AT&C losses, `ss_mva`, `atc_arr`,
  `ppmf`. Extraction for these is broken; they need per-layout parsers (like the one
  written for `consumers`) before they can answer safely.

---

## 9. Commands

```bash
cd backend && source .venv/Scripts/activate        # (Windows: .venv\Scripts\activate)
python build_tables.py        # rebuild uhbvn_tables.db from ../UHBVN_new
python ingest.py              # rebuild the prose vector store
python eval_tables.py         # offline regression (stub extractor, no key) — 18/18
python eval_intent_live.py    # live LLM router regression (needs key) — 18/18
python eval_rag.py            # multi-part RAG recall regression (needs key) — 3/3
python eval_followup.py       # conversational follow-up regression (needs key) — 8/8
python validate_e2e.py        # full end-to-end validation + metrics (needs key)
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000   # run locally
# open http://127.0.0.1:8000
```
