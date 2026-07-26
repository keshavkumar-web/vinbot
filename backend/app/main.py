"""FastAPI application exposing the RAG chatbot to the Vue frontend.

Endpoints
---------
GET  /api/health           Liveness + knowledge-base size.
POST /api/session          Create a new chat session, returns a session_id.
POST /api/chat             Stream the assistant's reply (Server-Sent Events).
POST /api/reset            Clear a session's conversation history.
"""

import json
import os
from collections.abc import Iterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import chat as chat_service
from . import config, rag
from .schemas import ChatRequest, ResetRequest, SessionResponse, SimpleResponse
from .sessions import store

app = FastAPI(title="Vinbot API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _load_knowledge_on_startup() -> None:
    # Warm the knowledge base so the first request isn't slow (and we log its size).
    rag.load_knowledge()


def _sse(payload: dict) -> str:
    """Encode a payload as a single Server-Sent Event frame."""
    return f"data: {json.dumps(payload)}\n\n"


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "chat_model": config.CHAT_MODEL,
        "embed_model": config.EMBED_MODEL,
        "knowledge_chunks": len(rag.get_knowledge_db()),
    }


@app.post("/api/session", response_model=SessionResponse)
def create_session() -> SessionResponse:
    return SessionResponse(session_id=store.create())


@app.post("/api/reset", response_model=SimpleResponse)
def reset_session(req: ResetRequest) -> SimpleResponse:
    if not store.exists(req.session_id):
        raise HTTPException(status_code=404, detail="Unknown session_id")
    store.reset(req.session_id)
    return SimpleResponse(ok=True)


@app.post("/api/chat")
def chat(req: ChatRequest) -> StreamingResponse:
    if not store.exists(req.session_id):
        raise HTTPException(status_code=404, detail="Unknown session_id")

    # Snapshot history BEFORE adding the new turn, then persist the user message.
    history = store.get(req.session_id)
    store.append(req.session_id, "user", req.message)

    def event_stream() -> Iterator[str]:
        collected: list[str] = []
        try:
            for token in chat_service.stream_answer(history, req.message):
                collected.append(token)
                yield _sse({"type": "token", "content": token})

            answer = "".join(collected)
            store.append(req.session_id, "assistant", answer)
            yield _sse({"type": "done"})
        except Exception as exc:  # surface failures to the client instead of hanging
            yield _sse({"type": "error", "message": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable proxy buffering for live streaming
        },
    )


# --- Serve the built frontend (single-server deployment) --------------------
# In production the Vue app is built to frontend/dist and served by THIS same
# process, so the UI and the API share one origin (no Nginx, no CORS needed).
# Mounted LAST so every /api route above takes precedence over the catch-all.
# Skipped gracefully when the build is absent (e.g. local dev via Vite).
_FRONTEND_DIST = os.getenv(
    "FRONTEND_DIST",
    os.path.join(os.path.dirname(config.BACKEND_DIR), "frontend", "dist"),
)
if os.path.isdir(_FRONTEND_DIST):
    app.mount("/", StaticFiles(directory=_FRONTEND_DIST, html=True), name="frontend")
    print(f"[main] Serving frontend from {_FRONTEND_DIST}")
else:
    print(f"[main] Frontend build not found at {_FRONTEND_DIST}; serving API only.")
