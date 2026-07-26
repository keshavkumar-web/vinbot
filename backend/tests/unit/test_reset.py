"""Unit tests for POST /api/reset (app/main.py).

REQ-API-04 — see docs/testing/REQUIREMENT_TRACEABILITY_MATRIX.md.
"""
import pytest

pytestmark = pytest.mark.unit


def test_reset_valid_session_returns_ok(client):
    sid = client.post("/api/session").json()["session_id"]
    resp = client.post("/api/reset", json={"session_id": sid})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_reset_unknown_session_returns_404(client):
    resp = client.post("/api/reset", json={"session_id": "does-not-exist"})
    assert resp.status_code == 404
    assert "Unknown session_id" in resp.json()["detail"]


def test_reset_missing_session_id_field_returns_422(client):
    resp = client.post("/api/reset", json={})
    assert resp.status_code == 422
