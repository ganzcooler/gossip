"""
Unit tests for app/services/image_generator.py
"""
from unittest.mock import patch

import pytest

from app.core.models import SingleArticle
from app.services import AuthenticationError
from app.services.image_generator import (
    _is_fatal_error,
    generate_image,
    generate_image_for_article,
    generate_image_prompt,
    make_prompt_realistic,
    validate_image_prompt,
)
from app.services.openrouter_client import OpenRouterError


class TestIsFatalError:
    """Tests for the _is_fatal_error helper."""

    @pytest.mark.parametrize("status", [401, 402, 403])
    def test_fatal_status_codes(self, status):
        exc = OpenRouterError("fatal", status_code=status)
        assert _is_fatal_error(exc) is True

    def test_non_fatal_status_code(self):
        exc = OpenRouterError("server error", status_code=500)
        assert _is_fatal_error(exc) is False

    def test_message_keywords(self):
        assert _is_fatal_error(Exception("Payment required")) is True
        assert _is_fatal_error(Exception("Network timeout")) is False


class TestValidateImagePrompt:
    """Tests for validate_image_prompt."""

    @patch("app.services.image_generator.openrouter_client.chat_completion")
    def test_returns_true_when_llm_responds_yes(self, mock_chat):
        mock_chat.return_value = "YES"

        prompt = "A realistic photo of a city council meeting"
        result = validate_image_prompt(prompt)

        assert result == (True, prompt)
        mock_chat.assert_called_once()
        assert mock_chat.call_args.kwargs["model"] == "deepseek/deepseek-v4.1-flash-1017"
        assert mock_chat.call_args.kwargs["temperature"] == 1.0
        assert mock_chat.call_args.kwargs["extra_body"] == {
            "reasoning": {"effort": "max"}
        }

    @patch("app.services.image_generator.openrouter_client.chat_completion")
    def test_returns_false_when_llm_responds_no(self, mock_chat):
        mock_chat.return_value = "NO"

        prompt = "A cartoon style image of a meeting"
        result = validate_image_prompt(prompt)

        assert result == (False, prompt)

    @patch("app.services.image_generator.openrouter_client.chat_completion")
    def test_returns_false_on_api_exception(self, mock_chat):
        mock_chat.side_effect = OpenRouterError("API Error", status_code=500)

        prompt = "Some prompt"
        result = validate_image_prompt(prompt)

        assert result == (False, prompt)

    @patch("app.services.image_generator.openrouter_client.chat_completion")
    def test_returns_false_on_empty_response(self, mock_chat):
        mock_chat.return_value = ""

        prompt = "Some prompt"
        result = validate_image_prompt(prompt)

        assert result == (False, prompt)

    @patch("app.services.image_generator.openrouter_client.chat_completion")
    def test_handles_whitespace_in_response(self, mock_chat):
        mock_chat.return_value = "  yes  "

        prompt = "A prompt"
        result = validate_image_prompt(prompt)

        assert result == (True, prompt)

    @patch("app.services.image_generator.openrouter_client.chat_completion")
    def test_fatal_error_raises_authentication_error(self, mock_chat):
        mock_chat.side_effect = OpenRouterError("Payment required", status_code=402)

        with pytest.raises(AuthenticationError):
            validate_image_prompt("A prompt")


class TestMakePromptRealistic:
    """Tests for make_prompt_realistic."""

    @patch("app.services.image_generator.openrouter_client.chat_completion")
    def test_returns_rewritten_prompt(self, mock_chat):
        rewritten = "A realistic photograph of a city hall building with natural lighting"
        mock_chat.return_value = rewritten

        result = make_prompt_realistic("A cartoon of a city hall")

        assert result == rewritten
        mock_chat.assert_called_once()

    @patch("app.services.image_generator.openrouter_client.chat_completion")
    def test_returns_original_prompt_on_empty_response(self, mock_chat):
        mock_chat.return_value = ""

        original_prompt = "A cartoon of a city hall"
        result = make_prompt_realistic(original_prompt)

        assert result == original_prompt

    @patch("app.services.image_generator.openrouter_client.chat_completion")
    def test_returns_original_prompt_on_api_exception(self, mock_chat):
        mock_chat.side_effect = OpenRouterError("API Error", status_code=500)

        original_prompt = "A cartoon of a city hall"
        result = make_prompt_realistic(original_prompt)

        assert result == original_prompt

    @patch("app.services.image_generator.openrouter_client.chat_completion")
    def test_fatal_error_raises_authentication_error(self, mock_chat):
        mock_chat.side_effect = OpenRouterError("Payment required", status_code=402)

        with pytest.raises(AuthenticationError):
            make_prompt_realistic("A cartoon of a city hall")


