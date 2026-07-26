# Vinbot — API Documentation

FastAPI backend (`backend/app/main.py`), app title **"Vinbot API"**. Interactive
Swagger UI is auto-generated at `/docs` (and ReDoc at `/redoc`) on any running
instance.

## Base URL

| Environment | Base URL |
|---|---|
| Local dev | `http://localhost:8000` (frontend dev server proxies `/api` from `http://localhost:5173`) |
| DEV | `https://dev-vinbot.vinbox.in` |
| UAT | `https://uat-vinbot.vinbox.in` |
| PROD | `https://vinbot.vinbox.in` |

All endpoints below are relative to the base URL and are served under `/api`.
In production the same origin also serves the built Vue frontend at `/`, so
there is no CORS to configure; `ALLOWED_ORIGINS` (see Configuration) applies
only to local/dev cross-origin use.

---

## `GET /api/health`

Liveness check. No auth, no parameters.

**Response `200`**
```json
{
  "status": "ok",
  "chat_model": "gpt-4o-mini",
  "embed_model": "text-embedding-3-small",
  "knowledge_chunks": 7288
}
```
- `chat_model` / `embed_model` — the OpenAI models currently configured (`app/config.py`).
- `knowledge_chunks` — number of embedded chunks loaded from `knowledge_db.pkl`.
  `0` means the knowledge base failed to load or is missing — treat as unhealthy.

This endpoint does not check OpenAI reachability or the structured (SQLite)
fact store — it only confirms the process is up and the vector store loaded.

---

## `POST /api/session`

Create a new, empty chat session. No request body.

**Response `200`**
```json
{ "session_id": "b7f1b3b1e9f8412d9f0a2f7e1c9a6a11" }
```
Store `session_id` client-side (e.g. in memory for the tab) and send it with
every subsequent `/api/chat` / `/api/reset` call. Sessions are held **in
server process memory** — they do not survive a backend restart, and are not
shared across multiple Uvicorn workers (see `ADMIN_MANUAL.md` — scaling).

---

## `POST /api/chat`

Send a message and stream the assistant's reply.

**Request body**
```json
{ "session_id": "b7f1b3b1e9f8412d9f0a2f7e1c9a6a11", "message": "How many domestic connections in Karnal?" }
```
| Field | Type | Constraints |
|---|---|---|
| `session_id` | string | must be a session id previously returned by `/api/session` |
| `message` | string | `min_length=1` |

**Errors**
- `404` if `session_id` is unknown (session never created, or backend restarted since).
- `422` if `message` is empty (Pydantic validation).

**Response `200`** — `Content-Type: text/event-stream` (Server-Sent Events).
The connection stays open and streams frames as the model generates tokens:

```
data: {"type": "token", "content": "UHBVN"}

data: {"type": "token", "content": " stands"}

data: {"type": "token", "content": " for..."}

data: {"type": "done"}

```

Each frame is `data: <json>\n\n`. Three frame `type`s:
| `type` | Meaning |
|---|---|
| `token` | One incremental piece of the reply; `content` is the text to append. |
| `done` | The reply is complete. No more frames follow. |
| `error` | Something failed mid-stream; `message` describes it. No `done` frame follows an `error` frame. |

Response headers set by the server (required for streaming to work correctly
behind a reverse proxy): `Cache-Control: no-cache`, `Connection: keep-alive`,
`X-Accel-Buffering: no`. A reverse proxy in front of Vinbot **must** disable
response buffering (e.g. Nginx `proxy_buffering off;`) or the reply will
arrive all at once instead of token-by-token — see `deploy/nginx-vinbot-*.conf`.

**Note on answer sourcing** — Vinbot routes each question through a
deterministic structured lookup (exact figures from the fact store, with
`(Source, Row, Column)` provenance in the text) before falling back to
retrieval-augmented generation over the document knowledge base. This routing
is internal; the API surface is the same regardless of which path answered.

---

## `POST /api/reset`

Clear a session's conversation history (the session id itself remains valid).

**Request body**
```json
{ "session_id": "b7f1b3b1e9f8412d9f0a2f7e1c9a6a11" }
```

**Response `200`**
```json
{ "ok": true }
```
**Errors**: `404` if `session_id` is unknown.

---

## Error format

Validation and not-found errors use FastAPI's default shape:
```json
{ "detail": "Unknown session_id" }
```

## Configuration affecting the API

Set via `backend/.env` / environment (`app/config.py`); see `ADMIN_MANUAL.md`
for the full reference table.

| Variable | Affects |
|---|---|
| `ALLOWED_ORIGINS` | CORS — which origins may call the API cross-origin (dev only) |
| `MAX_HISTORY_MESSAGES` | How many prior messages are kept/sent per session |
| `CHAT_MODEL` / `EMBED_MODEL` | Which OpenAI models answer `/api/health` reports and `/api/chat` uses |
