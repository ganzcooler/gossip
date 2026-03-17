"""
Unit tests for app/services/short_article_generator.py
"""
import pytest
from unittest.mock import MagicMock, patch

from app.services.short_article_generator import generate_short_article


class TestGenerateShortArticle:
    """Tests for generate_short_article function."""

    @pytest.fixture
    def mock_genai_client(self):
        """Fixture to create a mock GenAI client."""
        with patch("app.services.short_article_generator.genai.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            yield mock_client

    @pytest.fixture
    def mock_config(self):
        """Fixture to mock configuration."""
        with patch("app.services.short_article_generator.config") as mock_config:
            mock_config.load_google_api_key.return_value = "test-api-key"
            mock_config.GENAI_IMAGE_PROMPT_MODEL = "gemini-2.5-flash"
            mock_config.API_CALL_DELAY_SECONDS = 0  # Speed up tests
            yield mock_config

    @pytest.fixture
    def mock_prompts(self):
        """Fixture to mock prompts module."""
        with patch("app.services.short_article_generator.prompts") as mock_prompts:
            mock_prompts.SHORT_ARTICLE_PROMPT = "Short article prompt: {complete_article}"
            yield mock_prompts

    def test_successful_short_article_generation(self, mock_genai_client, mock_config, mock_prompts):
        """Test successful short article generation."""
        # Mock the response
        mock_response = MagicMock()
        mock_response.text = "Check out this amazing news about our local council! #localnews #community"
        mock_genai_client.models.generate_content.return_value = mock_response

        article_title = "New Community Center Opens"
        article_content = "<h2>Grand Opening</h2><p>The new community center opened yesterday with a big celebration.</p>"

        result = generate_short_article(article_title, article_content)

        assert result is not None
        assert "Check out this amazing news" in result
        assert "#localnews" in result
        mock_genai_client.models.generate_content.assert_called_once()

    def test_short_article_generation_with_empty_response(self, mock_genai_client, mock_config, mock_prompts):
        """Test handling when AI returns empty response."""
        # Mock empty response
        mock_response = MagicMock()
        mock_response.text = None
        mock_genai_client.models.generate_content.return_value = mock_response

        article_title = "Test Article"
        article_content = "<p>Test content</p>"

        result = generate_short_article(article_title, article_content)

        assert result is None
        # Should retry 5 times
        assert mock_genai_client.models.generate_content.call_count == 5

    def test_short_article_generation_with_empty_string_response(self, mock_genai_client, mock_config, mock_prompts):
        """Test handling when AI returns empty string."""
        # Mock empty string response
        mock_response = MagicMock()
        mock_response.text = "   "
        mock_genai_client.models.generate_content.return_value = mock_response

        article_title = "Test Article"
        article_content = "<p>Test content</p>"

        result = generate_short_article(article_title, article_content)

        # When response.text has only whitespace, strip() returns empty string
        # The code checks `if response.text:` before strip(), so whitespace is processed
        assert result == ""

    def test_short_article_generation_with_exception(self, mock_genai_client, mock_config, mock_prompts):
        """Test error handling when AI generation raises exception."""
        # Mock exception
        mock_genai_client.models.generate_content.side_effect = Exception("API Error")

        article_title = "Test Article"
        article_content = "<p>Test content</p>"

        result = generate_short_article(article_title, article_content)

        assert result is None
        # Should retry 5 times
        assert mock_genai_client.models.generate_content.call_count == 5

    def test_short_article_generation_strips_whitespace(self, mock_genai_client, mock_config, mock_prompts):
        """Test that generated short article has whitespace stripped."""
        # Mock response with leading/trailing whitespace
        mock_response = MagicMock()
        mock_response.text = "  \n  Short article with whitespace  \n  "
        mock_genai_client.models.generate_content.return_value = mock_response

        article_title = "Test Article"
        article_content = "<p>Test content</p>"

        result = generate_short_article(article_title, article_content)

        assert result == "Short article with whitespace"
        assert not result.startswith(" ")
        assert not result.endswith(" ")

    def test_short_article_generation_with_long_content(self, mock_genai_client, mock_config, mock_prompts):
        """Test short article generation with long article content."""
        mock_response = MagicMock()
        mock_response.text = "Breaking news from the council meeting! #politics"
        mock_genai_client.models.generate_content.return_value = mock_response

        article_title = "Council Approves New Budget"
        article_content = "<h2>Budget Discussion</h2><p>" + "Lorem ipsum dolor sit amet. " * 100 + "</p>"

        result = generate_short_article(article_title, article_content)

        assert result is not None
        assert "Breaking news" in result

    def test_short_article_generation_with_special_characters(self, mock_genai_client, mock_config, mock_prompts):
        """Test short article generation with special characters in content."""
        mock_response = MagicMock()
        mock_response.text = "Special announcement! 🎉 #news"
        mock_genai_client.models.generate_content.return_value = mock_response

        article_title = "Special Announcement"
        article_content = "<h2>Überschrift mit Umlauten</h2><p>Content with ß, ä, ö, ü and emojis 🎉</p>"

        result = generate_short_article(article_title, article_content)

        assert result is not None
        assert "🎉" in result

    def test_success_on_retry(self, mock_genai_client, mock_config, mock_prompts):
        """Test that function succeeds on a retry after initial failures."""
        # First two calls fail, third succeeds
        mock_response_success = MagicMock()
        mock_response_success.text = "Success after retries!"

        mock_genai_client.models.generate_content.side_effect = [
            Exception("API Error 1"),
            Exception("API Error 2"),
            mock_response_success,
        ]

        article_title = "Test Article"
        article_content = "<p>Test content</p>"

        result = generate_short_article(article_title, article_content)

        assert result == "Success after retries!"
        assert mock_genai_client.models.generate_content.call_count == 3

    def test_api_key_loaded_from_config(self, mock_genai_client, mock_config, mock_prompts):
        """Test that API key is loaded from config."""
        mock_response = MagicMock()
        mock_response.text = "Test short article"
        mock_genai_client.models.generate_content.return_value = mock_response

        article_title = "Test Article"
        article_content = "<p>Test content</p>"

        generate_short_article(article_title, article_content)

        # Verify API key was loaded
        mock_config.load_google_api_key.assert_called_once()

    def test_prompt_formatting(self, mock_genai_client, mock_config, mock_prompts):
        """Test that prompt is formatted correctly with article content."""
        mock_response = MagicMock()
        mock_response.text = "Test short article"
        mock_genai_client.models.generate_content.return_value = mock_response

        article_title = "Test Article"
        article_content = "<p>Article content here</p>"

        generate_short_article(article_title, article_content)

        # Verify prompt was formatted with article content
        call_args = mock_genai_client.models.generate_content.call_args
        assert "contents" in call_args.kwargs
        assert article_content in call_args.kwargs["contents"]

    def test_temperature_config(self, mock_genai_client, mock_config, mock_prompts):
        """Test that temperature is set in generation config."""
        mock_response = MagicMock()
        mock_response.text = "Test short article"
        mock_genai_client.models.generate_content.return_value = mock_response

        article_title = "Test Article"
        article_content = "<p>Test content</p>"

        generate_short_article(article_title, article_content)

        # Verify config was passed
        call_args = mock_genai_client.models.generate_content.call_args
        assert "config" in call_args.kwargs
        assert call_args.kwargs["config"].temperature == 1
