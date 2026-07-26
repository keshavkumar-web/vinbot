"""Integration test: a real pickled knowledge base file, loaded through the
real app.rag.load_knowledge()/FastAPI startup path (not a monkeypatched
in-memory list) — proving the on-disk format the app actually ships
(`knowledge_db.pkl`) loads and serves correctly end-to-end.

REQ-INT-06, REQ-RAG-07 — see docs/testing/REQUIREMENT_TRACEABILITY_MATRIX.md.
"""
import pickle
from pathlib import Path

import pytest

from app import config, rag

pytestmark = pytest.mark.integration


def test_health_endpoint_reflects_a_real_pickle_file(client, tmp_path, monkeypatch):
    chunks = [
        {"source": "a.txt", "chunk_id": 0, "text": "Sample circular text one.",
         "embedding": [0.1, 0.2, 0.3]},
        {"source": "b.txt", "chunk_id": 1, "text": "Sample circular text two.",
         "embedding": [0.4, 0.1, 0.0]},
    ]
    pkl_path = tmp_path / "real_shaped_knowledge_db.pkl"
    with open(pkl_path, "wb") as fh:
        pickle.dump(chunks, fh)

    rag.load_knowledge(str(pkl_path))

    body = client.get("/api/health").json()
    assert body["knowledge_chunks"] == 2


def test_load_knowledge_missing_file_degrades_to_empty_list(tmp_path):
    """Edge case: knowledge base file missing entirely — must not crash the
    process (see app/rag.py's own warning-and-continue behavior)."""
    missing = tmp_path / "does_not_exist.pkl"
    result = rag.load_knowledge(str(missing))
    assert result == []


@pytest.mark.slow
def test_shipped_knowledge_db_loads_if_present():
    """Read-only sanity check against the REAL production knowledge_db.pkl
    shipped in this repo (backend/knowledge_db.pkl) — skipped automatically
    if it isn't present (e.g. a lightweight checkout)."""
    real_path = Path(config.BACKEND_DIR) / "knowledge_db.pkl"
    if not real_path.exists():
        pytest.skip("backend/knowledge_db.pkl not present in this checkout")

    chunks = rag.load_knowledge(str(real_path))
    assert isinstance(chunks, list)
    assert len(chunks) > 0
    sample = chunks[0]
    assert "source" in sample and "text" in sample and "embedding" in sample
