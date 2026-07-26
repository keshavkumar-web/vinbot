"""Unit tests for POST /api/session (app/main.py) and SessionStore (app/sessions.py).

REQ-API-03, REQ-SESS-01..04 — see docs/testing/REQUIREMENT_TRACEABILITY_MATRIX.md.
"""
import pytest

from app import config

pytestmark = pytest.mark.unit


# --- API route ---------------------------------------------------------
def test_create_session_returns_session_id(client):
    resp = client.post("/api/session")
    assert resp.status_code == 200
    body = resp.json()
    assert "session_id" in body
    assert isinstance(body["session_id"], str)
    assert len(body["session_id"]) > 0


def test_create_session_returns_unique_ids(client):
    a = client.post("/api/session").json()["session_id"]
    b = client.post("/api/session").json()["session_id"]
    assert a != b


# --- SessionStore unit tests (no HTTP layer) ----------------------------
def test_store_create_then_exists(fresh_session_store):
    sid = fresh_session_store.create()
    assert fresh_session_store.exists(sid)


def test_store_unknown_session_does_not_exist(fresh_session_store):
    assert not fresh_session_store.exists("not-a-real-session-id")


def test_store_get_returns_empty_history_for_new_session(fresh_session_store):
    sid = fresh_session_store.create()
    assert fresh_session_store.get(sid) == []


def test_store_append_adds_message(fresh_session_store):
    sid = fresh_session_store.create()
    fresh_session_store.append(sid, "user", "hello")
    history = fresh_session_store.get(sid)
    assert history == [{"role": "user", "content": "hello"}]


def test_store_get_returns_a_copy_not_a_live_reference(fresh_session_store):
    """app/sessions.py docstring: get() returns a copy safe to iterate
    without holding the lock — mutating the returned list must not corrupt
    the store's internal state."""
    sid = fresh_session_store.create()
    fresh_session_store.append(sid, "user", "hello")
    history = fresh_session_store.get(sid)
    history.append({"role": "user", "content": "mutated externally"})
    assert fresh_session_store.get(sid) == [{"role": "user", "content": "hello"}]


def test_store_trims_history_to_max_history_messages(fresh_session_store):
    sid = fresh_session_store.create()
    total_to_add = config.MAX_HISTORY_MESSAGES + 10
    for i in range(total_to_add):
        fresh_session_store.append(sid, "user", f"message {i}")
    history = fresh_session_store.get(sid)
    assert len(history) == config.MAX_HISTORY_MESSAGES
    # the sliding window keeps the MOST RECENT messages
    assert history[-1]["content"] == f"message {total_to_add - 1}"


def test_store_reset_clears_history_but_keeps_session_id(fresh_session_store):
    sid = fresh_session_store.create()
    fresh_session_store.append(sid, "user", "hello")
    fresh_session_store.reset(sid)
    assert fresh_session_store.exists(sid)
    assert fresh_session_store.get(sid) == []
