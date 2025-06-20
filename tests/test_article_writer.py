import unittest
from unittest.mock import patch, MagicMock, call
import pathlib
import sys
import logging

# Ensure src directory is in sys.path for module imports from src
PROJECT_ROOT_FOR_TEST = pathlib.Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT_FOR_TEST) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_FOR_TEST))

# Modules to test
from src.pipeline_steps import article_writer
from src.pipeline_steps import db_loader # To mock its initialize_chroma_collection
from src import config as app_config # To potentially mock config values if needed

from google.api_core import exceptions as google_exceptions # For testing LLM error handling

# Disable most logging for cleaner test output
# logging.disable(logging.CRITICAL) # Keep logging for debugging tests if needed, then disable


class TestSanitizeFilename(unittest.TestCase):
    """Test suite for the sanitize_filename utility."""

    def test_basic_sanitization(self):
        self.assertEqual(article_writer.sanitize_filename("Valid Name 123"), "Valid-Name-123")

    def test_special_characters(self):
        self.assertEqual(article_writer.sanitize_filename("File*Name?Special!Chars:"), "FileNameSpecialChars")

    def test_leading_trailing_hyphens_spaces(self):
        self.assertEqual(article_writer.sanitize_filename("-  File Name  -"), "File-Name")

    def test_multiple_spaces_hyphens(self):
        self.assertEqual(article_writer.sanitize_filename("File   ---   Name"), "File-Name")

    def test_empty_string(self):
        self.assertEqual(article_writer.sanitize_filename(""), "")

    def test_only_special_chars(self):
        self.assertEqual(article_writer.sanitize_filename("!@#$%^&*()"), "")

    def test_numbers_and_hyphens(self):
        self.assertEqual(article_writer.sanitize_filename("123-456-789"), "123-456-789")

    def test_mixed_case(self):
        self.assertEqual(article_writer.sanitize_filename("MixedCaseName"), "MixedCaseName")


class TestGenerateHTMLArticle(unittest.TestCase):
    """Test suite for the generate_html_article function."""

    def test_basic_html_generation(self):
        """Test basic HTML structure and content injection."""
        article_text = "This is the LLM generated article content." # Parameter name changed
        top_number = "T123"
        expected_title = f"<title>Journalistic Article (TOP: {top_number})</title>" # Title changed
        expected_header = f"<h1>Journalistic Article (Original TOP Number: {top_number})</h1>" # Header changed
        # Style for <pre> tag might have changed, check current implementation
        expected_body_content = f'<pre>{article_text}</pre>' # Content is now LLM output

        html_output = article_writer.generate_html_article(article_text, top_number)

        self.assertIn("<!DOCTYPE html>", html_output)
        self.assertIn("<html lang=\"en\">", html_output)
        self.assertIn("<head>", html_output)
        self.assertIn("</head>", html_output)
        self.assertIn("<body>", html_output)
        self.assertIn("</body>", html_output)
        self.assertIn(expected_title, html_output)
        self.assertIn(expected_header, html_output)
        self.assertIn(expected_body_content, html_output)
        # Check for style on <pre> or body as per implementation
        self.assertIn("white-space: pre-wrap;", html_output)

    def test_empty_content(self):
        """Test with empty article text."""
        article_text = "" # Parameter name changed
        top_number = "T000"
        expected_body_content = f'<pre>{article_text}</pre>' # Content is empty
        html_output = article_writer.generate_html_article(article_text, top_number)
        self.assertIn(expected_body_content, html_output)
        self.assertIn(f"<title>Journalistic Article (TOP: {top_number})</title>", html_output) # Title changed

    def test_content_with_special_chars(self):
        """Test with article text having HTML special characters."""
        article_text = "<p>Hello & Welcome!</p>" # Parameter name changed
        top_number = "T789"
        # <pre> tag behavior: content is typically rendered as-is by browsers, including interpreting HTML tags.
        expected_body_content = f'<pre>{article_text}</pre>'
        html_output = article_writer.generate_html_article(article_text, top_number)
        self.assertIn(expected_body_content, html_output)

    def test_default_top_number(self):
        """Test that 'N/A' is used if top_number is not provided."""
        article_text = "Some content." # Parameter name changed
        expected_title = "<title>Journalistic Article (TOP: N/A)</title>" # Title changed
        expected_header = "<h1>Journalistic Article (Original TOP Number: N/A)</h1>" # Header changed
        html_output = article_writer.generate_html_article(article_text) # Call without top_number
        self.assertIn(expected_title, html_output)
        self.assertIn(expected_header, html_output)