class TestGenerateImagePrompt:
    """Tests for generate_image_prompt."""

    @patch("app.services.image_generator.time.sleep")
    @patch("app.services.image_generator.openrouter_client.chat_completion")
    def test_successful_prompt_generation(self, mock_chat, mock_sleep):
        mock_chat.return_value = "A detailed image prompt for the article"

        article = SingleArticle(ueberschrift="Test Article", inhalt="Test content")
        result = generate_image_prompt(article)

        assert result == "A detailed image prompt for the article"
        kwargs = mock_chat.call_args.kwargs
        assert kwargs["model"] == "deepseek/deepseek-v4.1-flash-1017"
        assert "Test Article" in kwargs["prompt"]
        assert "Test content" in kwargs["prompt"]
        assert kwargs["extra_body"] == {"reasoning": {"effort": "max"}}

    @patch("app.services.image_generator.time.sleep")
    @patch("app.services.image_generator.openrouter_client.chat_completion")
    def test_retries_on_empty_response(self, mock_chat, mock_sleep):
        mock_chat.side_effect = ["", "", "Final prompt"]

        article = SingleArticle(ueberschrift="Test Article", inhalt="Test content")
        result = generate_image_prompt(article)

        assert result == "Final prompt"
        assert mock_chat.call_count == 3

    @patch("app.services.image_generator.time.sleep")
    @patch("app.services.image_generator.openrouter_client.chat_completion")
    def test_returns_empty_after_max_retries(self, mock_chat, mock_sleep):
        mock_chat.side_effect = OpenRouterError("API Error", status_code=500)

        article = SingleArticle(ueberschrift="Test Article", inhalt="Test content")
        result = generate_image_prompt(article)

        assert result == ""
        assert mock_chat.call_count == 5

    @patch("app.services.image_generator.openrouter_client.chat_completion")
    def test_fatal_error_raises_immediately(self, mock_chat):
        mock_chat.side_effect = OpenRouterError("Payment required", status_code=402)

        article = SingleArticle(ueberschrift="Test Article", inhalt="Test content")
        with pytest.raises(AuthenticationError):
            generate_image_prompt(article)

        assert mock_chat.call_count == 1


class TestGenerateImage:
    """Tests for generate_image."""

    @patch("app.services.image_generator.time.sleep")
    @patch("app.services.image_generator.openrouter_client.generate_image")
    def test_successful_image_generation(self, mock_generate, mock_sleep):
        mock_generate.return_value = b"image_data_bytes"

        result = generate_image("A test prompt")

        assert result == b"image_data_bytes"
        kwargs = mock_generate.call_args.kwargs
        assert kwargs["model"] == "google/gemini-3.1-flash-image"
        assert kwargs["prompt"] == "A test prompt"
        assert kwargs["aspect_ratio"] == "9:16"
        mock_generate.assert_called_once()

    @patch("app.services.image_generator.time.sleep")
    @patch("app.services.image_generator.openrouter_client.generate_image")
    def test_retries_on_failure(self, mock_generate, mock_sleep):
        mock_generate.side_effect = [
            OpenRouterError("Network error", status_code=500),
            OpenRouterError("Timeout", status_code=504),
            b"image_data_bytes",
        ]

        result = generate_image("A test prompt")

        assert result == b"image_data_bytes"
        assert mock_generate.call_count == 3

    @patch("app.services.image_generator.time.sleep")
    @patch("app.services.image_generator.openrouter_client.generate_image")
    def test_returns_empty_bytes_after_max_retries(self, mock_generate, mock_sleep):
        mock_generate.side_effect = OpenRouterError("Persistent error", status_code=500)

        result = generate_image("A test prompt")

        assert result == b""
        assert mock_generate.call_count == 5

    @patch("app.services.image_generator.openrouter_client.generate_image")
    def test_fatal_error_raises_immediately(self, mock_generate):
        mock_generate.side_effect = OpenRouterError("Payment required", status_code=402)

        with pytest.raises(AuthenticationError):
            generate_image("A test prompt")

        assert mock_generate.call_count == 1


