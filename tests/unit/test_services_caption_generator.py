"""
Unit tests for app/services/caption_generator.py
"""
from unittest.mock import patch

import pytest

from app.services import AuthenticationError
from app.services.caption_generator import generate_insta_caption
from app.services.openrouter_client import OpenRouterError


class TestGenerateInstaCaption:
    """Tests for generate_insta_caption function."""

    @pytest.fixture
    def mock_chat(self):
        with patch(
            "app.services.caption_generator.openrouter_client.chat_completion"
        ) as mock_chat:
            yield mock_chat

    @pytest.fixture
    def mock_sleep(self):
        with patch("app.services.caption_generator.time.sleep") as mock_sleep:
            yield mock_sleep

    def test_successful_caption_generation(self, mock_chat, mock_sleep):
        mock_chat.return_value = (
            "Spannende Neuigkeiten aus dem Gemeinderat! #Kommunalpolitik #Rosdorf"
        )

        result = generate_insta_caption(
            "New Community Center Opens",
            "<h2>Grand Opening</h2><p>The new community center opened yesterday.</p>",
        )

        assert result is not None
        assert "Spannende Neuigkeiten" in result
        assert "#Rosdorf" in result
        mock_chat.assert_called_once()

        kwargs = mock_chat.call_args.kwargs
        assert kwargs["model"] == "deepseek/deepseek-v4.1-flash-1017"
        assert kwargs["temperature"] == 1.0
        assert kwargs["extra_body"] == {"reasoning": {"effort": "max"}}
        assert "The new community center opened yesterday" in kwargs["prompt"]

    def test_caption_generation_with_empty_response(self, mock_chat, mock_sleep):
        mock_chat.return_value = ""

        result = generate_insta_caption("Test Article", "<p>Test content</p>")

        assert result is None
        assert mock_chat.call_count == 5

    def test_caption_generation_with_exception(self, mock_chat, mock_sleep):
        mock_chat.side_effect = OpenRouterError("API Error", status_code=500)

        result = generate_insta_caption("Test Article", "<p>Test content</p>")

        assert result is None
        assert mock_chat.call_count == 5

    def test_caption_generation_strips_whitespace(self, mock_chat, mock_sleep):
        mock_chat.return_value = (
            "  \n  Wichtige Entscheidung im Rat gefallen! #Gemeinderat #Rosdorf  \n  "
        )

        result = generate_insta_caption("Test Article", "<p>Test content</p>")

        assert result == "Wichtige Entscheidung im Rat gefallen! #Gemeinderat #Rosdorf"
        assert not result.startswith(" ")
        assert not result.endswith(" ")

    def test_caption_generation_with_long_content(self, mock_chat, mock_sleep):
        mock_chat.return_value = "Neue Entwicklung im Bauausschuss! #Bauprojekte #Rosdorf"

        result = generate_insta_caption(
            "Council Approves New Budget",
            "<h2>Budget Discussion</h2><p>" + "Lorem ipsum dolor sit amet. " * 100 + "</p>",
        )

        assert result is not None
        assert "Bauausschuss" in result

    def test_success_on_retry(self, mock_chat, mock_sleep):
        mock_chat.side_effect = [
            OpenRouterError("API Error 1", status_code=500),
            OpenRouterError("API Error 2", status_code=500),
            "Erfolg nach mehreren Versuchen! #Rosdorf",
        ]

        result = generate_insta_caption("Test Article", "<p>Test content</p>")

        assert result == "Erfolg nach mehreren Versuchen! #Rosdorf"
        assert mock_chat.call_count == 3

    def test_prompt_contains_article_content(self, mock_chat, mock_sleep):
        mock_chat.return_value = "Test caption #Rosdorf"

        generate_insta_caption("Test Article", "<p>Article content here</p>")

        prompt = mock_chat.call_args.kwargs["prompt"]
        assert "Article content here" in prompt
        assert "Instagram-Caption" in prompt or "Caption" in prompt

    def test_fatal_error_raises_immediately(self, mock_chat, mock_sleep):
        """A 402 from OpenRouter should not be retried."""
        mock_chat.side_effect = OpenRouterError("Payment required", status_code=402)

        with pytest.raises(AuthenticationError):
            generate_insta_caption("Test Article", "<p>Test content</p>")

        assert mock_chat.call_count == 1
