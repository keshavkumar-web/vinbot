"""Unit tests for app/intent.py (the LLM intent-selection layer).

Contract under test (per intent.py's own docstring): the model NEVER returns
a value, only identifiers; `normalise()` must fail CLOSED (degrade to
"clarify") on anything malformed, never to a fabricated "answer".

REQ-INTENT-01..03 — see docs/testing/REQUIREMENT_TRACEABILITY_MATRIX.md.
"""
import json

import pytest

from app import intent

pytestmark = pytest.mark.unit


# --- normalise() ---------------------------------------------------------
def test_normalise_none_input_degrades_to_clarify():
    result = intent.normalise(None)
    assert result == {
        "status": "clarify", "confidence": 0.0, "selections": [], "clarify_reason": None,
    }


def test_normalise_valid_answer_passthrough():
    raw = {"status": "answer", "confidence": 0.95, "selections": [
        {"dataset": "connection", "metric": "Total", "entity": "Karnal", "period": None}]}
    result = intent.normalise(raw)
    assert result["status"] == "answer"
    assert result["confidence"] == 0.95
    assert result["selections"] == [
        {"dataset": "connection", "metric": "Total", "entity": "Karnal", "period": None}]


def test_normalise_invalid_status_degrades_to_clarify():
    raw = {"status": "definitely-not-a-real-status", "confidence": 0.9, "selections": []}
    assert intent.normalise(raw)["status"] == "clarify"


def test_normalise_non_numeric_confidence_defaults_to_zero():
    raw = {"status": "answer", "confidence": "not-a-number", "selections": []}
    assert intent.normalise(raw)["confidence"] == 0.0


def test_normalise_string_confidence_is_coerced_to_float():
    raw = {"status": "answer", "confidence": "0.75", "selections": []}
    assert intent.normalise(raw)["confidence"] == 0.75


def test_normalise_drops_selections_missing_dataset():
    raw = {"status": "answer", "confidence": 0.9, "selections": [
        {"metric": "Total", "entity": "Karnal"},           # no "dataset" -> dropped
        {"dataset": "connection", "metric": "Total"},       # valid
    ]}
    result = intent.normalise(raw)
    assert len(result["selections"]) == 1
    assert result["selections"][0]["dataset"] == "connection"


def test_normalise_ignores_non_dict_selection_entries():
    raw = {"status": "answer", "confidence": 0.9, "selections": ["not-a-dict", 42]}
    assert intent.normalise(raw)["selections"] == []


# --- render_catalog() -----------------------------------------------------
def test_render_catalog_limits_entities_shown():
    schema = {"connection": {"title": "Number of Consumers",
                              "metrics": ["Total", "Domestic"],
                              "entities": [f"District {i}" for i in range(50)]}}
    catalog = json.loads(intent.render_catalog(schema, max_entities=5))
    assert len(catalog["connection"]["entities"]) == 5
    assert catalog["connection"]["metrics"] == ["Total", "Domestic"]


# --- extract() with a fake client -----------------------------------------
class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, content):
        self._content = content
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return _FakeResponse(self._content)


class _FakeChat:
    def __init__(self, content):
        self.completions = _FakeCompletions(content)


class _FakeClient:
    def __init__(self, content):
        self.chat = _FakeChat(content)


def test_extract_parses_valid_json_response():
    content = json.dumps({"status": "answer", "confidence": 0.9, "selections": [
        {"dataset": "connection", "metric": "Total", "entity": None, "period": None}]})
    fake = _FakeClient(content)
    schema = {"connection": {"title": "x", "metrics": ["Total"], "entities": []}}

    result = intent.extract(fake, "gpt-4o-mini", "how many connections", schema)

    assert result["status"] == "answer"
    assert result["selections"][0]["dataset"] == "connection"
    assert fake.chat.completions.last_kwargs["response_format"] == {"type": "json_object"}
    assert fake.chat.completions.last_kwargs["temperature"] == 0.0


def test_extract_malformed_json_degrades_to_clarify():
    fake = _FakeClient("this is not valid json {{{")
    schema = {"connection": {"title": "x", "metrics": ["Total"], "entities": []}}

    result = intent.extract(fake, "gpt-4o-mini", "how many connections", schema)

    assert result["status"] == "clarify"


def test_extract_empty_content_degrades_to_clarify():
    fake = _FakeClient(None)
    schema = {"connection": {"title": "x", "metrics": ["Total"], "entities": []}}

    result = intent.extract(fake, "gpt-4o-mini", "how many connections", schema)

    assert result["status"] == "clarify"


def test_default_extractor_uses_shared_rag_client(mock_openai_chat):
    mock_openai_chat["reply"] = json.dumps({
        "status": "prose", "confidence": 0.9, "selections": [],
    })
    schema = {"connection": {"title": "x", "metrics": ["Total"], "entities": []}}

    result = intent.default_extractor("what is the procedure for a new connection", schema)

    assert result["status"] == "prose"
