"""
Unit tests for app/services/short_article_generator.py
"""
import pytest
from unittest.mock import MagicMock, patch

from app.services.short_article_generator import (
    generate_short_article,
    _strip_html_tags,
    _get_text_length_without_html,
    _shorten_article,
)


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
            mock_prompts.SHORT_ARTICLE_RETRY_PROMPT = "Retry prompt: {short_article}"
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
        """Test that temperature starts at 1.0 and decays on retries."""
        # First call returns too long article, retry succeeds
        mock_response_long = MagicMock()
        mock_response_long.text = "<h2>Title</h2><p>" + "a" * 500 + "</p>"  # Too long

        mock_response_short = MagicMock()
        mock_response_short.text = "<h2>Title</h2><p>Short article.</p>"

        mock_genai_client.models.generate_content.side_effect = [
            mock_response_long,  # First attempt - too long, shortening fails
            mock_response_short,  # Second attempt with lower temperature
        ]

        article_title = "Test Article"
        article_content = "<p>Test content</p>"

        generate_short_article(article_title, article_content)

        # Verify temperature decays on retry
        calls = mock_genai_client.models.generate_content.call_args_list
        assert len(calls) == 2
        # First call: temperature = 1.0
        assert calls[0].kwargs["config"].temperature == 1.0
        # Second call: temperature = 0.85 (1.0 - 0.15)
        assert calls[1].kwargs["config"].temperature == 0.85


class TestStripHtmlTags:
    """Tests for _strip_html_tags function."""

    def test_strip_simple_tags(self):
        """Test stripping simple HTML tags."""
        html = "<h2>Title</h2><p>Content here</p>"
        result = _strip_html_tags(html)
        assert result == "TitleContent here"

    def test_strip_nested_tags(self):
        """Test stripping nested HTML tags."""
        html = "<div><p><strong>Bold</strong> and <em>italic</em></p></div>"
        result = _strip_html_tags(html)
        assert result == "Bold and italic"

    def test_strip_self_closing_tags(self):
        """Test stripping self-closing tags."""
        html = "Line one<br/>Line two<hr/>Line three"
        result = _strip_html_tags(html)
        assert result == "Line oneLine twoLine three"

    def test_strip_no_tags(self):
        """Test text without HTML tags."""
        html = "Plain text without any tags"
        result = _strip_html_tags(html)
        assert result == "Plain text without any tags"

    def test_strip_empty_string(self):
        """Test stripping empty string."""
        result = _strip_html_tags("")
        assert result == ""

    def test_strip_tags_with_attributes(self):
        """Test stripping tags with attributes."""
        html = '<p class="text-bold" id="main">Content</p>'
        result = _strip_html_tags(html)
        assert result == "Content"


class TestGetTextLengthWithoutHtml:
    """Tests for _get_text_length_without_html function."""

    def test_length_without_html(self):
        """Test calculating length without HTML tags."""
        html = "<h2>Title</h2><p>Content here</p>"
        result = _get_text_length_without_html(html)
        assert result == len("TitleContent here")

    def test_length_empty_html(self):
        """Test calculating length of empty HTML."""
        result = _get_text_length_without_html("")
        assert result == 0

    def test_length_html_only(self):
        """Test calculating length of HTML with no text content."""
        html = "<br/><hr/><img src='test.jpg'/>"
        result = _get_text_length_without_html(html)
        assert result == 0

    def test_length_with_special_chars(self):
        """Test calculating length with special characters and unicode."""
        html = "<p>Hellö Wörld! 🎉</p>"
        result = _get_text_length_without_html(html)
        assert result == len("Hellö Wörld! 🎉")


