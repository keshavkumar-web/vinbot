"""Unit tests for POST /api/chat (app/main.py).

Isolates the ROUTE contract (session validation, SSE framing, error handling)
from the routing DECISIONS inside app.chat.stream_answer, which are covered
separately in tests/unit/test_chat_router.py. Here we monkeypatch
`app.main.chat_service.stream_answer` itself (the exact name main.py imports
it under: `from . import chat as chat_service`).

REQ-API-05, REQ-API-06, REQ-ERR-01 — see
docs/testing/REQUIREMENT_TRACEABILITY_MATRIX.md.
"""
import json

import pytest

from app import main as main_module

pytestmark = pytest.mark.unit


def _parse_sse(body: str) -> list[dict]:
    frames = []
    for raw in body.split("\n\n"):
        for line in raw.splitlines():
            if line.startswith("data:"):
                frames.append(json.loads(line[len("data:"):].strip()))
    return frames


def test_chat_unknown_session_returns_404(client):
    resp = client.post("/api/chat", json={"session_id": "nope", "message": "hi"})
    assert resp.status_code == 404
    assert "Unknown session_id" in resp.json()["detail"]


def test_chat_empty_message_returns_422(client):
    sid = client.post("/api/session").json()["session_id"]
    resp = client.post("/api/chat", json={"session_id": sid, "message": ""})
    assert resp.status_code == 422


def test_chat_missing_fields_returns_422(client):
    resp = client.post("/api/chat", json={})
    assert resp.status_code == 422


def test_chat_streams_tokens_then_done(client, monkeypatch):
    def fake_stream_answer(history, user_input):
        yield "Hello"
        yield " world"

    monkeypatch.setattr(main_module.chat_service, "stream_answer", fake_stream_answer)

    sid = client.post("/api/session").json()["session_id"]
    resp = client.post("/api/chat", json={"session_id": sid, "message": "hi"})

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.headers["cache-control"] == "no-cache"
    assert resp.headers["x-accel-buffering"] == "no"

    frames = _parse_sse(resp.text)
    assert [f["type"] for f in frames] == ["token", "token", "done"]
    assert "".join(f["content"] for f in frames if f["type"] == "token") == "Hello world"


def test_chat_persists_assistant_reply_to_session_history(client, monkeypatch):
    def fake_stream_answer(history, user_input):
        yield "answer"

    monkeypatch.setattr(main_module.chat_service, "stream_answer", fake_stream_answer)

    sid = client.post("/api/session").json()["session_id"]
    client.post("/api/chat", json={"session_id": sid, "message": "question"})

    history = main_module.store.get(sid)
    assert history == [
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": "answer"},
    ]


def test_chat_yields_error_frame_on_exception(client, monkeypatch):
    def fake_stream_answer(history, user_input):
        yield "partial"
        raise RuntimeError("simulated upstream failure")

    monkeypatch.setattr(main_module.chat_service, "stream_answer", fake_stream_answer)

    sid = client.post("/api/session").json()["session_id"]
    resp = client.post("/api/chat", json={"session_id": sid, "message": "hi"})

    frames = _parse_sse(resp.text)
    assert frames[0] == {"type": "token", "content": "partial"}
    assert frames[-1]["type"] == "error"
    assert "simulated upstream failure" in frames[-1]["message"]
