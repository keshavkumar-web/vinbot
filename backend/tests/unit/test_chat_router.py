"""Unit tests for app/chat.py — the router in `stream_answer()`.

Each test isolates ONE branch of the routing precedence documented in
chat.py's own docstring (pending clarification -> glossary batch/category ->
single-term glossary -> meta-question -> comparison -> domain-switch ->
transformer-rate -> prose-continuation -> superlative -> slot follow-up ->
structured table lookup -> glossary fallback -> RAG), by monkeypatching the
collaborator modules chat.py imports (`app.glossary`, `app.followup`,
`app.tables`). The collaborators' OWN internal correctness is covered by
test_glossary.py / test_followup.py / test_tables.py — this file verifies
chat.py picks the RIGHT one and stops (never falls through past a match).

REQ-ROUTER-01..08 — see docs/testing/REQUIREMENT_TRACEABILITY_MATRIX.md.
"""
import pytest

from app import chat, followup, glossary, tables

pytestmark = pytest.mark.unit


def _collect(gen):
    return "".join(gen)


def test_glossary_batch_short_circuits_before_rag(monkeypatch):
    monkeypatch.setattr(glossary, "define_multi", lambda q: "SDO — Sub Divisional Officer.")

    def _fail_rag(*a, **kw):
        raise AssertionError("RAG must not run when the glossary batch matched")
    monkeypatch.setattr(chat, "_stream_rag_answer", _fail_rag)

    result = _collect(chat.stream_answer([], "What is SDO?\nWhat is XEN?"))
    assert result == "SDO — Sub Divisional Officer."


def test_glossary_category_list_short_circuits(monkeypatch):
    monkeypatch.setattr(glossary, "define_multi", lambda q: None)
    monkeypatch.setattr(glossary, "list_category", lambda q: "Administrative:\n• SDO — ...")

    result = _collect(chat.stream_answer([], "show administrative abbreviations"))
    assert result.startswith("Administrative:")


def test_structured_table_answer_short_circuits_before_rag(monkeypatch):
    monkeypatch.setattr(glossary, "define_multi", lambda q: None)
    monkeypatch.setattr(glossary, "list_category", lambda q: None)
    monkeypatch.setattr(tables, "respond",
                         lambda q, *a, **kw: {"status": "answer",
                                               "text": "Karnal — Total: 543,445"})

    def _fail_rag(*a, **kw):
        raise AssertionError("RAG must not run when the structured path answered")
    monkeypatch.setattr(chat, "_stream_rag_answer", _fail_rag)

    result = _collect(chat.stream_answer([], "how many connections in Karnal?"))
    assert result == "Karnal — Total: 543,445"


def test_structured_clarify_is_returned_without_rag(monkeypatch):
    monkeypatch.setattr(glossary, "define_multi", lambda q: None)
    monkeypatch.setattr(glossary, "list_category", lambda q: None)
    monkeypatch.setattr(glossary, "define", lambda q: None)
    monkeypatch.setattr(tables, "respond",
                         lambda q, *a, **kw: {"status": "clarify",
                                               "text": "Please name the circle."})

    result = _collect(chat.stream_answer([], "how many connections?"))
    assert result == "Please name the circle."


def test_comparison_question_answered_deterministically(monkeypatch):
    monkeypatch.setattr(followup, "is_comparison_question", lambda q: True)
    monkeypatch.setattr(followup, "compare_answer",
                         lambda history, q: "Karnal (543,445) has a higher Total than Panchkula (195,820).")

    def _fail_rag(*a, **kw):
        raise AssertionError("RAG must not run when the comparison was resolved deterministically")
    monkeypatch.setattr(chat, "_stream_rag_answer", _fail_rag)

    history = [{"role": "assistant", "content": "Karnal — Total: 543,445\n(Source: x, Row: Karnal, Column: Total)"}]
    result = _collect(chat.stream_answer(history, "which is higher?"))
    assert "Karnal" in result and "higher" in result


def test_meta_question_answered_from_history_without_rag(monkeypatch):
    monkeypatch.setattr(glossary, "define_multi", lambda q: None)
    monkeypatch.setattr(glossary, "list_category", lambda q: None)
    monkeypatch.setattr(followup, "is_meta_question", lambda q: True)
    monkeypatch.setattr(followup, "is_comparison_question", lambda q: False)
    monkeypatch.setattr(chat, "_stream_meta_answer", lambda history, q: iter(["That was the Karnal total."]))

    def _fail_rag(*a, **kw):
        raise AssertionError("RAG must not run for a meta-question")
    monkeypatch.setattr(chat, "_stream_rag_answer", _fail_rag)

    history = [{"role": "assistant", "content": "Karnal — Total: 543,445"}]
    result = _collect(chat.stream_answer(history, "where did that number come from?"))
    assert result == "That was the Karnal total."


def test_pending_transformer_clarification_resolved_first(monkeypatch):
    monkeypatch.setattr(followup, "pending_transformer_reply",
                         lambda history, q: "Kurukshetra Rural — Transformers damaged Total: 3,602")

    result = _collect(chat.stream_answer(
        [{"role": "assistant", "content": "This looks like a transformer question..."}],
        "damage rate"))
    assert "3,602" in result


def test_falls_through_to_rag_when_nothing_else_matches(mock_openai_embeddings, mock_openai_chat,
                                                          load_sample_kb, monkeypatch):
    """No glossary/table/follow-up branch matches an out-of-scope prose
    question -> falls all the way through to the RAG-grounded reply."""
    monkeypatch.setattr(glossary, "define_multi", lambda q: None)
    monkeypatch.setattr(glossary, "list_category", lambda q: None)
    monkeypatch.setattr(glossary, "define", lambda q: None)
    mock_openai_chat["reply"] = "Grounded RAG answer."

    result = _collect(chat.stream_answer([], "What is the late payment surcharge?"))
    assert result == "Grounded RAG answer."
