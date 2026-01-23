# tests/conftest.py
"""Root pytest configuration and fixtures for ai-scripts tests."""

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_ollama_response():
    """Factory fixture for mocking Ollama API responses."""
    def _make_response(content: str):
        return {"message": {"content": content}, "done_reason": "stop"}
    return _make_response


@pytest.fixture
def mock_ollama_chat(mock_ollama_response):
    """Mock the ollama_chat function from helper/llm.py."""
    with patch("scripts.helper.llm.requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_ollama_response("Mocked LLM response")
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp
        yield mock_post


@pytest.fixture
def mock_vlm_response():
    """Factory fixture for mocking VLM API responses."""
    def _make_response(json_content: str):
        return {"message": {"content": json_content}, "done_reason": "stop"}
    return _make_response
