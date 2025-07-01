import unittest
from unittest.mock import patch, MagicMock, call
import pathlib
import sys
import logging
import json
from pydantic import ValidationError
from google.api_core import exceptions as google_exceptions

# Ensure src directory is in sys.path for module imports from src
PROJECT_ROOT_FOR_TEST = pathlib.Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT_FOR_TEST) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_FOR_TEST))

# Modules to test
from src.pipeline_steps import article_writer
from src import config as app_config # To potentially mock config values if needed

# Disable most logging for cleaner test output
# logging.disable(logging.CRITICAL)


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
        self.assertEqual(article_writer.sanitize_filename(""), "untitled_article")

    def test_only_special_chars(self):
        self.assertEqual(article_writer.sanitize_filename("!@#$%^&*()"), "untitled_article")

    def test_numbers_and_hyphens(self):
        self.assertEqual(article_writer.sanitize_filename("123-456-789"), "123-456-789")

    def test_mixed_case(self):
        self.assertEqual(article_writer.sanitize_filename("MixedCaseName"), "MixedCaseName")


class TestGenerateHTMLArticle(unittest.TestCase):
    """Test suite for the generate_html_article function."""

    def test_basic_html_generation(self):
        headline_val = "Test Article Headline"
        content_val = "This is the LLM generated article content."
        pdf_name_val = "source_document.pdf"

        expected_html_title = f"<title>{headline_val}</title>"
        expected_html_header = f"<h1>{headline_val}</h1>"
        expected_html_body_content = f"<pre>{content_val}</pre>" # Content is escaped by html.escape
        expected_source_comment = f"<!-- Source PDF: {pdf_name_val} -->"

        html_output = article_writer.generate_html_article(
            headline_val, content_val, pdf_name_val
        )

        self.assertIn("<!DOCTYPE html>", html_output)
        self.assertIn("<html lang=\"de\">", html_output)
        self.assertIn(expected_html_title, html_output)
        self.assertIn(expected_html_header, html_output)
        self.assertIn(expected_html_body_content, html_output)
        self.assertIn(expected_source_comment, html_output)
        self.assertIn("white-space: pre-wrap;", html_output) # Style for <pre>

    def test_content_with_html_special_chars_gets_escaped(self):
        headline_val = "Special Chars & < > \" ' Test"
        content_val = "<p>Hello & Welcome!</p> This should be escaped."
        pdf_name_val = "chars.pdf"

        # html.escape behavior
        escaped_headline = "&lt;title&gt;Special Chars &amp; &lt; &gt; &quot; &#x27; Test&lt;/title&gt;" # Title tag content
        escaped_h1_content = "Special Chars &amp; &lt; &gt; &quot; &#x27; Test" # H1 content
        escaped_body_content = "&lt;pre&gt;&lt;p&gt;Hello &amp; Welcome!&lt;/p&gt; This should be escaped.&lt;/pre&gt;" # Pre content

        html_output = article_writer.generate_html_article(
            headline_val, content_val, pdf_name_val
        )
        self.assertIn(f"<title>{escaped_h1_content}</title>", html_output) # Title uses the escaped headline
        self.assertIn(f"<h1>{escaped_h1_content}</h1>", html_output)   # H1 uses the escaped headline
        self.assertIn(f"<pre>{escaped_body_content.replace('<pre>','').replace('</pre>','').replace('&lt;pre&gt;','').replace('&lt;/pre&gt;','')}</pre>", html_output)


