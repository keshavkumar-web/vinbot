"""Unit tests for app/tables.py — the structured (numeric) retrieval engine.

`respond()` tests use its own documented, injectable `extractor` parameter
(see the module docstring: "extractor is injectable for offline testing") —
the same seam `eval_tables.py` already relies on — so no real OpenAI call is
needed and no application code changes were required.

REQ-TABLES-01..06 — see docs/testing/REQUIREMENT_TRACEABILITY_MATRIX.md.
"""
import pytest

from app import tables

pytestmark = pytest.mark.unit


# --- parse_number ------------------------------------------------------------
@pytest.mark.parametrize("cell,expected_value,expected_lead", [
    ("3,003,464", 3003464.0, None),
    ("5.23", 5.23, None),
    ("r 330656", 330656.0, "r"),      # leaked circle-name letter (see docstring)
    (None, None, None),
    ("", None, None),
    ("no numbers here", None, None),
])
def test_parse_number(cell, expected_value, expected_lead):
    value, lead = tables.parse_number(cell)
    assert value == expected_value
    assert lead == expected_lead


# --- build_columns (merged/multi-row header reconstruction) ------------------
def test_build_columns_reconstructs_split_header():
    rows = [
        ["Circle", "Transformers damaged", None],
        ["", "Total", "Rural"],
        ["Ambala", "10", "5"],
    ]
    columns, first_data = tables.build_columns(rows, entity_cols=1)
    assert columns == ["Circle", "Transformers damaged Total", "Transformers damaged Rural"]
    assert first_data == 2


# --- snap_metric ---------------------------------------------------------------
def test_snap_metric_exact_hint_match():
    cols = ["Total", "Domestic", "HT Industry"]
    assert tables.snap_metric(cols, "Total", "irrelevant") == ["Total"]


def test_snap_metric_matches_explicit_column_named_in_query():
    cols = ["Total", "Domestic", "HT Industry"]
    assert tables.snap_metric(cols, None, "how many domestic connections") == ["Domestic"]


def test_snap_metric_falls_back_to_aggregate_for_bare_quantity():
    cols = ["Total", "Domestic", "HT Industry"]
    assert tables.snap_metric(cols, None, "how many connections") == ["Total"]


# --- find_entity (safety: never substitute an unknown place) ------------------
def test_find_entity_matches_named_district(temp_tables_db):
    con = tables._connect(str(temp_tables_db))
    try:
        assert tables.find_entity(con, "connection", "connections in Karnal") == ["Karnal"]
    finally:
        con.close()


def test_find_entity_defaults_to_grand_total_when_no_place_named(temp_tables_db):
    con = tables._connect(str(temp_tables_db))
    try:
        assert tables.find_entity(con, "connection", "how many connections") == ["Grand Total"]
    finally:
        con.close()


def test_find_entity_refuses_unknown_place(temp_tables_db):
    con = tables._connect(str(temp_tables_db))
    try:
        assert tables.find_entity(con, "connection", "connections in Atlantis") == []
    finally:
        con.close()


# --- respond() end-to-end via the injectable extractor -------------------------
def test_respond_returns_exact_value_with_provenance(temp_tables_db):
    intent = {"status": "answer", "confidence": 0.95, "selections": [
        {"dataset": "connection", "metric": "Total", "entity": "Karnal", "period": None}]}

    result = tables.respond("how many connections in Karnal", str(temp_tables_db),
                             extractor=lambda q, s: intent)

    assert result["status"] == "answer"
    assert "543,445" in result["text"]
    assert "(Source: 1_Connection.pdf, Row: Karnal, Column: Total)" in result["text"]


def test_respond_low_confidence_returns_clarify(temp_tables_db):
    intent = {"status": "answer", "confidence": 0.2, "selections": [
        {"dataset": "connection", "metric": "Total", "entity": "Karnal", "period": None}]}

    result = tables.respond("connections", str(temp_tables_db), extractor=lambda q, s: intent)

    assert result["status"] == "clarify"


def test_respond_unknown_place_returns_clarify_not_wrong_value(temp_tables_db):
    """Safety: a place we don't have must never silently fall back to the
    Grand Total (the customer-reported 'wrong values from tables' bug)."""
    intent = {"status": "answer", "confidence": 0.9, "selections": [
        {"dataset": "connection", "metric": "Total", "entity": "Atlantis", "period": None}]}

    result = tables.respond("connections in Atlantis", str(temp_tables_db),
                             extractor=lambda q, s: intent)

    assert result["status"] == "clarify"
    assert "3,892,250" not in result.get("text", "")  # never the wrong Grand Total


def test_respond_procedural_question_routes_to_prose_without_calling_extractor(temp_tables_db):
    def _fail_if_called(q, s):
        raise AssertionError("extractor must not be called for a procedural question")

    result = tables.respond("What documents are required for a new connection",
                             str(temp_tables_db), extractor=_fail_if_called)

    assert result == {"status": "prose"}


def test_respond_database_unavailable_falls_back_to_prose(tmp_path):
    """Edge case explicitly required by Phase 3: database unavailable."""
    missing_db = tmp_path / "does_not_exist.db"
    result = tables.respond("how many connections in Karnal", str(missing_db))
    assert result == {"status": "prose"}