class TestShortenArticle:
    """Tests for _shorten_article function."""

    @pytest.fixture
    def mock_shorten_config(self):
        """Fixture to mock configuration for shortening."""
        with patch("app.services.short_article_generator.config") as mock_config:
            mock_config.GENAI_CLASSIFICATION_MODEL = "gemini-2.5-flash-lite"
            mock_config.API_CALL_DELAY_SECONDS = 0  # Speed up tests
            yield mock_config

    @pytest.fixture
    def mock_shorten_prompts(self):
        """Fixture to mock prompts for shortening."""
        with patch("app.services.short_article_generator.prompts") as mock_prompts:
            mock_prompts.SHORT_ARTICLE_RETRY_PROMPT = "Retry: {short_article}"
            yield mock_prompts

    def test_shorten_article_success(self, mock_shorten_config, mock_shorten_prompts):
        """Test successful article shortening."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "<h2>Short</h2><p>Shortened content.</p>"
        mock_client.models.generate_content.return_value = mock_response

        long_article = "<h2>Long Title</h2><p>" + "a" * 500 + "</p>"
        result = _shorten_article(mock_client, long_article, "Test Article")

        assert result is not None
        assert "Shortened content" in result
        mock_client.models.generate_content.assert_called_once()

    def test_shorten_article_still_too_long(self, mock_shorten_config, mock_shorten_prompts):
        """Test shortening when result is still too long triggers retry."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        # Return content that's still too long twice, then acceptable
        mock_response.text = "<h2>Title</h2><p>" + "b" * 500 + "</p>"
        mock_client.models.generate_content.return_value = mock_response

        long_article = "<h2>Long Title</h2><p>" + "a" * 500 + "</p>"
        result = _shorten_article(mock_client, long_article, "Test Article")

        # Should retry 3 times then give up
        assert result is None
        assert mock_client.models.generate_content.call_count == 3

    def test_shorten_article_empty_response(self, mock_shorten_config, mock_shorten_prompts):
        """Test handling of empty response during shortening."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = None
        mock_client.models.generate_content.return_value = mock_response

        long_article = "<h2>Long Title</h2><p>Content</p>"
        result = _shorten_article(mock_client, long_article, "Test Article")

        assert result is None
        assert mock_client.models.generate_content.call_count == 3  # Retries

    def test_shorten_article_exception(self, mock_shorten_config, mock_shorten_prompts):
        """Test handling of exception during shortening."""
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("API Error")

        long_article = "<h2>Long Title</h2><p>Content</p>"
        result = _shorten_article(mock_client, long_article, "Test Article")

        assert result is None
        assert mock_client.models.generate_content.call_count == 3  # Retries

    def test_shorten_article_progressive_shortening(self, mock_shorten_config, mock_shorten_prompts):
        """Test that progressively shorter inputs are used on each retry."""
        mock_client = MagicMock()

        # First attempt returns something, second returns final short version
        response1 = MagicMock()
        response1.text = "<h2>Med</h2><p>" + "c" * 400 + "</p>"  # Still too long
        response2 = MagicMock()
        response2.text = "<h2>Short</h2><p>Final.</p>"

        mock_client.models.generate_content.side_effect = [response1, response2]

        long_article = "<h2>Long</h2><p>" + "a" * 500 + "</p>"
        result = _shorten_article(mock_client, long_article, "Test Article")

        assert result is not None
        # Verify second call used the output from first call
        calls = mock_client.models.generate_content.call_args_list
        assert len(calls) == 2


class TestLengthValidationRetryFlow:
    """Tests for length validation and retry flow in generate_short_article."""

    def test_accept_article_within_limit(self, mock_genai_client, mock_config, mock_prompts):
        """Test that article within limit is accepted without shortening."""
        mock_response = MagicMock()
        mock_response.text = "<h2>Title</h2><p>Short enough content.</p>"
        mock_genai_client.models.generate_content.return_value = mock_response

        article_title = "Test Article"
        article_content = "<p>Test content</p>"

        result = generate_short_article(article_title, article_content)

        assert result is not None
        # Should only call generate_content once (no shortening needed)
        assert mock_genai_client.models.generate_content.call_count == 1

    def test_shorten_article_too_long_success(self, mock_genai_client, mock_config, mock_prompts):
        """Test that too-long article triggers shortening and succeeds."""
        # First generate_content returns too-long article
        response_long = MagicMock()
        response_long.text = "<h2>Title</h2><p>" + "a" * 500 + "</p>"

        # Second generate_content (in _shorten_article) returns acceptable length
        response_short = MagicMock()
        response_short.text = "<h2>Title</h2><p>Shortened.</p>"

        mock_genai_client.models.generate_content.side_effect = [
            response_long,  # Initial generation
            response_short,  # Shortening attempt
        ]

        article_title = "Test Article"
        article_content = "<p>Test content</p>"

        result = generate_short_article(article_title, article_content)

        assert result is not None
        assert result == "<h2>Title</h2><p>Shortened.</p>"
        assert mock_genai_client.models.generate_content.call_count == 2

    def test_shorten_article_too_long_failure_triggers_regeneration(self, mock_genai_client, mock_config, mock_prompts):
        """Test that failed shortening triggers regeneration with lower temperature."""
        # First attempt: too long, shortening fails
        response_long1 = MagicMock()
        response_long1.text = "<h2>Title1</h2><p>" + "a" * 500 + "</p>"

        # Shortening attempts all return too-long content
        response_short_fail = MagicMock()
        response_short_fail.text = "<h2>Title</h2><p>" + "b" * 500 + "</p>"

        # Second full generation: success
        response_success = MagicMock()
        response_success.text = "<h2>Title2</h2><p>Short enough.</p>"

        mock_genai_client.models.generate_content.side_effect = [
            response_long1,      # First generation - too long
            response_short_fail,  # Shortening retry 1
            response_short_fail,  # Shortening retry 2
            response_short_fail,  # Shortening retry 3
            response_success,    # Second full generation - success
        ]

        article_title = "Test Article"
        article_content = "<p>Test content</p>"

        result = generate_short_article(article_title, article_content)

        assert result is not None
        assert result == "<h2>Title2</h2><p>Short enough.</p>"
        # Verify temperature is lower on retry
        calls = mock_genai_client.models.generate_content.call_args_list
        # First generation: temp = 1.0
        assert calls[0].kwargs["config"].temperature == 1.0
        # Second generation: temp = 0.85
        assert calls[4].kwargs["config"].temperature == 0.85
