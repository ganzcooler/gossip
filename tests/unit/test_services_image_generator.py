"""
Unit tests for app/services/image_generator.py
"""
import pytest
from unittest.mock import MagicMock, patch

from app.services.image_generator import (
    validate_image_prompt,
    make_prompt_realistic,
    generate_image_for_article,
    generate_image_prompt,
    generate_image,
)
from app.core.models import SingleArticle


class TestValidateImagePrompt:
    """Tests for the validate_image_prompt function."""

    def test_returns_true_when_llm_responds_yes(self):
        """Test that validate_image_prompt returns (True, prompt) when LLM responds 'YES'."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "YES"
        mock_client.models.generate_content.return_value = mock_response

        prompt = "A realistic photo of a city council meeting"
        result = validate_image_prompt(prompt, mock_client)

        assert result == (True, prompt)
        mock_client.models.generate_content.assert_called_once()

    def test_returns_false_when_llm_responds_no(self):
        """Test that validate_image_prompt returns (False, prompt) when LLM responds 'NO'."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "NO"
        mock_client.models.generate_content.return_value = mock_response

        prompt = "A cartoon style image of a meeting"
        result = validate_image_prompt(prompt, mock_client)

        assert result == (False, prompt)
        mock_client.models.generate_content.assert_called_once()

    def test_returns_false_on_api_exception(self):
        """Test that validate_image_prompt returns (False, prompt) when API raises exception."""
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("API Error")

        prompt = "Some prompt"
        result = validate_image_prompt(prompt, mock_client)

        assert result == (False, prompt)
        mock_client.models.generate_content.assert_called_once()

    def test_returns_false_on_empty_response(self):
        """Test that validate_image_prompt returns (False, prompt) on empty response."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = ""
        mock_client.models.generate_content.return_value = mock_response

        prompt = "Some prompt"
        result = validate_image_prompt(prompt, mock_client)

        assert result == (False, prompt)

    def test_handles_whitespace_in_response(self):
        """Test that validate_image_prompt handles whitespace in YES/NO response."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "  yes  "
        mock_client.models.generate_content.return_value = mock_response

        prompt = "A prompt"
        result = validate_image_prompt(prompt, mock_client)

        assert result == (True, prompt)


class TestMakePromptRealistic:
    """Tests for the make_prompt_realistic function."""

    def test_returns_rewritten_prompt(self):
        """Test that make_prompt_realistic returns the rewritten prompt from LLM."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        rewritten = "A realistic photograph of a city hall building with natural lighting"
        mock_response.text = rewritten
        mock_client.models.generate_content.return_value = mock_response

        original_prompt = "A cartoon of a city hall"
        result = make_prompt_realistic(original_prompt, mock_client)

        assert result == rewritten
        mock_client.models.generate_content.assert_called_once()

    def test_returns_original_prompt_on_empty_response(self):
        """Test that make_prompt_realistic returns original prompt on empty response."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = ""
        mock_client.models.generate_content.return_value = mock_response

        original_prompt = "A cartoon of a city hall"
        result = make_prompt_realistic(original_prompt, mock_client)

        assert result == original_prompt

    def test_returns_original_prompt_on_api_exception(self):
        """Test that make_prompt_realistic returns original prompt on API exception."""
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("API Error")

        original_prompt = "A cartoon of a city hall"
        result = make_prompt_realistic(original_prompt, mock_client)

        assert result == original_prompt


