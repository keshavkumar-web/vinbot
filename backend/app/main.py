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
from .logger import get_logger
from .schemas import ChatRequest, ResetRequest, SessionResponse, SimpleResponse
from .sessions import store

logger = get_logger(__name__)

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
    logger.info("Vinbot API starting up.")
    rag.load_knowledge()
    logger.info("Startup complete. knowledge_chunks=%d", len(rag.get_knowledge_db()))


@app.on_event("shutdown")
def _log_shutdown() -> None:
    logger.info("Vinbot API shutting down.")


def _sse(payload: dict) -> str:
    """Encode a payload as a single Server-Sent Event frame."""
    return f"data: {json.dumps(payload)}\n\n"


@app.get("/api/health")
def health() -> dict:
    result = {
        "status": "ok",
        "chat_model": config.CHAT_MODEL,
        "embed_model": config.EMBED_MODEL,
        "knowledge_chunks": len(rag.get_knowledge_db()),
    }
    logger.info("Health check requested. knowledge_chunks=%d", result["knowledge_chunks"])
    return result


@app.post("/api/session", response_model=SessionResponse)
def create_session() -> SessionResponse:
    session_id = store.create()
    logger.info("Session created. session_id=%s", session_id)
    return SessionResponse(session_id=session_id)


@app.post("/api/reset", response_model=SimpleResponse)
def reset_session(req: ResetRequest) -> SimpleResponse:
    if not store.exists(req.session_id):
        logger.warning("Reset requested for unknown session_id=%s", req.session_id)
        raise HTTPException(status_code=404, detail="Unknown session_id")
    store.reset(req.session_id)
    logger.info("Session reset. session_id=%s", req.session_id)
    return SimpleResponse(ok=True)


@app.post("/api/chat")
def chat(req: ChatRequest) -> StreamingResponse:
    if not store.exists(req.session_id):
        logger.warning("Chat requested for unknown session_id=%s", req.session_id)
        raise HTTPException(status_code=404, detail="Unknown session_id")

    # Never log req.message itself (may contain sensitive consumer details) —
    # only its length, alongside the session_id, per the logging policy.
    logger.info(
        "Chat request received. session_id=%s message_length=%d",
        req.session_id, len(req.message),
    )

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
            logger.info(
                "Response generation completed. session_id=%s response_length=%d",
                req.session_id, len(answer),
            )
            yield _sse({"type": "done"})
        except Exception as exc:  # surface failures to the client instead of hanging
            logger.exception(
                "Unexpected error while streaming chat response. session_id=%s",
                req.session_id,
            )
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
    logger.info("Serving frontend from %s", _FRONTEND_DIST)
else:
    logger.info("Frontend build not found at %s; serving API only.", _FRONTEND_DIST)