class TestGenerateJournalisticArticleLLM(unittest.TestCase):
    """Test suite for generate_journalistic_article_llm."""

    def test_successful_generation(self):
        mock_genai_model_instance = MagicMock()
        mock_response = MagicMock()
        mock_response.text = " This is a great LLM article. "
        mock_response.parts = [MagicMock()] # Ensure parts exist
        mock_genai_model_instance.generate_content.return_value = mock_response

        top_content = "Raw TOP data."
        prompt_template = "Test Prompt: {TOP_CONTENT}"

        result = article_writer.generate_journalistic_article_llm(
            top_content, mock_genai_model_instance, prompt_template
        )

        mock_genai_model_instance.generate_content.assert_called_once_with(
            contents=[prompt_template.format(TOP_CONTENT=top_content)]
        )
        self.assertEqual(result, "This is a great LLM article.")

    @patch('src.pipeline_steps.article_writer.log')
    def test_llm_api_error(self, mock_log):
        mock_genai_model_instance = MagicMock()
        mock_genai_model_instance.generate_content.side_effect = google_exceptions.GoogleAPIError("API Error")

        result = article_writer.generate_journalistic_article_llm(
            "Content", mock_genai_model_instance, "Prompt: {TOP_CONTENT}"
        )
        self.assertIsNone(result)
        mock_log.error.assert_called()

    @patch('src.pipeline_steps.article_writer.log')
    def test_llm_empty_response_text(self, mock_log):
        mock_genai_model_instance = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "" # Empty text
        mock_response.parts = [MagicMock()]
        mock_genai_model_instance.generate_content.return_value = mock_response

        result = article_writer.generate_journalistic_article_llm(
            "Content", mock_genai_model_instance, "Prompt: {TOP_CONTENT}"
        )
        self.assertIsNone(result)
        mock_log.warning.assert_any_call("LLM returned empty or whitespace-only text.")

    @patch('src.pipeline_steps.article_writer.log')
    def test_llm_no_response_parts(self, mock_log):
        mock_genai_model_instance = MagicMock()
        mock_response = MagicMock()
        mock_response.parts = [] # No parts
        mock_response.text = None # Also no text
        mock_genai_model_instance.generate_content.return_value = mock_response

        result = article_writer.generate_journalistic_article_llm(
            "Content", mock_genai_model_instance, "Prompt: {TOP_CONTENT}"
        )
        self.assertIsNone(result)
        mock_log.error.assert_any_call("LLM response is empty or has no parts.")

    def test_empty_top_content(self):
        mock_genai_model_instance = MagicMock()
        result = article_writer.generate_journalistic_article_llm(
            "", mock_genai_model_instance, "Prompt: {TOP_CONTENT}"
        )
        self.assertIsNone(result)
        mock_genai_model_instance.generate_content.assert_not_called()