class TestGenerateImageForArticleValidationLoop:
    """Tests for the validation loop in generate_image_for_article."""

    @patch('app.services.image_generator.generate_image')
    @patch('app.services.image_generator.generate_image_prompt')
    @patch('app.services.image_generator.genai.Client')
    @patch('app.services.image_generator.config.load_google_api_key')
    def test_first_validation_true_exits_immediately(
        self, mock_load_key, mock_client_class, mock_gen_prompt, mock_gen_image
    ):
        """Test that when first validation returns True, loop exits immediately and proceeds to image generation."""
        mock_load_key.return_value = "test-key"
        
        # Setup mock client
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        # Mock generate_image_prompt to return a prompt
        test_prompt = "A realistic photo of a meeting"
        mock_gen_prompt.return_value = test_prompt
        
        # Mock validate_image_prompt to return True immediately
        mock_validation_response = MagicMock()
        mock_validation_response.text = "YES"
        mock_client.models.generate_content.return_value = mock_validation_response
        
        # Mock generate_image to return image bytes
        mock_gen_image.return_value = b"fake_image_data"
        
        article = SingleArticle(ueberschrift="Test Article", inhalt="Test content")
        result_prompt, result_image = generate_image_for_article(article)
        
        # Should proceed to image generation
        assert result_prompt == test_prompt
        assert result_image == b"fake_image_data"
        
        # generate_image should be called exactly once
        mock_gen_image.assert_called_once_with(test_prompt)

    @patch('app.services.image_generator.time.sleep')
    @patch('app.services.image_generator.generate_image')
    @patch('app.services.image_generator.genai.Client')
    @patch('app.services.image_generator.config.load_google_api_key')
    def test_validation_false_calls_make_prompt_realistic(
        self, mock_load_key, mock_client_class, mock_gen_image, mock_sleep
    ):
        """Test that when validation returns False, it calls make_prompt_realistic and retries."""
        mock_load_key.return_value = "test-key"
        
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        # First validation returns False, second returns True
        first_response = MagicMock()
        first_response.text = "NO"
        second_response = MagicMock()
        second_response.text = "YES"
        
        # First is validation (NO), second is rewrite, third is validation (YES)
        rewrite_response = MagicMock()
        rewrite_response.text = "A realistic photo of a city council building"
        
        mock_client.models.generate_content.side_effect = [
            first_response,    # First validation: NO
            rewrite_response,  # make_prompt_realistic call
            second_response,   # Second validation: YES
        ]
        
        mock_gen_image.return_value = b"fake_image_data"
        
        # Create article and directly set the prompt
        article = SingleArticle(ueberschrift="Test Article", inhalt="Test content")
        
        with patch('app.services.image_generator.generate_image_prompt') as mock_gen_prompt:
            original_prompt = "A cartoon style image"
            mock_gen_prompt.return_value = original_prompt
            result_prompt, result_image = generate_image_for_article(article)
        
        # Should have called generate_content 3 times: validate, rewrite, validate
        assert mock_client.models.generate_content.call_count == 3
        mock_gen_image.assert_called_once()

    @patch('app.services.image_generator.time.sleep')
    @patch('app.services.image_generator.generate_image')
    @patch('app.services.image_generator.genai.Client')
    @patch('app.services.image_generator.config.load_google_api_key')
    def test_after_three_failed_validations_proceeds_anyway(
        self, mock_load_key, mock_client_class, mock_gen_image, mock_sleep
    ):
        """Test that after 3 failed validations, it proceeds with last version anyway."""
        mock_load_key.return_value = "test-key"
        
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        # All validations return NO
        no_response = MagicMock()
        no_response.text = "NO"
        
        # Rewrites return new prompts
        rewrite1 = MagicMock()
        rewrite1.text = "First rewritten prompt"
        rewrite2 = MagicMock()
        rewrite2.text = "Second rewritten prompt"
        
        # Sequence: validate(NO), rewrite, validate(NO), rewrite, validate(NO)
        mock_client.models.generate_content.side_effect = [
            no_response,  # First validation: NO
            rewrite1,     # First rewrite
            no_response,  # Second validation: NO
            rewrite2,     # Second rewrite
            no_response,  # Third validation: NO (should proceed anyway)
        ]
        
        mock_gen_image.return_value = b"fake_image_data"
        
        article = SingleArticle(ueberschrift="Test Article", inhalt="Test content")
        
        with patch('app.services.image_generator.generate_image_prompt') as mock_gen_prompt:
            mock_gen_prompt.return_value = "Original prompt"
            result_prompt, result_image = generate_image_for_article(article)
        
        # Should have called generate_content 5 times: validate, rewrite, validate, rewrite, validate
        assert mock_client.models.generate_content.call_count == 5
        
        # Should still proceed to image generation with last version
        mock_gen_image.assert_called_once()
        assert result_image == b"fake_image_data"

    @patch('app.services.image_generator.time.sleep')
    @patch('app.services.image_generator.generate_image')
    @patch('app.services.image_generator.genai.Client')
    @patch('app.services.image_generator.config.load_google_api_key')
    def test_mixed_scenario_false_false_true_breaks(
        self, mock_load_key, mock_client_class, mock_gen_image, mock_sleep
    ):
        """Test with mixed scenarios (False, False, True should break and proceed)."""
        mock_load_key.return_value = "test-key"
        
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        # Create responses
        no_response = MagicMock()
        no_response.text = "NO"
        yes_response = MagicMock()
        yes_response.text = "YES"
        
        # Rewrites
        rewrite1 = MagicMock()
        rewrite1.text = "First rewritten prompt"
        rewrite2 = MagicMock()
        rewrite2.text = "Second rewritten prompt"
        
        # Sequence: validate(NO), rewrite, validate(NO), rewrite, validate(YES) -> break
        mock_client.models.generate_content.side_effect = [
            no_response,  # First validation: NO
            rewrite1,     # First rewrite
            no_response,  # Second validation: NO
            rewrite2,     # Second rewrite
            yes_response, # Third validation: YES -> should break
        ]
        
        mock_gen_image.return_value = b"final_image_data"
        
        article = SingleArticle(ueberschrift="Test Article", inhalt="Test content")
        
        with patch('app.services.image_generator.generate_image_prompt') as mock_gen_prompt:
            mock_gen_prompt.return_value = "Original prompt"
            result_prompt, result_image = generate_image_for_article(article)
        
        # Should have called generate_content 5 times and then proceeded to image generation
        assert mock_client.models.generate_content.call_count == 5
        mock_gen_image.assert_called_once()
        assert result_image == b"final_image_data"

    @patch('app.services.image_generator.generate_image')
    @patch('app.services.image_generator.genai.Client')
    @patch('app.services.image_generator.config.load_google_api_key')
    def test_empty_prompt_returns_early(
        self, mock_load_key, mock_client_class, mock_gen_image
    ):
        """Test that when generate_image_prompt returns empty, function returns early."""
        mock_load_key.return_value = "test-key"
        
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        article = SingleArticle(ueberschrift="Test Article", inhalt="Test content")
        
        with patch('app.services.image_generator.generate_image_prompt') as mock_gen_prompt:
            mock_gen_prompt.return_value = ""
            result_prompt, result_image = generate_image_for_article(article)
        
        # Should return empty values immediately
        assert result_prompt == ""
        assert result_image == b""
        
        # No validation or image generation should occur
        mock_client.models.generate_content.assert_not_called()
        mock_gen_image.assert_not_called()


