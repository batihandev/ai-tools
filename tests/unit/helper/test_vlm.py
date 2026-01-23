# tests/unit/helper/test_vlm.py
"""Unit tests for vlm.py options."""

import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from scripts.helper.vlm import ollama_chat_with_images


@patch("scripts.helper.vlm._prepare_images_for_vlm")
@patch("scripts.helper.vlm.requests.post")
def test_vlm_sends_options_correctly(mock_post, mock_prep):
    """Verify that VLM helper puts num_ctx, etc. into options."""
    
    # Mock image prep
    mock_prep.return_value = (["base64image"], [(100, 100)])

    # Mock successful response
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "message": {"content": "ok"},
        "done_reason": "stop"
    }
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp

    ollama_chat_with_images(
        user_prompt="Explain this",
        image_paths=[Path("img.png")],
        num_ctx=8192,
        temperature=0.5,
    )

    # Check the call arguments
    assert mock_post.called
    kwargs = mock_post.call_args.kwargs
    payload = kwargs["json"]

    assert "options" in payload
    opts = payload["options"]
    
    assert opts["num_ctx"] == 8192
    assert opts["temperature"] == 0.5
    
    # num_batch might be in options if env var is set or default is used
    # Just ensure structure is correct
    assert "num_ctx" not in payload
