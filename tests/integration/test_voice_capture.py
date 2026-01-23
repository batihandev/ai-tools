# tests/integration/test_voice_capture.py
"""Integration tests for scripts/voice_capture.py."""

from unittest.mock import patch, MagicMock
from pathlib import Path


class TestLiteralize:
    """Tests for the literalize function."""

    def test_removes_punctuation(self):
        """literalize should remove punctuation."""
        from scripts.voice_capture import literalize

        result = literalize("Hello, world! How are you?")

        assert result == "hello world how are you"

    def test_preserves_apostrophes(self):
        """literalize should preserve apostrophes in contractions."""
        from scripts.voice_capture import literalize

        result = literalize("I can't believe it's working!")

        assert "can't" in result
        assert "it's" in result

    def test_lowercases(self):
        """literalize should lowercase all text."""
        from scripts.voice_capture import literalize

        result = literalize("THIS IS UPPERCASE")

        assert result == "this is uppercase"

    def test_normalizes_whitespace(self):
        """literalize should normalize multiple spaces."""
        from scripts.voice_capture import literalize

        result = literalize("Too   many    spaces")

        assert result == "too many spaces"


class TestParseArgs:
    """Tests for argument parsing."""

    def test_file_mode_basic(self):
        """parse_args should handle file mode."""
        from scripts.voice_capture import parse_args

        args = parse_args(["/path/to/audio.wav"])

        assert args.mode == "file"
        assert args.target == Path("/path/to/audio.wav")

    def test_record_mode(self):
        """parse_args should handle record mode."""
        from scripts.voice_capture import parse_args

        args = parse_args(["record", "15"])

        assert args.mode == "record"
        assert args.seconds == 15

    def test_custom_model(self):
        """parse_args should handle --model flag."""
        from scripts.voice_capture import parse_args

        args = parse_args(["/audio.wav", "--model", "large-v3"])

        assert args.model == "large-v3"

    def test_text_mode_raw(self):
        """parse_args should handle --text raw flag."""
        from scripts.voice_capture import parse_args

        args = parse_args(["/audio.wav", "--text", "raw"])

        assert args.text_mode == "raw"


class TestTranscribeFile:
    """Tests for transcribe_file with mocked Whisper model."""

    @patch("scripts.voice_capture._get_model")
    def test_transcribe_returns_tuple(self, mock_get_model):
        """transcribe_file should return (raw_text, literal_text, meta)."""
        from scripts.voice_capture import transcribe_file

        # Mock the Whisper model
        mock_model = MagicMock()
        mock_segment = MagicMock()
        mock_segment.text = "Hello, world!"
        mock_info = MagicMock()
        mock_info.language = "en"
        mock_info.duration = 2.5
        mock_model.transcribe.return_value = ([mock_segment], mock_info)
        mock_get_model.return_value = mock_model

        raw, literal, meta = transcribe_file("/tmp/test.wav")

        assert raw == "Hello, world!"
        assert literal == "hello world"
        assert meta["language"] == "en"
        assert meta["duration"] == 2.5

    @patch("scripts.voice_capture._get_model")
    def test_transcribe_handles_empty_segments(self, mock_get_model):
        """transcribe_file should handle empty segments gracefully."""
        from scripts.voice_capture import transcribe_file

        mock_model = MagicMock()
        mock_info = MagicMock()
        mock_info.language = "en"
        mock_info.duration = 0.0
        mock_model.transcribe.return_value = ([], mock_info)
        mock_get_model.return_value = mock_model

        raw, literal, meta = transcribe_file("/tmp/empty.wav")

        assert raw == ""
        assert literal == ""
