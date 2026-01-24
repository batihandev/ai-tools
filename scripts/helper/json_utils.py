# scripts/helper/json_utils.py
import json
import re
from typing import Any, Callable, Optional, TypeVar

T = TypeVar("T")

# Non-greedy, newline-agnostic fence capture (first fenced block only)
_JSON_FENCE_RE = re.compile(
    r"```(?:json)?\s*(.*?)\s*```",
    re.DOTALL | re.IGNORECASE,
)


def strip_json_fence(s: str) -> str:
    """
    Remove markdown code fences from JSON content.
    Finds the *first* fenced block. If none, returns stripped input.
    """
    m = _JSON_FENCE_RE.search(s)
    if not m:
        return s.strip()
    return m.group(1).strip()


def extract_json_object(text: str) -> str:
    """
    Extract the first JSON object likely to be valid.

    Strategy:
    1) If a ```json ... ``` fence exists, return its content.
    2) Else, return substring from first '{' to last '}' (inclusive).
    3) Else, return stripped original text.
    """
    m = _JSON_FENCE_RE.search(text)
    if m:
        return m.group(1).strip()

    start = text.find("{")
    end = text.rfind("}")

    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]

    return text.strip()


def try_parse_json(maybe: Any) -> tuple[Optional[Any], Optional[str]]:
    """
    Attempts to parse 'maybe' as JSON.

    Returns (parsed_object, original_raw_string).
    - If parsing succeeds and input was a string: raw string is returned in 2nd slot.
    - If input wasn't a string and is already JSON-compatible: returns (maybe, None).
    - If parsing fails: returns (None, raw_string_representation).
    """
    if isinstance(maybe, (dict, list, int, float, bool)) or maybe is None:
        return maybe, None

    if not isinstance(maybe, str):
        return None, str(maybe)

    raw = maybe
    s = extract_json_object(raw)
    s = strip_json_fence(s)

    try:
        parsed = json.loads(s)
    except Exception:
        return None, raw

    # Double-decoding check (JSON string containing JSON)
    if isinstance(parsed, str):
        s2 = extract_json_object(parsed)
        s2 = strip_json_fence(s2).strip()
        if (s2.startswith("{") and s2.endswith("}")) or (s2.startswith("[") and s2.endswith("]")):
            try:
                parsed2 = json.loads(s2)
                return parsed2, raw
            except Exception:
                return parsed, raw

    return parsed, raw


def safe_parse_model(
    raw: str,
    model_cls: type[T],
    fallback_factory: Callable[[str], T],
) -> T:
    """
    Parse LLM output into a Pydantic model with graceful fallback.

    Args:
        raw: Raw LLM output string (may contain markdown fences, preamble, etc.)
        model_cls: Pydantic model class to parse into
        fallback_factory: Callable that takes the raw string and returns a fallback model instance

    Returns:
        Parsed model instance, or fallback if parsing fails.
    """
    json_str = extract_json_object(raw)

    try:
        data = json.loads(json_str)
        if not isinstance(data, dict):
            return fallback_factory(raw)
        return model_cls(**data)
    except Exception:
        return fallback_factory(raw)