class TestGenerateArticlesFromTextLLM(unittest.TestCase):
    """Test suite for generate_articles_from_text_llm."""

    @patch('src.pipeline_steps.article_writer.json.loads')
    @patch('src.pipeline_steps.article_writer.LLMGeneratedArticles')
    def test_successful_generation(self, MockLLMGeneratedArticles, mock_json_loads):
        mock_genai_client_instance = MagicMock(spec=article_writer.genai.client.Client)
        mock_response = MagicMock()
        # LLM returns a JSON string representing LLMGeneratedArticles
        mock_llm_json_response = {
            "articles": [
                {"headline": "Headline 1", "content": "Content 1"},
                {"headline": "Headline 2", "content": "Content 2"}
            ]
        }
        mock_response.text = json.dumps(mock_llm_json_response)
        mock_genai_client_instance.generate_content.return_value = mock_response

        # Mock Pydantic validation
        mock_validated_data_instance = MagicMock()
        mock_article_1 = article_writer.SingleArticle(headline="Headline 1", content="Content 1")
        mock_article_2 = article_writer.SingleArticle(headline="Headline 2", content="Content 2")
        mock_validated_data_instance.articles = [mock_article_1, mock_article_2]
        MockLLMGeneratedArticles.return_value = mock_validated_data_instance # Mock the constructor
        mock_json_loads.return_value = mock_llm_json_response # json.loads returns dict

        # If LLMGeneratedArticles(**llm_output) is used directly
        MockLLMGeneratedArticles.model_validate.return_value = mock_validated_data_instance # For Pydantic v2
        # For Pydantic v1, the constructor itself would be called with **mock_llm_json_response

        protocol_text = "Full protocol text here."
        prompt_template = "Test Prompt: {PROTOCOL_TEXT}"
        model_name = "test-model"

        result = article_writer.generate_articles_from_text_llm(
            protocol_text, mock_genai_client_instance, model_name, prompt_template
        )

        self.assertIsNotNone(result)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].headline, "Headline 1")
        self.assertEqual(result[1].content, "Content 2")

        mock_genai_client_instance.generate_content.assert_called_once()
        _, kwargs = mock_genai_client_instance.generate_content.call_args
        self.assertEqual(kwargs['model'], f"models/{model_name}")
        self.assertIn("application/json", kwargs['generation_config'].response_mime_type)
        self.assertIsNotNone(kwargs['generation_config'].response_schema)


    @patch('src.pipeline_steps.article_writer.log')
    def test_llm_api_error(self, mock_log):
        mock_genai_client_instance = MagicMock(spec=article_writer.genai.client.Client)
        mock_genai_client_instance.generate_content.side_effect = google_exceptions.GoogleAPIError("API Error")

        result = article_writer.generate_articles_from_text_llm(
            "Content", mock_genai_client_instance, "model", "Prompt: {PROTOCOL_TEXT}"
        )
        self.assertIsNone(result)
        mock_log.error.assert_any_call("Google API Error during LLM article generation: API Error", exc_info=True)

    @patch('src.pipeline_steps.article_writer.log')
    def test_llm_invalid_json_response(self, mock_log):
        mock_genai_client_instance = MagicMock(spec=article_writer.genai.client.Client)
        mock_response = MagicMock()
        mock_response.text = "{'broken_json': True" # Invalid JSON
        mock_genai_client_instance.generate_content.return_value = mock_response

        result = article_writer.generate_articles_from_text_llm(
            "Content", mock_genai_client_instance, "model", "Prompt: {PROTOCOL_TEXT}"
        )
        self.assertIsNone(result)
        self.assertTrue(any("JSONDecodeError parsing LLM response" in call_args[0][0] for call_args in mock_log.error.call_args_list))

    @patch('src.pipeline_steps.article_writer.log')
    def test_llm_json_schema_mismatch(self, mock_log):
        mock_genai_client_instance = MagicMock(spec=article_writer.genai.client.Client)
        mock_response = MagicMock()
        # Valid JSON, but doesn't match Pydantic model (e.g. 'articles' key missing)
        mock_response.text = '{"wrong_key": "No articles here"}'
        mock_genai_client_instance.generate_content.return_value = mock_response

        # This will now raise ValidationError inside the function if Pydantic is used correctly
        # and Pydantic will be the one logging the error through its own mechanisms if not caught.
        # The function itself catches ValidationError.
        result = article_writer.generate_articles_from_text_llm(
            "Content", mock_genai_client_instance, "model", "Prompt: {PROTOCOL_TEXT}"
        )
        self.assertIsNone(result)
        self.assertTrue(any("Pydantic ValidationError for LLM response" in call_args[0][0] for call_args in mock_log.error.call_args_list))


    @patch('src.pipeline_steps.article_writer.log')
    def test_llm_empty_response_text(self, mock_log):
        mock_genai_client_instance = MagicMock(spec=article_writer.genai.client.Client)
        mock_response = MagicMock()
        mock_response.text = ""
        mock_genai_client_instance.generate_content.return_value = mock_response

        result = article_writer.generate_articles_from_text_llm(
            "Content", mock_genai_client_instance, "model", "Prompt: {PROTOCOL_TEXT}"
        )
        self.assertIsNone(result)
        mock_log.error.assert_any_call("LLM response text is empty. Cannot parse JSON.")


    def test_empty_protocol_text(self):
        mock_genai_client_instance = MagicMock(spec=article_writer.genai.client.Client)
        result = article_writer.generate_articles_from_text_llm(
            "", mock_genai_client_instance, "model", "Prompt: {PROTOCOL_TEXT}"
        )
        self.assertIsNone(result)
        mock_genai_client_instance.generate_content.assert_not_called()


