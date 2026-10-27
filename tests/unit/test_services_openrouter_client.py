"""
Unit tests for app/services/openrouter_client.py
"""
import base64
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services.openrouter_client import (
    OpenRouterError,
    chat_completion,
    generate_image,
)


@pytest.fixture(autouse=True)
def _openrouter_api_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-api-key")


def _response(status_code: int, payload=None, text: str = ""):
    response = MagicMock()
    response.status_code = status_code
    if payload is None:
        response.json.side_effect = ValueError("not json")
    else:
        response.json.return_value = payload
    response.text = text
    return response


class TestChatCompletion:
    """Tests for the chat_completion helper."""

    @patch("app.services.openrouter_client.httpx.post")
    def test_successful_completion(self, mock_post):
        mock_post.return_value = _response(
            200,
            {
                "choices": [
                    {"message": {"content": "  Hello world  "}}
                ]
            },
        )

        result = chat_completion(
            model="deepseek/deepseek-v4.1-flash-1017",
            prompt="Say hello",
            temperature=0.5,
            max_tokens=100,
            extra_body={"reasoning": {"effort": "max"}},
        )

        assert result == "Hello world"
        args, kwargs = mock_post.call_args
        assert args[0].endswith("/chat/completions")
        assert kwargs["json"]["model"] == "deepseek/deepseek-v4.1-flash-1017"
        assert kwargs["json"]["messages"] == [{"role": "user", "content": "Say hello"}]
        assert kwargs["json"]["temperature"] == 0.5
        assert kwargs["json"]["max_tokens"] == 100
        assert kwargs["json"]["reasoning"] == {"effort": "max"}
        assert kwargs["headers"]["Authorization"].startswith("Bearer ")

    @patch("app.services.openrouter_client.httpx.post")
    def test_http_error_raises_openrouter_error(self, mock_post):
        mock_post.return_value = _response(
            429,
            {"error": {"message": "Rate limit exceeded"}},
        )

        with pytest.raises(OpenRouterError) as exc_info:
            chat_completion(model="model", prompt="prompt")

        assert exc_info.value.status_code == 429
        assert "Rate limit exceeded" in str(exc_info.value)

    @patch("app.services.openrouter_client.httpx.post")
    def test_invalid_json_raises_openrouter_error(self, mock_post):
        mock_post.return_value = _response(200, payload=None, text="not json")

        with pytest.raises(OpenRouterError, match="invalid JSON"):
            chat_completion(model="model", prompt="prompt")

    @patch("app.services.openrouter_client.httpx.post")
    def test_unexpected_shape_raises_openrouter_error(self, mock_post):
        mock_post.return_value = _response(200, {"choices": []})

        with pytest.raises(OpenRouterError, match="Unexpected OpenRouter chat response"):
            chat_completion(model="model", prompt="prompt")

    @patch("app.services.openrouter_client.httpx.post")
    def test_timeout_raises_openrouter_error(self, mock_post):
        mock_post.side_effect = httpx.TimeoutException("timed out")

        with pytest.raises(OpenRouterError, match="request failed"):
            chat_completion(model="model", prompt="prompt")

    @patch("app.services.openrouter_client.config.load_openrouter_api_key")
    def test_missing_api_key_raises(self, mock_load_key):
        mock_load_key.side_effect = ValueError("OPENROUTER_API_KEY not found")

        with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
            chat_completion(model="model", prompt="prompt")


class TestGenerateImage:
    """Tests for the generate_image helper."""

    @patch("app.services.openrouter_client.httpx.post")
    def test_successful_image_generation(self, mock_post):
        encoded = base64.b64encode(b"image-bytes").decode()
        mock_post.return_value = _response(
            200,
            {"data": [{"b64_json": encoded, "media_type": "image/png"}]},
        )

        result = generate_image(
            model="google/gemini-3.1-flash-image",
            prompt="A test image",
            aspect_ratio="9:16",
        )

        assert result == b"image-bytes"
        args, kwargs = mock_post.call_args
        assert args[0].endswith("/images")
        assert kwargs["json"] == {
            "model": "google/gemini-3.1-flash-image",
            "prompt": "A test image",
            "aspect_ratio": "9:16",
            "n": 1,
        }

    @patch("app.services.openrouter_client.httpx.post")
    def test_image_http_error_raises_openrouter_error(self, mock_post):
        mock_post.return_value = _response(
            402,
            {"error": {"message": "Payment required"}},
        )

        with pytest.raises(OpenRouterError) as exc_info:
            generate_image(model="model", prompt="prompt")

        assert exc_info.value.status_code == 402

    @patch("app.services.openrouter_client.httpx.post")
    def test_invalid_image_payload_raises_openrouter_error(self, mock_post):
        mock_post.return_value = _response(200, {"data": []})

        with pytest.raises(OpenRouterError, match="Unexpected OpenRouter image response"):
            generate_image(model="model", prompt="prompt")

    @patch("app.services.openrouter_client.httpx.post")
    def test_invalid_base64_raises_openrouter_error(self, mock_post):
        mock_post.return_value = _response(200, {"data": [{"b64_json": "!!!"}]})

        with pytest.raises(OpenRouterError, match="invalid base64"):
            generate_image(model="model", prompt="prompt")
