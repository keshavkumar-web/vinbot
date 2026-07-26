"""Integration test: consumes the real StreamingResponse from POST /api/chat
incrementally (httpx streaming, the same transport frontend/src/api.js's
fetch+reader loop relies on), rather than reading the fully-buffered body —
proving the response is actually a live stream of separate SSE frames, and
that the anti-buffering headers required by deploy/nginx-vinbot-*.conf
(`proxy_buffering off`) are present.

REQ-INT-07, REQ-API-06 — see docs/testing/REQUIREMENT_TRACEABILITY_MATRIX.md.
"""
import json

import pytest

pytestmark = pytest.mark.integration


def test_chat_response_streams_as_multiple_sse_frames(client, mock_openai_chat,
                                                        mock_openai_embeddings):
    mock_openai_chat["tokens"] = ["Hel", "lo", " world"]

    session_id = client.post("/api/session").json()["session_id"]

    frames = []
    with client.stream("POST", "/api/chat",
                        json={"session_id": session_id, "message": "hi"}) as resp:
        assert resp.status_code == 200
        assert resp.headers["cache-control"] == "no-cache"
        assert resp.headers["connection"] == "keep-alive"
        assert resp.headers["x-accel-buffering"] == "no"

        buffer = ""
        for chunk in resp.iter_text():
            buffer += chunk
            *complete, buffer = buffer.split("\n\n")
            for raw in complete:
                for line in raw.splitlines():
                    if line.startswith("data:"):
                        frames.append(json.loads(line[len("data:"):].strip()))

    assert [f["type"] for f in frames] == ["token", "token", "token", "done"]
    assert "".join(f["content"] for f in frames if f["type"] == "token") == "Hello world"
