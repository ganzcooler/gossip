"""
Unit tests for app/core/config.py
"""
import pytest
from unittest.mock import patch, MagicMock
import os


class TestConfig:
    """Tests for configuration module."""

    def test_load_google_api_key_success(self, mock_env_vars):
        """Test successful loading of Google API key."""
        # Must reimport after setting env vars
        from app.core import config
        
        api_key = config.load_google_api_key()
        assert api_key == "test-api-key"

    def test_load_google_api_key_missing(self, monkeypatch):
        """Test error when Google API key is missing."""
        # Remove the API key from environment
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        
        from app.core import config
        
        with pytest.raises(ValueError, match="GOOGLE_API_KEY not found"):
            config.load_google_api_key()

    def test_database_url_from_env(self, mock_env_vars):
        """Test that DATABASE_URL is loaded from environment."""
        import importlib
        from app.core import config
        
        # Reload to pick up mocked env vars
        importlib.reload(config)
        
        expected_url = "postgresql+asyncpg://test_user:test_password@localhost:5432/test_db"
        assert config.DATABASE_URL == expected_url

    def test_database_url_defaults(self, monkeypatch):
        """Test that DATABASE_URL uses defaults when env vars not set."""
        # Clear all database-related env vars
        for key in ["DATABASE_URL", "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"]:
            monkeypatch.delenv(key, raising=False)
        
        # Reimport to get fresh defaults
        import importlib
        from app.core import config
        importlib.reload(config)
        
        assert "postgresql+asyncpg://" in config.DATABASE_URL
        assert "postgres" in config.DATABASE_URL

    def test_sessionnet_base_url_default(self, mock_env_vars):
        """Test default SessionNet base URL."""
        import importlib
        from app.core import config
        
        # Reload to pick up mocked env vars
        importlib.reload(config)
        
        # When env var is set in fixture
        assert config.SESSIONNET_BASE_URL == "https://test.sessionnet.example/"

    def test_sessionnet_base_url_fallback(self, monkeypatch):
        """Test fallback SessionNet base URL when not in env."""
        monkeypatch.delenv("SESSIONNET_BASE_URL", raising=False)
        
        import importlib
        from app.core import config
        importlib.reload(config)
        
        assert "sessionnet.owl-it.de" in config.SESSIONNET_BASE_URL

    def test_traefik_host_config(self, mock_env_vars):
        """Test Traefik host configuration."""
        import importlib
        from app.core import config
        
        # Reload to pick up mocked env vars
        importlib.reload(config)
        
        assert config.TRAEFIK_HOST == "test.localhost"

    def test_log_level_config(self, mock_env_vars):
        """Test log level configuration."""
        import importlib
        from app.core import config
        
        # Reload to pick up mocked env vars
        importlib.reload(config)
        
        assert config.LOG_LEVEL == "DEBUG"

    def test_model_names_configured(self, mock_env_vars):
        """Test that AI model names are configured."""
        from app.core import config
        
        assert config.GENAI_ARTICLE_GENERATION_MODEL == "gemini-3.5-flash"
        assert config.GENAI_IMAGE_PROMPT_MODEL == "gemini-2.5-flash"
        assert config.GENAI_IMAGE_GENERATION_MODEL == "gemini-2.5-flash-image"

    def test_api_call_delay_configured(self, mock_env_vars):
        """Test API call delay is configured."""
        from app.core import config
        
        assert config.API_CALL_DELAY_SECONDS == 1

    def test_directory_paths(self, mock_env_vars):
        """Test directory path configurations."""
        import importlib
        from app.core import config
        from pathlib import Path
        
        # Reload to pick up mocked env vars
        importlib.reload(config)
        
        # Check paths end with expected values (platform-independent)
        assert str(config.ARTICLES_DIR).replace("\\", "/").endswith("/app/articles")
        assert str(config.LOGS_DIR).replace("\\", "/").endswith("/app/logs")