class TestGenerateImageForArticle:
    """Tests for the validation loop in generate_image_for_article."""

    @patch("app.services.image_generator.generate_image")
    @patch("app.services.image_generator.generate_image_prompt")
    @patch("app.services.image_generator.validate_image_prompt")
    def test_first_validation_true_exits_immediately(
        self, mock_validate, mock_gen_prompt, mock_gen_image
    ):
        test_prompt = "A realistic photo of a meeting"
        mock_gen_prompt.return_value = test_prompt
        mock_validate.return_value = (True, test_prompt)
        mock_gen_image.return_value = b"fake_image_data"

        article = SingleArticle(ueberschrift="Test Article", inhalt="Test content")
        result_prompt, result_image = generate_image_for_article(article)

        assert result_prompt == test_prompt
        assert result_image == b"fake_image_data"
        mock_validate.assert_called_once_with(test_prompt)
        mock_gen_image.assert_called_once_with(test_prompt)

    @patch("app.services.image_generator.generate_image")
    @patch("app.services.image_generator.make_prompt_realistic")
    @patch("app.services.image_generator.generate_image_prompt")
    @patch("app.services.image_generator.validate_image_prompt")
    def test_validation_false_calls_make_prompt_realistic(
        self, mock_validate, mock_gen_prompt, mock_rewrite, mock_gen_image
    ):
        original_prompt = "A cartoon style image"
        rewritten_prompt = "A realistic photo of a city council building"
        mock_gen_prompt.return_value = original_prompt
        mock_validate.side_effect = [
            (False, original_prompt),
            (True, rewritten_prompt),
        ]
        mock_rewrite.return_value = rewritten_prompt
        mock_gen_image.return_value = b"fake_image_data"

        article = SingleArticle(ueberschrift="Test Article", inhalt="Test content")
        result_prompt, result_image = generate_image_for_article(article)

        assert result_prompt == rewritten_prompt
        assert result_image == b"fake_image_data"
        mock_rewrite.assert_called_once_with(original_prompt)
        assert mock_validate.call_count == 2
        mock_gen_image.assert_called_once_with(rewritten_prompt)

    @patch("app.services.image_generator.generate_image")
    @patch("app.services.image_generator.make_prompt_realistic")
    @patch("app.services.image_generator.generate_image_prompt")
    @patch("app.services.image_generator.validate_image_prompt")
    def test_after_three_failed_validations_proceeds_anyway(
        self, mock_validate, mock_gen_prompt, mock_rewrite, mock_gen_image
    ):
        mock_gen_prompt.return_value = "Original prompt"
        mock_validate.return_value = (False, "Not realistic")
        mock_rewrite.side_effect = ["Rewrite 1", "Rewrite 2"]
        mock_gen_image.return_value = b"fake_image_data"

        article = SingleArticle(ueberschrift="Test Article", inhalt="Test content")
        result_prompt, result_image = generate_image_for_article(article)

        assert result_image == b"fake_image_data"
        assert mock_validate.call_count == 3
        assert mock_rewrite.call_count == 2

    @patch("app.services.image_generator.generate_image")
    @patch("app.services.image_generator.generate_image_prompt")
    def test_empty_prompt_returns_early(self, mock_gen_prompt, mock_gen_image):
        mock_gen_prompt.return_value = ""

        article = SingleArticle(ueberschrift="Test Article", inhalt="Test content")
        result_prompt, result_image = generate_image_for_article(article)

        assert result_prompt == ""
        assert result_image == b""
        mock_gen_image.assert_not_called()
