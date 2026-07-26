"""Unit tests for app/followup.py — the conversational-context layer.

Covers the pure regex/text-classification functions directly (no mocks
needed), and `resolve_followup()` against a real temp SQLite fact store via
`monkeypatch.setattr(tables, "DB_PATH", ...)` — the same override seam
`app/tables.py` already documents.

REQ-FOLLOWUP-01..05 — see docs/testing/REQUIREMENT_TRACEABILITY_MATRIX.md.
"""
import pytest

from app import followup, tables

pytestmark = pytest.mark.unit


# --- is_self_contained ------------------------------------------------------
@pytest.mark.parametrize("message,expected", [
    ("How many connections in Karnal?", True),
    ("Domestic", False),                       # bare elliptical reply
    ("and for Jhajjar?", False),                # follow-up connector
    ("how many of those?", False),              # back-reference
    ("What is the procedure for a new connection?", True),
])
def test_is_self_contained(message, expected):
    assert followup.is_self_contained(message) is expected


# --- is_meta_question / is_comparison_question -----------------------------
def test_is_meta_question_true_for_self_reference():
    assert followup.is_meta_question("You said 543,445 earlier, where did that come from?")


def test_is_meta_question_false_for_ordinary_followup():
    assert not followup.is_meta_question("and for Jhajjar?")


def test_is_comparison_question_true_for_which_is_higher():
    assert followup.is_comparison_question("which is higher between Karnal and Panchkula?")


def test_is_comparison_question_true_for_difference():
    assert followup.is_comparison_question("what is the difference?")


def test_is_comparison_question_false_for_ordinary_question():
    assert not followup.is_comparison_question("how many connections in Karnal?")


# --- compare_facts (deterministic, no LLM) ---------------------------------
def test_compare_facts_higher_lower():
    facts = [
        {"entity": "Karnal", "metric": "Total", "unit": "count", "value": 543445.0,
         "num": "543,445", "source": "1_Connection.pdf"},
        {"entity": "Panchkula", "metric": "Total", "unit": "count", "value": 195820.0,
         "num": "195,820", "source": "1_Connection.pdf"},
    ]
    result = followup.compare_facts(facts, "which is higher?")
    assert "Karnal (543,445) has a higher Total than Panchkula (195,820)." == result


def test_compare_facts_difference():
    facts = [
        {"entity": "Karnal", "metric": "Total", "unit": "count", "value": 543445.0,
         "num": "543,445", "source": "1_Connection.pdf"},
        {"entity": "Panchkula", "metric": "Total", "unit": "count", "value": 195820.0,
         "num": "195,820", "source": "1_Connection.pdf"},
    ]
    result = followup.compare_facts(facts, "what is the difference?")
    assert "347,625" in result


def test_compare_facts_returns_none_with_fewer_than_two_values():
    facts = [{"entity": "Karnal", "metric": "Total", "unit": "count", "value": 543445.0,
              "num": "543,445", "source": "1_Connection.pdf"}]
    assert followup.compare_facts(facts, "which is higher?") is None


# --- resolve_followup (real temp SQLite) -----------------------------------
def test_resolve_followup_carries_over_entity_when_metric_named(monkeypatch, temp_tables_db):
    monkeypatch.setattr(tables, "DB_PATH", str(temp_tables_db))
    history = [
        {"role": "user", "content": "connections in Karnal"},
        {"role": "assistant", "content": (
            "Karnal — Total: 543,445 (as of March 2026)\n"
            "(Source: 1_Connection.pdf, Row: Karnal, Column: Total)"
        )},
    ]

    plan = followup.resolve_followup(history, "Domestic?")

    assert plan is not None
    assert plan["query"] == "Domestic?"
    assert plan["intent"]["selections"] == [
        {"dataset": "connection", "metric": "Domestic", "entity": "Karnal", "period": None}
    ]


def test_resolve_followup_returns_none_when_nothing_to_resolve(monkeypatch, temp_tables_db):
    monkeypatch.setattr(tables, "DB_PATH", str(temp_tables_db))
    history = [
        {"role": "user", "content": "connections in Karnal"},
        {"role": "assistant", "content": (
            "Karnal — Total: 543,445 (as of March 2026)\n"
            "(Source: 1_Connection.pdf, Row: Karnal, Column: Total)"
        )},
    ]
    # A message naming neither an entity, metric, nor dataset switch.
    assert followup.resolve_followup(history, "okay thanks") is None


def test_resolve_followup_returns_none_without_db(monkeypatch, tmp_path):
    """Edge case: database unavailable — must defer (None), never raise."""
    monkeypatch.setattr(tables, "DB_PATH", str(tmp_path / "no_such.db"))
    history = [{"role": "assistant", "content": "some prior answer"}]
    assert followup.resolve_followup(history, "Domestic?") is None
