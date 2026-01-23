# helper/llm.py
import os
from typing import Optional

import requests

from .ollama_utils import resolve_ollama_url


def resolve_model(requested_model: Optional[str] = None) -> str:
    """
    Resolve model with priority:
      1) OVERRIDE_LLM_MODEL (global override)
      2) requested_model (from specific tool env var)
      3) fallback "llama3.1:8b"
    """
    # 1. Global Override
    override = os.getenv("OVERRIDE_LLM_MODEL")
    if override and override.strip():
        return override.strip()

    # 2. Requested Model (e.g. tool specific)
    if requested_model and requested_model.strip():
        return requested_model.strip()

    # 3. Fallback
    return "llama3.1:8b"


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
    model_name = resolve_model(model)

    options: dict = {"num_ctx": num_ctx}
    if temperature is not None:
        options["temperature"] = temperature
    if top_p is not None:
        options["top_p"] = top_p

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "options": options,
        "stream": False,
    }

    resp = requests.post(
        f"{base_url}/api/chat",
        json=payload,
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["message"]["content"]


