"""Integration test: a real SQLite fact store, wired to app.tables.DB_PATH,
answering a real chat request through the full API — proving the structured
(numeric) path and the HTTP layer work together, not just tables.respond() in
isolation (see tests/unit/test_tables.py for that).

REQ-INT-05, REQ-TABLES-06 — see docs/testing/REQUIREMENT_TRACEABILITY_MATRIX.md.
"""
import json

import pytest

from app import intent, tables

pytestmark = pytest.mark.integration


def _reconstruct_reply(sse_body: str) -> str:
    text = ""
    for raw in sse_body.split("\n\n"):
        for line in raw.splitlines():
            if line.startswith("data:"):
                payload = json.loads(line[len("data:"):].strip())
                if payload.get("type") == "token":
                    text += payload["content"]
    return text


def test_chat_answers_from_real_sqlite_fact_store(client, temp_tables_db, monkeypatch):
    monkeypatch.setattr(tables, "DB_PATH", str(temp_tables_db))
    # Force deterministic routing without a live LLM call, exactly like
    # eval_tables.py does for its offline regression suite.
    fixed_intent = {"status": "answer", "confidence": 0.95, "selections": [
        {"dataset": "connection", "metric": "Total", "entity": "Karnal", "period": None}]}
    monkeypatch.setattr(intent, "default_extractor", lambda query, schema: fixed_intent)

    session_id = client.post("/api/session").json()["session_id"]
    resp = client.post("/api/chat", json={
        "session_id": session_id, "message": "how many connections in Karnal"})

    reply = _reconstruct_reply(resp.text)
    assert "543,445" in reply
    assert "(Source: 1_Connection.pdf, Row: Karnal, Column: Total)" in reply


def test_chat_never_serves_wrong_value_for_unknown_place(client, temp_tables_db, monkeypatch):
    """DB interaction safety check: an unrecognised district must clarify,
    never silently substitute the Grand Total."""
    monkeypatch.setattr(tables, "DB_PATH", str(temp_tables_db))
    fixed_intent = {"status": "answer", "confidence": 0.9, "selections": [
        {"dataset": "connection", "metric": "Total", "entity": "Atlantis", "period": None}]}
    monkeypatch.setattr(intent, "default_extractor", lambda query, schema: fixed_intent)

    session_id = client.post("/api/session").json()["session_id"]
    resp = client.post("/api/chat", json={
        "session_id": session_id, "message": "connections in Atlantis"})

    reply = _reconstruct_reply(resp.text)
    assert "3,892,250" not in reply
