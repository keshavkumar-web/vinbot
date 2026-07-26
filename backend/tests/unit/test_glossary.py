"""Unit tests for app/glossary.py.

glossary.py caches its parsed index in module-level globals (`_index`,
`_category_index`) built once from whatever `rag.get_knowledge_db()` returns
the first time it's called. An autouse fixture resets those globals before
every test in this module so each test builds the index fresh from its own
`load_sample_kb` fixture data, rather than reusing another test's cache.

REQ-GLOSS-01..04 — see docs/testing/REQUIREMENT_TRACEABILITY_MATRIX.md.
"""
import pytest

from app import glossary

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_glossary_cache():
    glossary._index = None
    glossary._category_index = None
    yield
    glossary._index = None
    glossary._category_index = None


def test_define_with_full_question_phrasing(load_sample_kb):
    result = glossary.define("what is SDO?")
    assert result == "SDO — Sub Divisional Officer. Officer in charge of a sub-division."


def test_define_dash_style_entry(load_sample_kb):
    result = glossary.define("what is AT&C Loss?")
    assert result is not None
    assert result.startswith("AT&C Loss — Aggregate Technical & Commercial loss")


def test_define_unknown_term_returns_none(load_sample_kb):
    assert glossary.define("what is ZZZQQQ?") is None


def test_define_bare_short_abbreviation_is_not_hijacked(load_sample_kb):
    """A bare 2-3 letter term ('SDO') without question phrasing must NOT
    resolve — this guards against a short numeric follow-up ('SDO', 'HT')
    being misread as a definition request (see glossary.py's `allow` guard)."""
    assert glossary.define("SDO") is None


def test_list_category_returns_matching_entries(load_sample_kb):
    result = glossary.list_category("show administrative abbreviations")
    assert result is not None
    assert result.startswith("Administrative:")
    assert "SDO — Sub Divisional Officer" in result


def test_list_category_no_match_returns_none(load_sample_kb):
    assert glossary.list_category("show plumbing abbreviations") is None


def test_define_multi_batch_of_known_terms(load_sample_kb):
    result = glossary.define_multi("What is SDO?\nWhat is AT&C Loss?")
    assert result is not None
    assert "Sub Divisional Officer" in result
    assert "Aggregate Technical" in result


def test_define_multi_mixed_batch_with_unknown_term_returns_none(load_sample_kb):
    """Only fires when EVERY segment is a known term (see glossary.py
    docstring) — a mixed batch must defer to the normal/RAG path."""
    result = glossary.define_multi("What is SDO?\nHow does electricity work?")
    assert result is None


def test_define_empty_knowledge_base_returns_none():
    """Edge case: no glossary source files loaded at all."""
    assert glossary.define("what is SDO?") is None
