"""Unit tests for app/rag.py — the vector/prose retrieval layer.

Embedding-ranking tests build each chunk's stored "embedding" by calling the
MOCKED `rag.create_embedding()` on that chunk's own text (see
`mock_openai_embeddings` in conftest.py), so a query using the same or a
near-identical text deterministically ranks first — this exercises the real
cosine-similarity/ranking code in rag.py without a live OpenAI call or a
dependency on real semantic embeddings.

REQ-RAG-01..06 — see docs/testing/REQUIREMENT_TRACEABILITY_MATRIX.md.
"""
import pytest

from app import config, rag

pytestmark = pytest.mark.unit


# --- cosine_similarity ------------------------------------------------------
def test_cosine_similarity_identical_vectors():
    assert rag.cosine_similarity([1, 0, 0], [1, 0, 0]) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors():
    assert rag.cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)


def test_cosine_similarity_zero_vector_is_safe():
    assert rag.cosine_similarity([0, 0], [1, 1]) == 0.0


# --- split_questions ---------------------------------------------------------
def test_split_questions_multi_part_turn():
    text = "What documents are required for a new connection?\nWhat is the security deposit?"
    result = rag.split_questions(text)
    assert len(result) == 2
    assert "documents" in result[0].lower()
    assert "deposit" in result[1].lower()


def test_split_questions_single_question_stays_whole():
    result = rag.split_questions("What is the security deposit for domestic supply?")
    assert len(result) == 1


# --- expand_query ------------------------------------------------------------
def test_expand_query_expands_known_abbreviation():
    expanded = rag.expand_query("what is sdo?")
    assert "Sub Divisional Officer" in expanded


def test_expand_query_expands_consumer_phrase_synonym():
    expanded = rag.expand_query("how much security deposit will I pay?")
    assert "Advance Consumption Deposit" in expanded


def test_expand_query_leaves_unmatched_query_unchanged():
    query = "what is the collection efficiency"
    assert rag.expand_query(query) == query


# --- find_id_chunks / find_rts_chunks ----------------------------------------
def test_find_id_chunks_matches_circular_id():
    db = [
        {"source": "SC_U_01_2026.txt", "text": "As per Circular U-01/2026, the deposit is Rs.750."},
        {"source": "SC_U_02_2026.txt", "text": "Unrelated circular text."},
    ]
    hits = rag.find_id_chunks("what does circular U-01/2026 say?", db)
    assert len(hits) == 1
    assert hits[0][1]["source"] == "SC_U_01_2026.txt"
    assert hits[0][0] == 1.0


def test_find_id_chunks_no_id_in_query_returns_empty():
    db = [{"source": "SC_U_01_2026.txt", "text": "As per Circular U-01/2026..."}]
    assert rag.find_id_chunks("what is the deposit amount?", db) == []


def test_find_rts_chunks_matches_named_service():
    db = [
        {"source": "RTS_Act.pdf", "text": "Shifting of meter: Designated Officer is the JE. Time limit: 7 days."},
        {"source": "RTS_Act.pdf", "text": "New connection: Designated Officer is the SDO. Time limit: 15 days."},
    ]
    hits = rag.find_rts_chunks("who is the designated officer for shifting of meter?", db)
    assert len(hits) == 1
    assert "Shifting of meter" in hits[0][1]["text"]


def test_find_rts_chunks_no_service_named_returns_empty():
    db = [{"source": "RTS_Act.pdf", "text": "Shifting of meter: Designated Officer is the JE."}]
    assert rag.find_rts_chunks("who is the designated officer?", db) == []


# --- format_context -----------------------------------------------------------
def test_format_context_renders_source_and_text():
    scored = [(0.9, {"source": "a.txt", "text": "chunk one"}),
              (0.8, {"source": "b.txt", "text": "chunk two"})]
    rendered = rag.format_context(scored)
    assert "[Source: a.txt]\nchunk one" in rendered
    assert "[Source: b.txt]\nchunk two" in rendered


# --- retrieval ranking (deterministic, mocked embeddings) ----------------------
def test_retrieve_context_ranks_matching_chunk_first(mock_openai_embeddings, monkeypatch):
    texts = [
        "Domestic connection deposit is Rs.750 per KW as per the sales circular.",
        "The collection efficiency measures billing recovery across circles.",
    ]
    db = [{"source": f"doc{i}.txt", "text": t, "embedding": rag.create_embedding(t)}
          for i, t in enumerate(texts)]
    monkeypatch.setattr(rag, "_knowledge_db", db)
    monkeypatch.setattr(rag, "_emb_matrix", None)
    monkeypatch.setattr(rag, "_emb_norms", None)
    monkeypatch.setattr(config, "MIN_SIMILARITY", 0.0)

    scored = rag.retrieve_context(texts[0])

    assert scored[0][1]["text"] == texts[0]


def test_retrieve_context_empty_knowledge_base_returns_empty_list():
    """Edge case explicitly required by Phase 3: empty knowledge base."""
    rag.load_knowledge(str(rag.config.KNOWLEDGE_DB_PATH))  # the conftest empty fixture
    assert rag.retrieve_context("any question") == []


def test_retrieve_context_multi_falls_back_for_single_question(mock_openai_embeddings, monkeypatch):
    text = "What is the security deposit for domestic supply?"
    db = [{"source": "a.txt", "text": text, "embedding": rag.create_embedding(text)}]
    monkeypatch.setattr(rag, "_knowledge_db", db)
    monkeypatch.setattr(rag, "_emb_matrix", None)
    monkeypatch.setattr(rag, "_emb_norms", None)
    monkeypatch.setattr(config, "MIN_SIMILARITY", 0.0)

    scored = rag.retrieve_context_multi(text)

    assert len(scored) == 1
    assert scored[0][1]["text"] == text


def test_retrieve_context_multi_covers_every_sub_question(mock_openai_embeddings, monkeypatch):
    part_a = "What documents are required for a new connection?"
    part_b = "What is the security deposit for domestic supply?"
    db = [
        {"source": "docs.txt", "text": part_a, "embedding": rag.create_embedding(part_a)},
        {"source": "deposit.txt", "text": part_b, "embedding": rag.create_embedding(part_b)},
    ]
    monkeypatch.setattr(rag, "_knowledge_db", db)
    monkeypatch.setattr(rag, "_emb_matrix", None)
    monkeypatch.setattr(rag, "_emb_norms", None)
    monkeypatch.setattr(config, "MIN_SIMILARITY", 0.0)

    scored = rag.retrieve_context_multi(f"{part_a}\n{part_b}")

    sources = {item["source"] for _, item in scored}
    assert sources == {"docs.txt", "deposit.txt"}
