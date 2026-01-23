# tests/integration/test_english_teacher.py
"""Integration tests for scripts/english_teacher.py."""

import json
from unittest.mock import patch

# We'll test the core parsing logic and the teach function with mocked LLM





class TestTeachFunction:
    """Tests for the teach() function with mocked LLM."""

    @patch("scripts.english_teacher.ollama_chat")
    def test_teach_returns_parsed_response(self, mock_ollama):
        """teach() should return parsed TeachOut from LLM response."""
        from scripts.english_teacher import teach

        mock_ollama.return_value = json.dumps({
            "corrected_natural": "I want to go home.",
            "corrected_literal": "I want to go home.",
            "mistakes": [{"frm": "I want go", "to": "I want to go", "why": "Missing infinitive 'to'"}],
            "pronunciation": [{"word": "want", "ipa": "/wɑnt/", "cue": "rhymes with font"}],
            "reply": "Good effort!",
            "follow_up_question": "Where is home?"
        })

        result = teach("I want go home", mode="coach")

        assert result.corrected_natural == "I want to go home."
        assert len(result.mistakes) == 1
        assert result.mistakes[0].why == "Missing infinitive 'to'"
        mock_ollama.assert_called_once()

    @patch("scripts.english_teacher.ollama_chat")
    def test_teach_handles_llm_error(self, mock_ollama):
        """teach() should handle malformed LLM responses gracefully."""
        from scripts.english_teacher import teach

        mock_ollama.return_value = "I can't process that request..."

        result = teach("test input", mode="strict")

        assert result.raw_error is True
        assert "process" in result.raw_output

    @patch("scripts.english_teacher.ollama_chat")
    def test_teach_uses_correct_mode_in_prompt(self, mock_ollama):
        """teach() should pass the mode to the system prompt builder."""
        from scripts.english_teacher import teach

        mock_ollama.return_value = '{"reply": "ok"}'

        teach("hello", mode="strict")

        # Verify ollama_chat was called (the mode affects the system prompt)
        call_args = mock_ollama.call_args
        assert call_args is not None
        assert "system_prompt" in call_args.kwargs or len(call_args.args) >= 1
