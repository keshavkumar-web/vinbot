"""Shared pytest fixtures for the Vinbot backend test suite.

Sets an isolated test environment (dummy API key, temp knowledge/db paths)
BEFORE any `app.*` module is imported, so the suite never touches the real
production `knowledge_db.pkl` / `uhbvn_tables.db` and never requires a live
OpenAI key. This mirrors the injectable-extractor / overridable-path seams
that already exist in `app.tables` and `app.rag` (see their docstrings) —
no application code changes were needed to make this possible.
"""
from __future__ import annotations

import hashlib
import os
import pickle
import sqlite3
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# --- Isolated environment — set before any `app` import ---------------------
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-key-not-real")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost:5173")

_FIXTURES_DIR = BACKEND_DIR / "tests" / "_fixtures"
_FIXTURES_DIR.mkdir(exist_ok=True)

_EMPTY_KB = _FIXTURES_DIR / "empty_knowledge_db.pkl"
if not _EMPTY_KB.exists():
    with open(_EMPTY_KB, "wb") as fh:
        pickle.dump([], fh)

# Point the app at the empty fixture KB and a fact-store path that does not
# exist, so a freshly-imported app starts from a known, empty state — the
# same "missing DB" state `tables.respond()` already handles by design
# (falls back to status="prose"; see app/tables.py).
os.environ.setdefault("KNOWLEDGE_DB_PATH", str(_EMPTY_KB))
os.environ.setdefault("TABLES_DB_PATH", str(_FIXTURES_DIR / "no_such_tables.db"))

from app import config, glossary, rag, sessions as sessions_module, tables  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_knowledge_base():
    """Every test starts from the empty fixture KB, never leftover state from
    a previous test (autouse fixtures run before explicitly-requested ones of
    the same scope, so this always resets before e.g. `load_sample_kb`).

    Also resets app.glossary's module-level index cache (`_index`,
    `_category_index`), which it builds once from whatever
    `rag.get_knowledge_db()` returns the first time it's called and never
    invalidates on its own — without this reset, whichever test happens to
    run first would silently pin the glossary index for every later test.
    """
    rag.load_knowledge(str(_EMPTY_KB))
    glossary._index = None
    glossary._category_index = None
    yield


@pytest.fixture
def client():
    """A TestClient over the REAL app object from app.main — same routes,
    same middleware, same startup event as production."""
    with TestClient(fastapi_app) as c:
        yield c


@pytest.fixture
def fresh_session_store():
    """A brand-new SessionStore, isolated from the app's global `store`."""
    return sessions_module.SessionStore()


@pytest.fixture
def sample_knowledge_chunks():
    """A small, realistic knowledge_db list covering the two glossary chunk
    shapes `app.glossary` actually parses, plus ordinary prose chunks.

    Embeddings are 8-dimensional placeholder vectors — the SAME dimension
    `mock_openai_embeddings`' `_text_vector()` produces — so a test that
    combines `load_sample_kb` with `mock_openai_embeddings` (e.g. a RAG
    fallback through the real router) never hits a shape mismatch in
    `rag.cosine_similarity`. Tests that need ranking to pick a SPECIFIC
    chunk build their own embeddings via `rag.create_embedding()` instead
    (see tests/unit/test_rag.py) rather than relying on these placeholders.
    """
    return [
        {"source": "SC_U_01_2026.txt", "chunk_id": 0,
         "text": "The security deposit (Advance Consumption Deposit) for domestic "
                 "supply is Rs.750 per KW as per Sales Circular U-01/2026.",
         "embedding": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]},
        {"source": "SC_U_01_2026.txt", "chunk_id": 1,
         "text": "Late Payment Surcharge (LPS) is levied at 1.25% per month on "
                 "overdue electricity bills.",
         "embedding": [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]},
        {"source": "Haryana_DISCOM_Abbreviations.txt", "chunk_id": 2,
         "text": "SDO\nFull Form: Sub Divisional Officer\n"
                 "Description: Officer in charge of a sub-division.\n"
                 "Category: Administrative",
         "embedding": [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0]},
        {"source": "Electricity_Department_Abbreviations.txt", "chunk_id": 3,
         "text": "AT&C Loss - Aggregate Technical & Commercial loss, a measure of "
                 "energy and revenue loss in distribution.",
         "embedding": [0.5, 0.5, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]},
    ]