class TestGenerateImage:
    """Tests for the generate_image function."""

    @patch('app.services.image_generator.time.sleep')
    @patch('app.services.image_generator.genai.Client')
    @patch('app.services.image_generator.config.load_google_api_key')
    def test_successful_image_generation(self, mock_load_key, mock_client_class, mock_sleep):
        """Test successful image generation."""
        mock_load_key.return_value = "test-key"
        
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        # Create mock response with inline data
        mock_response = MagicMock()
        mock_part = MagicMock()
        mock_part.inline_data = MagicMock()
        mock_part.inline_data.data = b"image_data_bytes"
        mock_response.parts = [mock_part]
        
        mock_client.models.generate_content.return_value = mock_response
        
        result = generate_image("A test prompt")
        
        assert result == b"image_data_bytes"
        mock_client.models.generate_content.assert_called_once()

    @patch('app.services.image_generator.time.sleep')
    @patch('app.services.image_generator.genai.Client')
    @patch('app.services.image_generator.config.load_google_api_key')
    def test_retries_on_failure(self, mock_load_key, mock_client_class, mock_sleep):
        """Test that generate_image retries on failure."""
        mock_load_key.return_value = "test-key"
        
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        # First 2 calls fail, 3rd succeeds
        mock_client.models.generate_content.side_effect = [
            Exception("Network error"),
            Exception("Timeout"),
            self._create_successful_response()
        ]
        
        result = generate_image("A test prompt")
        
        assert result == b"image_data_bytes"
        assert mock_client.models.generate_content.call_count == 3

    @patch('app.services.image_generator.time.sleep')
    @patch('app.services.image_generator.genai.Client')
    @patch('app.services.image_generator.config.load_google_api_key')
    def test_returns_empty_bytes_after_max_retries(self, mock_load_key, mock_client_class, mock_sleep):
        """Test that generate_image returns empty bytes after max retries."""
        mock_load_key.return_value = "test-key"
        
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        # All calls fail
        mock_client.models.generate_content.side_effect = Exception("Persistent error")
        
        result = generate_image("A test prompt")
        
        assert result == b""
        # Should retry 5 times
        assert mock_client.models.generate_content.call_count == 5

    def _create_successful_response(self):
        """Helper to create a successful mock response."""
        mock_response = MagicMock()
        mock_part = MagicMock()
        mock_part.inline_data = MagicMock()
        mock_part.inline_data.data = b"image_data_bytes"
        mock_response.parts = [mock_part]
        return mock_response


