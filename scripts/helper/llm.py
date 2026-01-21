# helper/llm.py
import os
from typing import Optional

import requests

from .ollama_utils import resolve_ollama_url


def get_default_model() -> str:
    """
    Resolve the model name for local tools.

    Priority:
      1) AI_COMMIT_MODEL
      2) INVESTIGATE_MODEL
      3) fallback "llama3.1:8b"
    """
    return os.getenv("AI_COMMIT_MODEL", os.getenv("INVESTIGATE_MODEL", "llama3.1:8b"))


def ollama_chat(
    system_prompt: str,
    user_prompt: str,
    *,
    num_ctx: int = 4096,
    timeout: int = 60,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
) -> str:
    """
    Core Ollama chat helper for local tools.

    Args:
        system_prompt: System context/instructions
        user_prompt: User query
        num_ctx: Context window size
        timeout: Request timeout in seconds
        model: Model name (uses default if not provided)
        temperature: Sampling temperature (0.0-1.0, lower = more deterministic)
        top_p: Nucleus sampling parameter (0.0-1.0)

    Returns:
      raw content string from the model (no extra cleanup).
    """
    base_url = resolve_ollama_url("http://localhost:11434")
    model_name = model or get_default_model()

    payload = {
        "model": model_name,
        "num_ctx": num_ctx,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
    }

    # Add optional sampling parameters if provided
    if temperature is not None:
        payload["temperature"] = temperature
    if top_p is not None:
        payload["top_p"] = top_p

    resp = requests.post(
        f"{base_url}/api/chat",
        json=payload,
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["message"]["content"]


def strip_fences_and_quotes(text: str) -> str:
    """
    Remove common wrapping artifacts:
      - ``` blocks
      - single leading/trailing quotes or backticks
    """
    out = text.strip()

    if "```" in out:
        parts = out.split("```")
        if len(parts) >= 3:
            out = parts[1].strip() if parts[0].strip() == "" else parts[1].strip()

    if out.startswith(("`", '"', "'")) and out.endswith(("`", '"', "'")):
        out = out[1:-1].strip()

    return out
