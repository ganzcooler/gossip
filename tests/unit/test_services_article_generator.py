"""
Unit tests for app/services/article_generator.py
"""
import pytest
from unittest.mock import MagicMock, patch

from app.services.article_generator import (
    generate_articles,
    _is_auth_error,
)
from app.services import AuthenticationError, ArticleGenerationError


class TestIsAuthError:
    """Tests for the _is_auth_error helper function."""

    def test_detects_status_401(self):
        """Test that exception with status 401 is detected as auth error."""
        exc = MagicMock()
        exc.status = 401
        exc.code = None
        assert _is_auth_error(exc) is True

    def test_detects_status_403(self):
        """Test that exception with status 403 is detected as auth error."""
        exc = MagicMock()
        exc.status = 403
        exc.code = None
        assert _is_auth_error(exc) is True

    def test_detects_code_401(self):
        """Test that exception with code 401 is detected as auth error."""
        exc = MagicMock()
        exc.status = None
        exc.code = 401
        assert _is_auth_error(exc) is True

    def test_detects_code_403(self):
        """Test that exception with code 403 is detected as auth error."""
        exc = MagicMock()
        exc.status = None
        exc.code = 403
        assert _is_auth_error(exc) is True

    def test_detects_unauthorized_in_message(self):
        """Test that 'unauthorized' in message is detected as auth error."""
        exc = Exception("Request failed: unauthorized")
        assert _is_auth_error(exc) is True

    def test_detects_forbidden_in_message(self):
        """Test that 'forbidden' in message is detected as auth error."""
        exc = Exception("Access forbidden")
        assert _is_auth_error(exc) is True

    def test_detects_api_key_in_message(self):
        """Test that 'api key' in message is detected as auth error."""
        exc = Exception("Invalid API key provided")
        assert _is_auth_error(exc) is True

    def test_detects_authentication_in_message(self):
        """Test that 'authentication' in message is detected as auth error."""
        exc = Exception("Authentication failed")
        assert _is_auth_error(exc) is True

    def test_detects_permission_denied_in_message(self):
        """Test that 'permission denied' in message is detected as auth error."""
        exc = Exception("Permission denied for this resource")
        assert _is_auth_error(exc) is True

    def test_non_auth_error_returns_false(self):
        """Test that non-auth errors are not detected as auth errors."""
        exc = Exception("Network timeout")
        assert _is_auth_error(exc) is False

    def test_rate_limit_error_returns_false(self):
        """Test that rate limit errors are not detected as auth errors."""
        exc = MagicMock()
        exc.status = 429
        exc.code = None
        assert _is_auth_error(exc) is False


class TestGenerateArticlesAuthError:
    """Tests for AuthenticationError handling in generate_articles."""

    @patch('app.services.article_generator.genai.Client')
    @patch('app.services.article_generator.config.load_google_api_key')
    def test_auth_error_raises_immediately_no_retries(self, mock_load_key, mock_client_class):
        """Test that auth errors raise immediately without retries."""
        mock_load_key.return_value = "test-api-key"

        # Create a mock client that raises an auth error
        mock_client = MagicMock()
        error = Exception("Unauthorized: Invalid API key")
        error.status = 401
        mock_client.models.generate_content.side_effect = error
        mock_client_class.return_value = mock_client

        # Should raise AuthenticationError immediately (no retries)
        with pytest.raises(AuthenticationError):
            generate_articles("Some protocol text")

        # Should only be called once (no retries for auth errors)
        assert mock_client.models.generate_content.call_count == 1

    @patch('app.services.article_generator.genai.Client')
    @patch('app.services.article_generator.config.load_google_api_key')
    def test_auth_error_with_status_403(self, mock_load_key, mock_client_class):
        """Test that 403 errors raise AuthenticationError immediately."""
        mock_load_key.return_value = "test-api-key"

        mock_client = MagicMock()
        error = Exception("Forbidden")
        error.status = 403
        mock_client.models.generate_content.side_effect = error
        mock_client_class.return_value = mock_client

        with pytest.raises(AuthenticationError):
            generate_articles("Some protocol text")

        assert mock_client.models.generate_content.call_count == 1

    @patch('app.services.article_generator.time.sleep')
    @patch('app.services.article_generator.genai.Client')
    @patch('app.services.article_generator.config.load_google_api_key')
    def test_non_auth_error_retries(self, mock_load_key, mock_client_class, mock_sleep):
        """Test that non-auth errors are retried."""
        from app.core.models import LLMGeneratedArticles, SingleArticle

        mock_load_key.return_value = "test-api-key"

        mock_client = MagicMock()
        # First 2 calls fail with network error, 3rd succeeds
        error = Exception("Network timeout")
        error.status = 500

        # Create proper LLMGeneratedArticles instance for successful response
        article = SingleArticle(ueberschrift="Test", inhalt="Content")
        parsed_response = LLMGeneratedArticles(artikel=[article])
        mock_response = MagicMock()
        mock_response.parsed = parsed_response

        mock_client.models.generate_content.side_effect = [error, error, mock_response]
        mock_client_class.return_value = mock_client

        # Should complete without raising
        result = generate_articles("Some protocol text")

        # Should retry (called 3 times)
        assert mock_client.models.generate_content.call_count == 3
        assert len(result) == 1

    @patch('app.services.article_generator.time.sleep')
    @patch('app.services.article_generator.genai.Client')
    @patch('app.services.article_generator.config.load_google_api_key')
    def test_non_auth_error_raises_after_max_retries(self, mock_load_key, mock_client_class, mock_sleep):
        """Test that non-auth errors raise ArticleGenerationError after max retries."""
        mock_load_key.return_value = "test-api-key"

        mock_client = MagicMock()
        error = Exception("Server error")
        error.status = 500
        mock_client.models.generate_content.side_effect = error
        mock_client_class.return_value = mock_client

        # Should raise ArticleGenerationError after retries
        with pytest.raises(ArticleGenerationError):
            generate_articles("Some protocol text")

        # Should retry 3 times (max_retries)
        assert mock_client.models.generate_content.call_count == 3
