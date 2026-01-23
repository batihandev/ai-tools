# scripts/helper/json_utils.py
import json
import re
from typing import Any, Callable, Optional, TypeVar

T = TypeVar("T")

_JSON_FENCE_RE = re.compile(
    r"^\s*```(?:json)?\s*\n(.*?)\n\s*```\s*$",
    re.DOTALL | re.IGNORECASE,
)

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def strip_json_fence(s: str) -> str:
    """Remove markdown code fences from JSON content."""
    m = _JSON_FENCE_RE.match(s)
    if not m:
        return s.strip()
    return m.group(1).strip()


def extract_json_object(text: str) -> str:
    """
    Extract the first JSON object {...} from text.
    
    Handles:
    - Markdown code fences (```json ... ```)
    - Extra preamble/postamble text from LLM
    - Returns original text if no JSON object found
    """
    cleaned = strip_json_fence(text).strip()
    
    match = _JSON_OBJECT_RE.search(cleaned)
    if match:
        return match.group(0)
    
    return cleaned


def try_parse_json(maybe: Any) -> tuple[Optional[Any], Optional[str]]:
    """
    Attempts to parse 'maybe' as JSON.
    Returns (parsed_object, original_raw_string).
    If parsing fails, parsed_object is None.
    """
    if isinstance(maybe, (dict, list, int, float, bool)) or maybe is None:
        return maybe, None

    if not isinstance(maybe, str):
        return None, str(maybe)

    raw = maybe
    s = strip_json_fence(raw)

    try:
        parsed = json.loads(s)
    except Exception:
        return None, raw

    # Double-decoding check (if the JSON string itself contains a JSON string)
    if isinstance(parsed, str):
        s2 = strip_json_fence(parsed).strip()
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
        Parsed model instance, or fallback if parsing fails
        
    Example:
        result = safe_parse_model(
            raw=llm_output,
            model_cls=MyModel,
            fallback_factory=lambda r: MyModel(error=True, raw_output=r)
        )
    """
    json_str = extract_json_object(raw)
    
    try:
        data = json.loads(json_str)
        if not isinstance(data, dict):
            return fallback_factory(raw)
        return model_cls(**data)
    except Exception:
        return fallback_factory(raw)

