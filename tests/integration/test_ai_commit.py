# tests/integration/test_ai_commit.py
"""Integration tests for scripts/ai_commit.py."""

import json
from unittest.mock import patch


class TestGenerateCommit:
    """Tests for the generate_commit function with mocked LLM."""

    @patch("scripts.ai_commit.ollama_chat")
    def test_generate_commit_valid_response(self, mock_ollama):
        """generate_commit should parse valid LLM JSON response."""
        from scripts.ai_commit import generate_commit, CommitCfg

        mock_ollama.return_value = json.dumps({
            "summary": "Add user authentication",
            "bullets": [
                {"path": "auth.py", "explanation": "Added login function"},
                {"path": "routes.py", "explanation": "Added /login endpoint"}
            ]
        })

        cfg = CommitCfg()
        diff = "diff --git a/auth.py b/auth.py\n+def login(): pass"
        
        result = generate_commit(diff, cfg)

        assert result.summary == "Add user authentication"
        assert len(result.bullets) == 2
        assert result.bullets[0].path == "auth.py"
        assert not result.is_error

    @patch("scripts.ai_commit.ollama_chat")
    def test_generate_commit_with_markdown_fence(self, mock_ollama):
        """generate_commit should handle markdown-wrapped JSON."""
        from scripts.ai_commit import generate_commit, CommitCfg

        mock_ollama.return_value = """```json
{
    "summary": "Fix bug in parser",
    "bullets": [{"path": "parser.py", "explanation": "Fixed edge case"}]
}
```"""

        cfg = CommitCfg()
        result = generate_commit("dummy diff", cfg)

        assert result.summary == "Fix bug in parser"
        assert not result.is_error

    @patch("scripts.ai_commit.ollama_chat")
    def test_generate_commit_handles_llm_error(self, mock_ollama):
        """generate_commit should return error state on LLM failure."""
        from scripts.ai_commit import generate_commit, CommitCfg

        mock_ollama.side_effect = Exception("Network error")

        cfg = CommitCfg()
        result = generate_commit("dummy diff", cfg)

        assert result.is_error is True
        assert "Network error" in result.raw_output

    @patch("scripts.ai_commit.ollama_chat")
    def test_generate_commit_handles_invalid_json(self, mock_ollama):
        """generate_commit should handle invalid JSON gracefully."""
        from scripts.ai_commit import generate_commit, CommitCfg

        mock_ollama.return_value = "This is not valid JSON..."

        cfg = CommitCfg()
        result = generate_commit("dummy diff", cfg)

        assert result.is_error is True

    @patch("scripts.ai_commit.ollama_chat")
    def test_generate_commit_alias_handling(self, mock_ollama):
        """generate_commit should handle 'title' alias for 'summary'."""
        from scripts.ai_commit import generate_commit, CommitCfg

        # Some LLMs might use "title" instead of "summary"
        mock_ollama.return_value = json.dumps({
            "title": "Update README",
            "bullets": []
        })

        cfg = CommitCfg()
        result = generate_commit("dummy diff", cfg)

        assert result.summary == "Update README"
        assert not result.is_error