class TestGenerateImagePrompt:
    """Tests for the generate_image_prompt function."""

    @patch('app.services.image_generator.time.sleep')
    @patch('app.services.image_generator.genai.Client')
    @patch('app.services.image_generator.config.load_google_api_key')
    def test_successful_prompt_generation(self, mock_load_key, mock_client_class, mock_sleep):
        """Test successful image prompt generation."""
        mock_load_key.return_value = "test-key"
        
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        mock_response = MagicMock()
        mock_response.text = "A detailed image prompt for the article"
        mock_client.models.generate_content.return_value = mock_response
        
        article = SingleArticle(ueberschrift="Test Article", inhalt="Test content")
        result = generate_image_prompt(article)
        
        assert result == "A detailed image prompt for the article"

    @patch('app.services.image_generator.time.sleep')
    @patch('app.services.image_generator.genai.Client')
    @patch('app.services.image_generator.config.load_google_api_key')
    def test_retries_on_empty_response(self, mock_load_key, mock_client_class, mock_sleep):
        """Test that generate_image_prompt retries on empty response."""
        mock_load_key.return_value = "test-key"
        
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        # First 2 return empty, 3rd succeeds
        empty_response = MagicMock()
        empty_response.text = ""
        success_response = MagicMock()
        success_response.text = "Final prompt"
        
        mock_client.models.generate_content.side_effect = [
            empty_response,
            empty_response,
            success_response
        ]
        
        article = SingleArticle(ueberschrift="Test Article", inhalt="Test content")
        result = generate_image_prompt(article)
        
        assert result == "Final prompt"
        assert mock_client.models.generate_content.call_count == 3

    @patch('app.services.image_generator.time.sleep')
    @patch('app.services.image_generator.genai.Client')
    @patch('app.services.image_generator.config.load_google_api_key')
    def test_returns_empty_after_max_retries(self, mock_load_key, mock_client_class, mock_sleep):
        """Test that generate_image_prompt returns empty string after max retries."""
        mock_load_key.return_value = "test-key"
        
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        # All calls fail
        mock_client.models.generate_content.side_effect = Exception("API Error")
        
        article = SingleArticle(ueberschrift="Test Article", inhalt="Test content")
        result = generate_image_prompt(article)
        
        assert result == ""
        assert mock_client.models.generate_content.call_count == 5
