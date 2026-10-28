"""
Unit tests for app/services/article_generator.py
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from app.core.models import LLMGeneratedArticles, SingleArticle
from app.services import ArticleGenerationError, AuthenticationError
from app.services.article_generator import (
    _is_auth_error,
    _parse_articles,
    _strip_code_fences,
    generate_articles,
)
from app.services.openrouter_client import OpenRouterError


def _valid_articles_json() -> str:
    return json.dumps(
        {
            "artikel": [
                {
                    "ueberschrift": "Test headline",
                    "inhalt": "<p>Test content.</p>",
                }
            ]
        }
    )


class TestIsAuthError:
    """Tests for the _is_auth_error helper function."""

    @pytest.mark.parametrize("status", [401, 402, 403])
    def test_detects_fatal_status_codes(self, status):
        exc = MagicMock()
        exc.status_code = status
        assert _is_auth_error(exc) is True

    def test_detects_status_attribute(self):
        exc = MagicMock()
        exc.status_code = None
        exc.status = 401
        exc.code = None
        assert _is_auth_error(exc) is True

    def test_detects_code_attribute(self):
        exc = MagicMock()
        exc.status_code = None
        exc.status = None
        exc.code = 403
        assert _is_auth_error(exc) is True

    @pytest.mark.parametrize(
        "message",
        [
            "Unauthorized",
            "Access forbidden",
            "Invalid API key",
            "Authentication failed",
            "Permission denied",
            "Payment required",
            "Insufficient credits",
        ],
    )
    def test_detects_auth_keywords(self, message):
        assert _is_auth_error(Exception(message)) is True

    def test_non_auth_error_returns_false(self):
        assert _is_auth_error(Exception("Network timeout")) is False

    def test_rate_limit_error_is_retryable(self):
        exc = MagicMock()
        exc.status_code = 429
        exc.status = None
        exc.code = None
        assert _is_auth_error(exc) is False


class TestParsing:
    """Tests for JSON response parsing helpers."""

    def test_strips_markdown_fences(self):
        raw = '```json\n{"artikel": []}\n```'
        assert _strip_code_fences(raw) == '{"artikel": []}'

    def test_parses_valid_articles(self):
        parsed = _parse_articles(_valid_articles_json())
        assert isinstance(parsed, LLMGeneratedArticles)
        assert len(parsed.artikel) == 1
        assert parsed.artikel[0].ueberschrift == "Test headline"


class TestGenerateArticles:
    """Tests for generate_articles with the OpenRouter client mocked."""

    @patch("app.services.article_generator.time.sleep")
    @patch("app.services.article_generator.openrouter_client.chat_completion")
    def test_successful_generation(self, mock_chat, mock_sleep):
        mock_chat.return_value = _valid_articles_json()

        result = generate_articles("Protocol text")

        assert len(result) == 1
        assert isinstance(result[0], SingleArticle)
        assert result[0].ueberschrift == "Test headline"

        kwargs = mock_chat.call_args.kwargs
        assert kwargs["model"] == "deepseek/deepseek-v4.1-flash-1017"
        assert kwargs["response_format"]["type"] == "json_schema"
        assert kwargs["response_format"]["json_schema"]["strict"] is True
        assert "artikel" in kwargs["response_format"]["json_schema"]["schema"]["properties"]
        assert "Protocol text" in kwargs["prompt"]
        assert kwargs["extra_body"] == {"reasoning": {"effort": "max"}}
        mock_chat.assert_called_once()

    @patch("app.services.article_generator.time.sleep")
    @patch("app.services.article_generator.openrouter_client.chat_completion")
    def test_markdown_fenced_response_is_accepted(self, mock_chat, mock_sleep):
        mock_chat.return_value = f"```json\n{_valid_articles_json()}\n```"

        result = generate_articles("Protocol text")

        assert len(result) == 1

    @patch("app.services.article_generator.openrouter_client.chat_completion")
    def test_auth_error_raises_immediately_without_retries(self, mock_chat):
        mock_chat.side_effect = OpenRouterError("Unauthorized", status_code=401)

        with pytest.raises(AuthenticationError):
            generate_articles("Protocol text")

        assert mock_chat.call_count == 1

    @patch("app.services.article_generator.openrouter_client.chat_completion")
    def test_missing_credits_raise_immediately_without_retries(self, mock_chat):
        mock_chat.side_effect = OpenRouterError("Payment required", status_code=402)

        with pytest.raises(AuthenticationError):
            generate_articles("Protocol text")

        assert mock_chat.call_count == 1

    @patch("app.services.article_generator.time.sleep")
    @patch("app.services.article_generator.openrouter_client.chat_completion")
    def test_non_auth_error_is_retried(self, mock_chat, mock_sleep):
        mock_chat.side_effect = [
            OpenRouterError("Server error", status_code=500),
            OpenRouterError("Server error", status_code=500),
            _valid_articles_json(),
        ]

        result = generate_articles("Protocol text")

        assert len(result) == 1
        assert mock_chat.call_count == 3

    @patch("app.services.article_generator.time.sleep")
    @patch("app.services.article_generator.openrouter_client.chat_completion")
    def test_raises_after_max_retries(self, mock_chat, mock_sleep):
        mock_chat.side_effect = OpenRouterError("Server error", status_code=500)

        with pytest.raises(ArticleGenerationError):
            generate_articles("Protocol text")

        assert mock_chat.call_count == 3

    @patch("app.services.article_generator.time.sleep")
    @patch("app.services.article_generator.openrouter_client.chat_completion")
    def test_empty_response_returns_empty_list(self, mock_chat, mock_sleep):
        mock_chat.return_value = ""

        result = generate_articles("Protocol text")

        assert result == []
        assert mock_chat.call_count == 3

    @patch("app.services.article_generator.time.sleep")
    @patch("app.services.article_generator.openrouter_client.chat_completion")
    def test_empty_article_list_returns_empty_list(self, mock_chat, mock_sleep):
        mock_chat.return_value = '{"artikel": []}'

        result = generate_articles("Protocol text")

        assert result == []
        assert mock_chat.call_count == 3

    @patch("app.services.article_generator.time.sleep")
    @patch("app.services.article_generator.openrouter_client.chat_completion")
    def test_invalid_json_is_retried_then_raises(self, mock_chat, mock_sleep):
        mock_chat.return_value = "not-json"

        with pytest.raises(ArticleGenerationError):
            generate_articles("Protocol text")

        assert mock_chat.call_count == 3
