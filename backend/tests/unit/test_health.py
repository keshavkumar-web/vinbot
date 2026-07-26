"""Unit tests for GET /api/health (app/main.py).

REQ-API-01, REQ-API-02 — see docs/testing/REQUIREMENT_TRACEABILITY_MATRIX.md.
"""
import pytest

pytestmark = pytest.mark.unit


def test_health_returns_ok_status(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"


def test_health_reports_configured_models(client):
    from app import config
    body = client.get("/api/health").json()
    assert body["chat_model"] == config.CHAT_MODEL
    assert body["embed_model"] == config.EMBED_MODEL


def test_health_reports_zero_chunks_on_empty_knowledge_base(client):
    """Edge case: empty knowledge base (the conftest default state) must be
    reported honestly as 0 chunks, not hidden or errored."""
    body = client.get("/api/health").json()
    assert body["knowledge_chunks"] == 0


def test_health_reports_chunk_count_after_kb_loaded(client, load_sample_kb):
    body = client.get("/api/health").json()
    assert body["knowledge_chunks"] == len(load_sample_kb)
