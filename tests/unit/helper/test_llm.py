# tests/unit/helper/test_llm.py
"""Unit tests for llm.py options."""

import json
import pytest
from unittest.mock import patch, MagicMock
from scripts.helper.llm import ollama_chat


@patch("scripts.helper.llm.requests.post")
def test_ollama_chat_sends_options_correctly(mock_post):
    """Verify that num_ctx, temperature, and top_p are sent inside 'options'."""
    
    # Mock successful response
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"message": {"content": "ok"}}
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp

    ollama_chat(
        system_prompt="sys",
        user_prompt="user",
        num_ctx=2048,
        temperature=0.7,
        top_p=0.9,
    )

    # Check the call arguments
    assert mock_post.called
    kwargs = mock_post.call_args.kwargs
    payload = kwargs["json"]

    assert "options" in payload
    opts = payload["options"]
    
    assert opts["num_ctx"] == 2048
    assert opts["temperature"] == 0.7
    assert opts["top_p"] == 0.9

    # Verify they are NOT at the top level
    assert "num_ctx" not in payload
    assert "temperature" not in payload
    assert "top_p" not in payload
