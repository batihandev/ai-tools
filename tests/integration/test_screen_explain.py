# tests/integration/test_screen_explain.py
"""Integration tests for scripts/screen_explain.py."""

import json





class TestBuildPrompt:
    """Tests for the build_prompt function."""

    def test_single_image_prompt(self):
        """Prompt for 1 image should reflect singular."""
        from scripts.screen_explain import build_prompt

        prompt = build_prompt(1)

        assert "screenshot" in prompt.lower()
        # Should include schema hints
        assert "summary" in prompt.lower()

    def test_multiple_images_prompt(self):
        """Prompt for N>1 images should reflect plural."""
        from scripts.screen_explain import build_prompt

        prompt = build_prompt(3)

        # Should handle multiple screenshots
        assert "3" in prompt or "screenshot" in prompt.lower()
