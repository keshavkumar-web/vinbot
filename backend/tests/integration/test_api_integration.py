"""Integration tests: the full FastAPI app (real routes, real chat.stream_answer
routing, real SessionStore) driven end-to-end through TestClient. Only the
OpenAI network boundary is mocked (via conftest's mock_openai_* fixtures) —
everything else is the real, unmodified application.

REQ-INT-01..04 — see docs/testing/REQUIREMENT_TRACEABILITY_MATRIX.md.
"""
import json

import pytest

pytestmark = pytest.mark.integration


def _reconstruct_reply(sse_body: str) -> str:
    """Concatenate every 'token' frame's content, mirroring how
    frontend/src/api.js reassembles the streamed reply."""
    text = ""
    for raw in sse_body.split("\n\n"):
        for line in raw.splitlines():
            if line.startswith("data:"):
                payload = json.loads(line[len("data:"):].strip())
                if payload.get("type") == "token":
                    text += payload["content"]
    return text


def test_full_session_chat_reset_lifecycle(client, mock_openai_chat, mock_openai_embeddings):
    """Session creation -> chat -> reset, exactly as the frontend uses the API
    (see frontend/src/api.js)."""
    mock_openai_chat["reply"] = "This is a grounded test reply."

    session_id = client.post("/api/session").json()["session_id"]

    chat_resp = client.post("/api/chat", json={"session_id": session_id, "message": "Hello"})
    assert chat_resp.status_code == 200
    assert _reconstruct_reply(chat_resp.text) == "This is a grounded test reply."

    reset_resp = client.post("/api/reset", json={"session_id": session_id})
    assert reset_resp.status_code == 200
    assert reset_resp.json() == {"ok": True}

    # session id remains valid after reset (per app/sessions.py: reset keeps the id)
    second_chat = client.post("/api/chat", json={"session_id": session_id, "message": "Hi again"})
    assert second_chat.status_code == 200


def test_chat_without_a_session_is_rejected(client):
    resp = client.post("/api/chat", json={"session_id": "never-created", "message": "hi"})
    assert resp.status_code == 404


def test_health_reflects_real_config_module(client):
    from app import config
    body = client.get("/api/health").json()
    assert body["chat_model"] == config.CHAT_MODEL
    assert body["embed_model"] == config.EMBED_MODEL
    assert "knowledge_chunks" in body


def test_conversation_history_flows_through_real_session_store(client, mock_openai_chat,
                                                                 mock_openai_embeddings):
    from app.main import store

    mock_openai_chat["reply"] = "answer one"
    session_id = client.post("/api/session").json()["session_id"]
    client.post("/api/chat", json={"session_id": session_id, "message": "question one"})

    history = store.get(session_id)
    assert history == [
        {"role": "user", "content": "question one"},
        {"role": "assistant", "content": "answer one"},
    ]