class TestRunArticleWriting(unittest.TestCase):
    """Test suite for the run_article_writing function."""

    @patch('src.pipeline_steps.article_writer.time.sleep')
    @patch('src.pipeline_steps.article_writer.load_api_call_delay')
    @patch('src.pipeline_steps.article_writer.GENAI_ARTICLE_GENERATION_MODEL', "test-model")
    @patch('src.pipeline_steps.article_writer.load_google_api_key')
    @patch('src.pipeline_steps.article_writer.genai.Client')
    @patch('src.pipeline_steps.article_writer.generate_articles_from_text_llm')
    @patch('src.pipeline_steps.article_writer.pathlib.Path.mkdir')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    @patch('src.pipeline_steps.article_writer.config') # Mock the whole config module used by article_writer
    def test_successful_article_generation_and_saving(
        self, mock_article_writer_config, mock_open_file, mock_mkdir,
        mock_generate_articles_llm, mock_genai_client_constructor, mock_load_google_api_key,
        mock_load_api_call_delay, mock_time_sleep
    ):
        # 1. Configure Mocks
        mock_project_root = MagicMock(spec=pathlib.Path)
        mock_articles_dir_path = MagicMock(spec=pathlib.Path)
        mock_project_root.__truediv__.return_value = mock_articles_dir_path # PROJECT_ROOT / ARTICLES_DIR_NAME
        mock_article_writer_config.PROJECT_ROOT = mock_project_root
        mock_article_writer_config.ARTICLES_DIR_NAME = "generated_articles_test"
        mock_article_writer_config.get_logger.return_value = MagicMock() # Mock logger

        mock_load_google_api_key.return_value = "dummy_api_key"
        mock_load_api_call_delay.return_value = 0.01 # Small delay for testing sleep call

        # Mock GenAI Client
        mock_genai_client_instance = MagicMock()
        mock_genai_client_constructor.return_value = mock_genai_client_instance

        # Mock LLM response from generate_articles_from_text_llm
        article1 = article_writer.SingleArticle(headline="Test Headline 1", content="Test Content 1")
        article2 = article_writer.SingleArticle(headline="Another Headline", content="More Content")
        mock_generate_articles_llm.return_value = [article1, article2]

        # Input for run_article_writing
        extracted_texts_input = {
            "protocol_alpha.pdf": "Full text of protocol alpha.",
            "protocol_beta.pdf": "Full text of protocol beta."
        }

        # Path.exists will be called for filename uniqueness, make it return False initially
        mock_articles_dir_path.joinpath.return_value.exists.return_value = False


        # 2. Call run_article_writing
        article_writer.run_article_writing(extracted_texts_input)

        # 3. Assertions
        mock_load_google_api_key.assert_called_once()
        mock_genai_client_constructor.assert_called_once_with(api_key="dummy_api_key")

        # generate_articles_from_text_llm called for each protocol
        self.assertEqual(mock_generate_articles_llm.call_count, len(extracted_texts_input))
        expected_llm_calls = [
            call(protocol_text="Full text of protocol alpha.", client=mock_genai_client_instance, model_name="test-model", prompt_template=article_writer.GENAI_JOURNALISTIC_ARTICLE_PROMPT),
            call(protocol_text="Full text of protocol beta.", client=mock_genai_client_instance, model_name="test-model", prompt_template=article_writer.GENAI_JOURNALISTIC_ARTICLE_PROMPT),
        ]
        mock_generate_articles_llm.assert_has_calls(expected_llm_calls, any_order=True) # dict iteration order

        # Filesystem assertions
        mock_project_root.__truediv__.assert_called_with(mock_article_writer_config.ARTICLES_DIR_NAME)
        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)

        # File writing: 2 articles per protocol, 2 protocols = 4 files
        self.assertEqual(mock_open_file.call_count, 4)
        # Example check for one file (details depend on sanitize_filename and generate_html_article)
        # This requires knowing the exact output of sanitize_filename and generate_html_article
        # For brevity, we'll assume they are tested separately and trust their output.
        # A more robust check would involve capturing the arguments to `open` and `write`.
        self.assertTrue(mock_open_file().write.call_count >= 4) # Each file is written to

        # time.sleep called between processing different PDFs
        self.assertEqual(mock_time_sleep.call_count, len(extracted_texts_input)) # Called after each PDF's LLM call
        mock_time_sleep.assert_any_call(0.01)


    @patch('src.pipeline_steps.article_writer.time.sleep')
    @patch('src.pipeline_steps.article_writer.load_api_call_delay')
    @patch('src.pipeline_steps.article_writer.GENAI_ARTICLE_GENERATION_MODEL', "test-model")
    @patch('src.pipeline_steps.article_writer.load_google_api_key')
    @patch('src.pipeline_steps.article_writer.genai.Client')
    @patch('src.pipeline_steps.article_writer.generate_articles_from_text_llm')
    @patch('src.pipeline_steps.article_writer.pathlib.Path.mkdir')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    @patch('src.pipeline_steps.article_writer.config')
    @patch('src.pipeline_steps.article_writer.log')
    def test_llm_failure_skips_articles_for_that_pdf(
        self, mock_log, mock_article_writer_config, mock_open_file, mock_mkdir,
        mock_generate_articles_llm, mock_genai_client_constructor, mock_load_google_api_key,
        mock_load_api_call_delay, mock_time_sleep
    ):
        mock_project_root = MagicMock(spec=pathlib.Path)
        mock_articles_dir_path = MagicMock(spec=pathlib.Path)
        mock_project_root.__truediv__.return_value = mock_articles_dir_path
        mock_article_writer_config.PROJECT_ROOT = mock_project_root
        mock_article_writer_config.ARTICLES_DIR_NAME = "generated_articles_test"
        mock_article_writer_config.get_logger.return_value = mock_log # Use the passed mock_log

        mock_load_google_api_key.return_value = "dummy_api_key"
        mock_load_api_call_delay.return_value = 0.01

        mock_genai_client_instance = MagicMock()
        mock_genai_client_constructor.return_value = mock_genai_client_instance

        # Simulate LLM failure for the first PDF, success for the second
        article_beta = article_writer.SingleArticle(headline="Beta Headline", content="Beta Content")
        def llm_side_effect(protocol_text, client, model_name, prompt_template):
            if "alpha" in protocol_text:
                return None # Simulate failure
            return [article_beta] # Simulate success

        mock_generate_articles_llm.side_effect = llm_side_effect

        extracted_texts_input = {
            "protocol_alpha.pdf": "Full text of protocol alpha (will fail).",
            "protocol_beta.pdf": "Full text of protocol beta (will succeed)."
        }
        mock_articles_dir_path.joinpath.return_value.exists.return_value = False

        article_writer.run_article_writing(extracted_texts_input)

        self.assertEqual(mock_generate_articles_llm.call_count, 2)
        mock_open_file.assert_called_once() # Only for protocol_beta's article
        # Check that a warning or error was logged about the LLM failure for alpha
        self.assertTrue(any("LLM failed to generate any articles for 'protocol_alpha.pdf'" in msg[0][0] for msg in mock_log.warning.call_args_list))
        self.assertEqual(mock_time_sleep.call_count, 2)


    @patch('src.pipeline_steps.article_writer.load_google_api_key')
    @patch('src.pipeline_steps.article_writer.pathlib.Path.mkdir')
    @patch('src.pipeline_steps.article_writer.config')
    @patch('src.pipeline_steps.article_writer.log')
    def test_no_extracted_texts_provided(
        self, mock_log, mock_article_writer_config, mock_mkdir, mock_load_google_api_key
    ):
        mock_article_writer_config.get_logger.return_value = mock_log

        article_writer.run_article_writing({}) # Empty dict

        mock_load_google_api_key.assert_not_called()
        mock_mkdir.assert_not_called() # Should not attempt to create dir if no texts
        mock_log.info.assert_any_call("No extracted texts provided. Skipping article generation.")


    @patch('src.pipeline_steps.article_writer.load_google_api_key')
    @patch('src.pipeline_steps.article_writer.config')
    @patch('src.pipeline_steps.article_writer.log')
    def test_google_api_key_not_found(
        self, mock_log, mock_article_writer_config, mock_load_google_api_key
    ):
        mock_article_writer_config.get_logger.return_value = mock_log
        mock_load_google_api_key.return_value = None # Simulate API key not found

        article_writer.run_article_writing({"some.pdf": "text"})

        mock_load_google_api_key.assert_called_once()
        mock_log.critical.assert_any_call("Google API key not found in config.ini. LLM generation disabled.")


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG) # Enable logging for test development
    # logging.disable(logging.CRITICAL) # Keep disabled for normal test runs
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