class TestRunArticleWriting(unittest.TestCase):
    """Test suite for the run_article_writing function."""

    @patch('src.pipeline_steps.article_writer.time.sleep')
    @patch('src.pipeline_steps.article_writer.config.load_api_call_delay')
    @patch('src.pipeline_steps.article_writer.config.GENAI_ARTICLE_GENERATION_MODEL', "test-model") # Mock model name directly
    @patch('src.pipeline_steps.article_writer.config.load_google_api_key')
    @patch('src.pipeline_steps.article_writer.genai.configure') # Mock genai.configure
    @patch('src.pipeline_steps.article_writer.genai.GenerativeModel') # Mock the class constructor
    @patch('src.pipeline_steps.article_writer.pathlib.Path.mkdir')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    @patch('src.pipeline_steps.article_writer.db_loader.initialize_chroma_collection')
    @patch('src.pipeline_steps.article_writer.config') # General config mock for PROJECT_ROOT etc.
    def test_successful_llm_article_generation_and_saving(
        self, mock_general_config, mock_initialize_chroma, mock_open_file, mock_mkdir,
        mock_generative_model_constructor, mock_genai_configure, mock_load_google_api_key,
        mock_load_api_call_delay, mock_time_sleep
    ):
        """Test successful LLM generation, file saving, and ChromaDB update."""
        # --- Setup Mocks ---
        # Config related mocks
        mock_project_root = MagicMock(spec=pathlib.Path)
        mock_articles_dir = MagicMock(spec=pathlib.Path)
        mock_project_root.__truediv__.return_value = mock_articles_dir
        mock_general_config.PROJECT_ROOT = mock_project_root
        mock_general_config.CHROMA_DB_DIR_NAME = "test_db"
        mock_general_config.CHROMA_COLLECTION_NAME = "test_collection"
        mock_logger = MagicMock()
        mock_general_config.get_logger.return_value = mock_logger # For general logging

        mock_load_google_api_key.return_value = "dummy_api_key"
        mock_load_api_call_delay.return_value = 0 # No actual sleep in tests

        # LLM model instance mock
        mock_llm_instance = MagicMock()
        mock_generative_model_constructor.return_value = mock_llm_instance
        mock_llm_response = MagicMock()
        mock_llm_response.text = "Mocked LLM Article Content"
        mock_llm_response.parts = [MagicMock()]
        mock_llm_instance.generate_content.return_value = mock_llm_response

        # ChromaDB mock
        mock_chroma_collection = MagicMock()
        mock_initialize_chroma.return_value = mock_chroma_collection
        top_id_1 = "id1"
        top_content_1 = "Raw content for TOP 1"
        top_metadata_1 = {"top_number": "T001", "is_relevant": True}
        mock_chroma_collection.get.return_value = {
            "ids": [top_id_1], "documents": [top_content_1], "metadatas": [top_metadata_1]
        }

        # --- Act ---
        article_writer.run_article_writing()

        # --- Assertions ---
        mock_load_google_api_key.assert_called_once()
        mock_genai_configure.assert_called_once_with(api_key="dummy_api_key")
        mock_generative_model_constructor.assert_called_once_with("test-model")
        mock_llm_instance.generate_content.assert_called_once() # Check it was called

        # Filesystem assertions
        mock_project_root.__truediv__.assert_called_once_with("generated_articles")
        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)

        expected_html_output_from_llm = article_writer.generate_html_article(
            "Mocked LLM Article Content", top_metadata_1["top_number"]
        )
        sanitized_filename = article_writer.sanitize_filename(top_metadata_1["top_number"])
        expected_filepath = mock_articles_dir / f"TOP_{sanitized_filename}.html"
        mock_open_file.assert_called_once_with(expected_filepath, "w", encoding="utf-8")
        mock_open_file().write.assert_called_once_with(expected_html_output_from_llm)

        # ChromaDB update assertions
        updated_md_arg = mock_chroma_collection.update.call_args[0][1][0]
        self.assertTrue(updated_md_arg.get("article_generated"))
        self.assertNotIn("html_content", updated_md_arg)

        mock_time_sleep.assert_called_once_with(0) # api_delay is 0


    @patch('src.pipeline_steps.article_writer.time.sleep')
    @patch('src.pipeline_steps.article_writer.config.load_api_call_delay')
    @patch('src.pipeline_steps.article_writer.config.GENAI_ARTICLE_GENERATION_MODEL', "test-model")
    @patch('src.pipeline_steps.article_writer.config.load_google_api_key')
    @patch('src.pipeline_steps.article_writer.genai.configure')
    @patch('src.pipeline_steps.article_writer.genai.GenerativeModel')
    @patch('src.pipeline_steps.article_writer.pathlib.Path.mkdir')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    @patch('src.pipeline_steps.article_writer.db_loader.initialize_chroma_collection')
    @patch('src.pipeline_steps.article_writer.config')
    @patch('src.pipeline_steps.article_writer.log') # Mock log for error checking
    def test_llm_failure_skips_article(
        self, mock_log, mock_general_config, mock_initialize_chroma, mock_open_file, mock_mkdir,
        mock_generative_model_constructor, mock_genai_configure, mock_load_google_api_key,
        mock_load_api_call_delay, mock_time_sleep
    ):
        """Test that an LLM error skips file generation for that TOP."""
        mock_project_root = MagicMock(spec=pathlib.Path)
        mock_articles_dir = MagicMock(spec=pathlib.Path)
        mock_project_root.__truediv__.return_value = mock_articles_dir
        mock_general_config.PROJECT_ROOT = mock_project_root
        mock_logger = MagicMock()
        mock_general_config.get_logger.return_value = mock_logger # For general logging

        mock_load_google_api_key.return_value = "dummy_api_key"
        mock_load_api_call_delay.return_value = 0

        mock_llm_instance = MagicMock()
        mock_generative_model_constructor.return_value = mock_llm_instance
        # Simulate LLM error by making generate_journalistic_article_llm return None
        # This happens if genai_model_instance.generate_content raises an exception
        mock_llm_instance.generate_content.side_effect = google_exceptions.GoogleAPIError("LLM Simulated API Error")

        mock_chroma_collection = MagicMock()
        mock_initialize_chroma.return_value = mock_chroma_collection
        top_id_1 = "id1_llm_fail"
        top_content_1 = "Content for LLM to fail on"
        top_metadata_1 = {"top_number": "T_FAIL", "is_relevant": True}
        mock_chroma_collection.get.return_value = {
            "ids": [top_id_1], "documents": [top_content_1], "metadatas": [top_metadata_1]
        }

        article_writer.run_article_writing()

        mock_llm_instance.generate_content.assert_called_once()
        mock_open_file.assert_not_called() # File should not be written
        mock_chroma_collection.update.assert_not_called() # ChromaDB should not be updated for this failed TOP
        mock_time_sleep.assert_called_once_with(0) # Sleep should still be called
        # Check that a warning or error was logged about the LLM failure
        # This depends on the logging within generate_journalistic_article_llm and run_article_writing
        self.assertTrue(any("LLM failed to generate article" in call_args[0][0] for call_args in mock_log.warning.call_args_list) or \
                        any("Google API Error during LLM article generation" in call_args[0][0] for call_args in mock_log.error.call_args_list))


    # Simplified versions of no_relevant_tops and chromadb_init_failure
    # They need to mock the GenAI setup part as it happens before ChromaDB interaction.
    @patch('src.pipeline_steps.article_writer.config.load_api_call_delay', MagicMock(return_value=0))
    @patch('src.pipeline_steps.article_writer.config.GENAI_ARTICLE_GENERATION_MODEL', "test-model")
    @patch('src.pipeline_steps.article_writer.config.load_google_api_key', MagicMock(return_value="dummykey"))
    @patch('src.pipeline_steps.article_writer.genai.configure', MagicMock())
    @patch('src.pipeline_steps.article_writer.genai.GenerativeModel', MagicMock())
    @patch('src.pipeline_steps.article_writer.pathlib.Path.mkdir')
    @patch('src.pipeline_steps.article_writer.db_loader.initialize_chroma_collection')
    @patch('src.pipeline_steps.article_writer.config')
    def test_no_relevant_tops(self, mock_general_config, mock_initialize_chroma, mock_mkdir):
        mock_project_root = MagicMock(spec=pathlib.Path)
        mock_articles_dir = MagicMock(spec=pathlib.Path)
        mock_project_root.__truediv__.return_value = mock_articles_dir
        mock_general_config.PROJECT_ROOT = mock_project_root
        mock_logger = MagicMock()
        mock_general_config.get_logger.return_value = mock_logger

        mock_chroma_collection = MagicMock()
        mock_initialize_chroma.return_value = mock_chroma_collection
        mock_chroma_collection.get.return_value = {"ids": [], "documents": [], "metadatas": []}

        with patch('builtins.open', new_callable=unittest.mock.mock_open) as mock_open_file:
            article_writer.run_article_writing()
            mock_open_file.assert_not_called()

        mock_chroma_collection.update.assert_not_called()
        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)


    @patch('src.pipeline_steps.article_writer.config.load_api_call_delay', MagicMock(return_value=0))
    @patch('src.pipeline_steps.article_writer.config.GENAI_ARTICLE_GENERATION_MODEL', "test-model")
    @patch('src.pipeline_steps.article_writer.config.load_google_api_key', MagicMock(return_value="dummykey"))
    @patch('src.pipeline_steps.article_writer.genai.configure', MagicMock())
    @patch('src.pipeline_steps.article_writer.genai.GenerativeModel', MagicMock())
    @patch('src.pipeline_steps.article_writer.pathlib.Path.mkdir')
    @patch('src.pipeline_steps.article_writer.db_loader.initialize_chroma_collection')
    @patch('src.pipeline_steps.article_writer.config')
    def test_chromadb_initialization_failure(self, mock_general_config, mock_initialize_chroma, mock_mkdir):
        mock_project_root = MagicMock(spec=pathlib.Path)
        mock_articles_dir = MagicMock(spec=pathlib.Path)
        mock_project_root.__truediv__.return_value = mock_articles_dir
        mock_general_config.PROJECT_ROOT = mock_project_root
        mock_logger = MagicMock()
        mock_general_config.get_logger.return_value = mock_logger

        mock_initialize_chroma.side_effect = Exception("ChromaDB init error")

        with patch('builtins.open', new_callable=unittest.mock.mock_open) as mock_open_file:
            article_writer.run_article_writing()
            mock_open_file.assert_not_called()

        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)


if __name__ == '__main__':
    logging.disable(logging.CRITICAL) # Keep disabled for normal test runs
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
