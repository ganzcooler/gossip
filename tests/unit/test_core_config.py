"""
Unit tests for app/core/config.py
"""
import importlib

import pytest


class TestConfig:
    """Tests for configuration module."""

    def test_load_openrouter_api_key_success(self, mock_env_vars):
        """Test successful loading of the OpenRouter API key."""
        from app.core import config

        api_key = config.load_openrouter_api_key()
        assert api_key == "test-api-key"

    def test_load_openrouter_api_key_missing(self, monkeypatch):
        """Test error when the OpenRouter API key is missing."""
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

        from app.core import config

        with pytest.raises(ValueError, match="OPENROUTER_API_KEY not found"):
            config.load_openrouter_api_key()

    def test_database_url_from_env(self, mock_env_vars):
        """Test that DATABASE_URL is loaded from environment."""
        from app.core import config

        importlib.reload(config)

        expected_url = "postgresql+asyncpg://test_user:test_password@localhost:5432/test_db"
        assert config.DATABASE_URL == expected_url

    def test_database_url_defaults(self, monkeypatch):
        """Test that DATABASE_URL uses defaults when env vars not set."""
        for key in ["DATABASE_URL", "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"]:
            monkeypatch.delenv(key, raising=False)

        from app.core import config

        importlib.reload(config)

        assert "postgresql+asyncpg://" in config.DATABASE_URL
        assert "postgres" in config.DATABASE_URL

    def test_sessionnet_base_url_default(self, mock_env_vars):
        """Test SessionNet base URL from the environment."""
        from app.core import config

        importlib.reload(config)

        assert config.SESSIONNET_BASE_URL == "https://test.sessionnet.example/"

    def test_sessionnet_base_url_fallback(self, monkeypatch):
        """Test fallback SessionNet base URL when not in env."""
        monkeypatch.delenv("SESSIONNET_BASE_URL", raising=False)

        from app.core import config

        importlib.reload(config)

        assert "sessionnet.owl-it.de" in config.SESSIONNET_BASE_URL

    def test_traefik_host_config(self, mock_env_vars):
        """Test Traefik host configuration."""
        from app.core import config

        importlib.reload(config)

        assert config.TRAEFIK_HOST == "test.localhost"

    def test_log_level_config(self, mock_env_vars):
        """Test log level configuration."""
        from app.core import config

        importlib.reload(config)

        assert config.LOG_LEVEL == "DEBUG"

    def test_model_names_configured(self, mock_env_vars):
        """Test that the OpenRouter model names are configured."""
        from app.core import config

        importlib.reload(config)

        assert config.OPENROUTER_TEXT_MODEL == "deepseek/deepseek-v4.1-flash-1017"
        assert config.OPENROUTER_IMAGE_MODEL == "bytedance-seed/seedream-5-0-flash"
        assert config.OPENROUTER_REASONING_EFFORT == "max"
        assert config.OPENROUTER_BASE_URL == "https://openrouter.ai/api/v1"

    def test_model_names_can_be_overridden(self, monkeypatch):
        """Test that model names can be overridden by environment variables."""
        monkeypatch.setenv("OPENROUTER_TEXT_MODEL", "custom/text-model")
        monkeypatch.setenv("OPENROUTER_IMAGE_MODEL", "custom/image-model")
        monkeypatch.setenv("OPENROUTER_REASONING_EFFORT", "high")

        from app.core import config

        importlib.reload(config)

        assert config.OPENROUTER_TEXT_MODEL == "custom/text-model"
        assert config.OPENROUTER_IMAGE_MODEL == "custom/image-model"
        assert config.OPENROUTER_REASONING_EFFORT == "high"

    def test_image_artifact_threshold_defaults(self, monkeypatch):
        """Test the calibrated per-question artifact thresholds."""
        for name in (
            "IMAGE_ARTIFACT_BORDER_OR_BLANK_AREA_THRESHOLD",
            "IMAGE_ARTIFACT_PANEL_OR_SEAM_THRESHOLD",
            "IMAGE_ARTIFACT_WATERMARK_OR_OVERLAY_THRESHOLD",
            "IMAGE_ARTIFACT_ROTATION_THRESHOLD",
            "IMAGE_ARTIFACT_MINOR_THRESHOLD",
        ):
            monkeypatch.delenv(name, raising=False)

        from app.core import config

        importlib.reload(config)

        assert config.IMAGE_ARTIFACT_THRESHOLDS == {
            "border_or_blank_area": 0.5,
            "panel_or_seam": 0.5,
            "watermark_or_overlay": 0.8,
            "rotation": 0.6,
            "minor": 0.5,
        }

    def test_image_artifact_thresholds_can_be_overridden(self, monkeypatch):
        """Test every artifact threshold can be raised or lowered by ENV."""
        monkeypatch.setenv("IMAGE_ARTIFACT_BORDER_OR_BLANK_AREA_THRESHOLD", "0.7")
        monkeypatch.setenv("IMAGE_ARTIFACT_WATERMARK_OR_OVERLAY_THRESHOLD", "0.8")

        from app.core import config

        importlib.reload(config)

        assert config.IMAGE_ARTIFACT_THRESHOLDS["border_or_blank_area"] == 0.7
        assert config.IMAGE_ARTIFACT_THRESHOLDS["watermark_or_overlay"] == 0.8
        assert config.IMAGE_ARTIFACT_THRESHOLDS["panel_or_seam"] == 0.5

    def test_image_artifact_threshold_must_be_a_probability(self, monkeypatch):
        """Test invalid thresholds fail at configuration load time."""
        monkeypatch.setenv("IMAGE_ARTIFACT_BORDER_OR_BLANK_AREA_THRESHOLD", "1.5")

        from app.core import config

        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            importlib.reload(config)

        monkeypatch.delenv("IMAGE_ARTIFACT_BORDER_OR_BLANK_AREA_THRESHOLD")
        importlib.reload(config)

    def test_api_call_delay_configured(self, mock_env_vars):
        """Test API call delay is configured."""
        from app.core import config

        assert config.API_CALL_DELAY_SECONDS == 1

    def test_directory_paths(self, mock_env_vars):
        """Test directory path configurations."""
        from app.core import config

        importlib.reload(config)

        assert str(config.ARTICLES_DIR).replace("\\", "/").endswith("/app/articles")
        assert str(config.LOGS_DIR).replace("\\", "/").endswith("/app/logs")
