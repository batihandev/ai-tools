# tests/unit/helper/test_json_utils.py
"""Unit tests for json_utils.py."""

from pydantic import BaseModel
from scripts.helper.json_utils import extract_json_object, safe_parse_model, strip_json_fence


class MyModel(BaseModel):
    name: str
    value: int


class TestExtractJsonObject:
    def test_strip_fence(self):
        assert strip_json_fence("```json\n{}\n```") == "{}"
        assert strip_json_fence("no fence") == "no fence"

    def test_extract_json(self):
        raw = "Here is the JSON:\n```json\n{\"name\": \"test\"}\n```\nHope it helps."
        assert extract_json_object(raw) == '{"name": "test"}'

    def test_returns_cleaned_if_no_match(self):
        raw = "Just text"
        assert extract_json_object(raw) == "Just text"


class TestSafeParseModel:
    def test_valid_parsing(self):
        raw = '{"name": "test", "value": 123}'
        result = safe_parse_model(raw, MyModel, lambda r: MyModel(name="flbk", value=0))
        assert result.name == "test"
        assert result.value == 123

    def test_fallback_on_invalid_json(self):
        raw = "Not JSON"
        result = safe_parse_model(raw, MyModel, lambda r: MyModel(name="error", value=-1))
        assert result.name == "error"
        assert result.value == -1

    def test_fallback_on_validation_error(self):
        raw = '{"name": "test", "value": "not-int"}'
        result = safe_parse_model(raw, MyModel, lambda r: MyModel(name="schema-error", value=-2))
        assert result.name == "schema-error"
        assert result.value == -2
