# scripts/helper/json_utils.py
import json
import re
from typing import Any, Optional, Tuple

_JSON_FENCE_RE = re.compile(
    r"^\s*```(?:json)?\s*\n(.*?)\n\s*```\s*$",
    re.DOTALL | re.IGNORECASE,
)

def strip_json_fence(s: str) -> str:
    m = _JSON_FENCE_RE.match(s)
    if not m:
        return s.strip()
    return m.group(1).strip()

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