@pytest.fixture
def load_sample_kb(sample_knowledge_chunks, tmp_path):
    """Load `sample_knowledge_chunks` as the active knowledge base for a test."""
    path = tmp_path / "sample_knowledge_db.pkl"
    with open(path, "wb") as fh:
        pickle.dump(sample_knowledge_chunks, fh)
    rag.load_knowledge(str(path))
    return sample_knowledge_chunks


@pytest.fixture
def temp_tables_db(tmp_path):
    """A real, minimal SQLite fact store in the exact schema `tables.build()`
    writes (see app/tables.py), with one TRUSTED dataset ('connection') and
    rows a test can look up deterministically."""
    db_path = tmp_path / "test_tables.db"
    con = sqlite3.connect(str(db_path))
    con.execute("""
        CREATE TABLE facts(
            dataset TEXT, source TEXT, title TEXT, period TEXT, unit TEXT,
            entity TEXT, metric TEXT, value REAL,
            entity_l TEXT, metric_l TEXT
        )""")
    rows = [
        ("connection", "1_Connection.pdf", "Number of Consumers", "March 2026", "count",
         "Karnal", "Total", 543445.0, "karnal", "total"),
        ("connection", "1_Connection.pdf", "Number of Consumers", "March 2026", "count",
         "Karnal", "Domestic", 404304.0, "karnal", "domestic"),
        ("connection", "1_Connection.pdf", "Number of Consumers", "March 2026", "count",
         "Panchkula", "Total", 195820.0, "panchkula", "total"),
        ("connection", "1_Connection.pdf", "Number of Consumers", "March 2026", "count",
         "Grand Total", "Total", 3892250.0, "grand total", "total"),
    ]
    con.executemany("INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    con.execute("""
        CREATE TABLE datasets(
            dataset TEXT PRIMARY KEY, n_facts INT, n_entities INT,
            pct_numeric_entity REAL, has_total INT, trusted INT, title TEXT
        )""")
    con.execute("INSERT INTO datasets VALUES (?,?,?,?,?,?,?)",
                ("connection", len(rows), 3, 0.0, 1, 1, "Number of Consumers"))
    con.commit()
    con.close()
    return db_path


def _text_vector(text: str) -> list[float]:
    """Deterministic pseudo-embedding: a hash of the text, not a real model
    call. Same text -> same vector, different text -> different vector, which
    is all cosine-similarity ranking tests need."""
    h = hashlib.sha256(text.encode()).digest()
    return [b / 255 for b in h[:8]]


@pytest.fixture
def mock_openai_embeddings(monkeypatch):
    """Replaces app.rag.client.embeddings.create with a deterministic,
    network-free fake. `app.chat` imports `client` from `app.rag` by
    reference, so patching the shared instance covers both modules."""

    class _Datum:
        def __init__(self, embedding):
            self.embedding = embedding

    class _Resp:
        def __init__(self, data):
            self.data = data

    def _fake_create(*, model, input):
        texts = input if isinstance(input, list) else [input]
        return _Resp([_Datum(_text_vector(t)) for t in texts])

    monkeypatch.setattr(rag.client.embeddings, "create", _fake_create)


@pytest.fixture
def mock_openai_chat(monkeypatch):
    """Replaces app.rag.client.chat.completions.create with a deterministic
    fake, for both streaming (`app.chat`) and non-streaming/JSON-mode
    (`app.intent`) call sites. Configure via the returned dict:
        holder["reply"]  -> full text for a non-streaming call
        holder["tokens"] -> list of chunks to stream (defaults to holder["reply"]
                             split into single characters)
    """
    holder = {"reply": "Mocked assistant reply.", "tokens": None}

    class _Delta:
        def __init__(self, content):
            self.content = content

    class _Choice:
        def __init__(self, content):
            self.delta = _Delta(content)
            self.message = type("M", (), {"content": content})()

    class _Chunk:
        def __init__(self, content):
            self.choices = [_Choice(content)] if content is not None else []

    class _Resp:
        def __init__(self, content):
            self.choices = [_Choice(content)]

    def _fake_create(*, model, messages, temperature=0, stream=False, **kw):
        if stream:
            tokens = holder["tokens"] if holder["tokens"] is not None else list(holder["reply"])
            return iter([_Chunk(t) for t in tokens] + [_Chunk(None)])
        return _Resp(holder["reply"])

    monkeypatch.setattr(rag.client.chat.completions, "create", _fake_create)
    return holder
