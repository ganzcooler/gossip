import pytest
from unittest.mock import MagicMock, patch

from app.services.caption_generator import generate_insta_caption


class TestGenerateInstaCaption:
    """Tests for generate_insta_caption function."""

    @pytest.fixture
    def mock_genai_client(self):
        with patch("app.services.caption_generator.genai.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            yield mock_client

    @pytest.fixture
    def mock_config(self):
        with patch("app.services.caption_generator.config") as mock_config:
            mock_config.load_google_api_key.return_value = "test-api-key"
            mock_config.GENAI_IMAGE_PROMPT_MODEL = "gemini-2.5-flash"
            mock_config.API_CALL_DELAY_SECONDS = 0
            yield mock_config

    @pytest.fixture
    def mock_prompts(self):
        with patch("app.services.caption_generator.prompts") as mock_prompts:
            mock_prompts.INSTA_CAPTION_PROMPT = "Caption prompt: {complete_article}"
            yield mock_prompts

    def test_successful_caption_generation(self, mock_genai_client, mock_config, mock_prompts):
        mock_response = MagicMock()
        mock_response.text = "Spannende Neuigkeiten aus dem Gemeinderat! #Kommunalpolitik #Rosdorf"
        mock_genai_client.models.generate_content.return_value = mock_response

        article_title = "New Community Center Opens"
        article_content = "<h2>Grand Opening</h2><p>The new community center opened yesterday.</p>"

        result = generate_insta_caption(article_title, article_content)

        assert result is not None
        assert "Spannende Neuigkeiten" in result
        assert "#Rosdorf" in result
        mock_genai_client.models.generate_content.assert_called_once()

    def test_caption_generation_with_empty_response(self, mock_genai_client, mock_config, mock_prompts):
        mock_response = MagicMock()
        mock_response.text = None
        mock_genai_client.models.generate_content.return_value = mock_response

        article_title = "Test Article"
        article_content = "<p>Test content</p>"

        result = generate_insta_caption(article_title, article_content)

        assert result is None
        assert mock_genai_client.models.generate_content.call_count == 5

    def test_caption_generation_with_exception(self, mock_genai_client, mock_config, mock_prompts):
        mock_genai_client.models.generate_content.side_effect = Exception("API Error")

        article_title = "Test Article"
        article_content = "<p>Test content</p>"

        result = generate_insta_caption(article_title, article_content)

        assert result is None
        assert mock_genai_client.models.generate_content.call_count == 5

    def test_caption_generation_strips_whitespace(self, mock_genai_client, mock_config, mock_prompts):
        mock_response = MagicMock()
        mock_response.text = "  \n  Wichtige Entscheidung im Rat gefallen! #Gemeinderat #Rosdorf  \n  "
        mock_genai_client.models.generate_content.return_value = mock_response

        article_title = "Test Article"
        article_content = "<p>Test content</p>"

        result = generate_insta_caption(article_title, article_content)

        assert result == "Wichtige Entscheidung im Rat gefallen! #Gemeinderat #Rosdorf"
        assert not result.startswith(" ")
        assert not result.endswith(" ")

    def test_caption_generation_with_long_content(self, mock_genai_client, mock_config, mock_prompts):
        mock_response = MagicMock()
        mock_response.text = "Neue Entwicklung im Bauausschuss! #Bauprojekte #Rosdorf"
        mock_genai_client.models.generate_content.return_value = mock_response

        article_title = "Council Approves New Budget"
        article_content = "<h2>Budget Discussion</h2><p>" + "Lorem ipsum dolor sit amet. " * 100 + "</p>"

        result = generate_insta_caption(article_title, article_content)

        assert result is not None
        assert "Bauausschuss" in result

    def test_success_on_retry(self, mock_genai_client, mock_config, mock_prompts):
        mock_response_success = MagicMock()
        mock_response_success.text = "Erfolg nach mehreren Versuchen! #Rosdorf"

        mock_genai_client.models.generate_content.side_effect = [
            Exception("API Error 1"),
            Exception("API Error 2"),
            mock_response_success,
        ]

        article_title = "Test Article"
        article_content = "<p>Test content</p>"

        result = generate_insta_caption(article_title, article_content)

        assert result == "Erfolg nach mehreren Versuchen! #Rosdorf"
        assert mock_genai_client.models.generate_content.call_count == 3

    def test_api_key_loaded_from_config(self, mock_genai_client, mock_config, mock_prompts):
        mock_response = MagicMock()
        mock_response.text = "Test caption #Rosdorf"
        mock_genai_client.models.generate_content.return_value = mock_response

        article_title = "Test Article"
        article_content = "<p>Test content</p>"

        generate_insta_caption(article_title, article_content)

        mock_config.load_google_api_key.assert_called_once()

    def test_prompt_formatting(self, mock_genai_client, mock_config, mock_prompts):
        mock_response = MagicMock()
        mock_response.text = "Test caption #Rosdorf"
        mock_genai_client.models.generate_content.return_value = mock_response

        article_title = "Test Article"
        article_content = "<p>Article content here</p>"

        generate_insta_caption(article_title, article_content)

        call_args = mock_genai_client.models.generate_content.call_args
        assert "contents" in call_args.kwargs
        assert article_content in call_args.kwargs["contents"]

    def test_temperature_config(self, mock_genai_client, mock_config, mock_prompts):
        mock_response = MagicMock()
        mock_response.text = "Test caption #Rosdorf"
        mock_genai_client.models.generate_content.return_value = mock_response

        article_title = "Test Article"
        article_content = "<p>Test content</p>"

        generate_insta_caption(article_title, article_content)

        calls = mock_genai_client.models.generate_content.call_args_list
        assert len(calls) == 1
        assert calls[0].kwargs["config"].temperature == 1
