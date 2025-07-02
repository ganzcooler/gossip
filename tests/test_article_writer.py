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
    # Patch pathlib.Path for mkdir and glob calls on instances
    @patch('src.pipeline_steps.article_writer.pathlib.Path')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    @patch('src.pipeline_steps.article_writer.config') # Mock the whole config module
    def test_successful_article_generation_and_saving(
        self, mock_aw_config, mock_open_file, MockPath, # Correct order of patches
        mock_generate_articles_llm, mock_genai_client_constructor, mock_load_google_api_key,
        mock_load_api_call_delay, mock_time_sleep
    ):
        # 1. Configure Mocks for config and paths
        mock_aw_config.PROJECT_ROOT = MagicMock(spec=pathlib.Path, name="PROJECT_ROOT_INSTANCE")
        mock_aw_config.ARTICLES_DIR_NAME = "generated_articles_test"
        mock_aw_config.EXTRACTED_TEXTS_DIR_NAME = "extracted_texts_test"
        mock_aw_config.get_logger.return_value = MagicMock(name="LoggerInstance")

        # Mock path instances that will be created by PROJECT_ROOT / DIR_NAME
        mock_articles_dir_path_instance = MockPath.return_value # Instance for articles dir
        mock_extracted_texts_dir_instance = MockPath.return_value # Instance for extracted texts dir

        # Configure side_effect for PROJECT_ROOT.__truediv__
        def project_root_truediv_effect(dir_name):
            if dir_name == mock_aw_config.ARTICLES_DIR_NAME:
                # Return a distinct mock for the articles directory path
                mp = MagicMock(spec=pathlib.Path, name=f"ArticlesDirPath_for_{dir_name}")
                mp.joinpath.return_value.exists.return_value = False # For unique filename check
                return mp
            elif dir_name == mock_aw_config.EXTRACTED_TEXTS_DIR_NAME:
                # Return a distinct mock for the extracted texts directory path
                mpt = MagicMock(spec=pathlib.Path, name=f"ExtractedTextsDirPath_for_{dir_name}")
                mpt.is_dir.return_value = True # Extracted texts dir exists
                # Mock .glob() on this specific instance
                mock_text_file1 = MagicMock(spec=pathlib.Path, name="text_file1.txt")
                mock_text_file1.stem = "text_file1" # Used for original_pdf_name
                mock_text_file2 = MagicMock(spec=pathlib.Path, name="text_file2.txt")
                mock_text_file2.stem = "text_file2"
                mpt.glob.return_value = [mock_text_file1, mock_text_file2]
                return mpt
            return MagicMock(spec=pathlib.Path, name=f"DefaultPath_for_{dir_name}")

        mock_aw_config.PROJECT_ROOT.__truediv__.side_effect = project_root_truediv_effect

        # Mock reading from text files
        # open() will be called for each .txt file. We need to provide content.
        def open_side_effect(path_obj, mode, encoding):
            m = unittest.mock.mock_open() # Fresh mock_open for each call
            if path_obj.name == "text_file1.txt":
                m().read.return_value = "Full text of protocol alpha."
            elif path_obj.name == "text_file2.txt":
                m().read.return_value = "Full text of protocol beta."
            else:
                m().read.return_value = "Default text content."
            return m() # Return the file handle mock
        mock_open_file.side_effect = open_side_effect


        mock_load_google_api_key.return_value = "dummy_api_key"
        mock_load_api_call_delay.return_value = 0.01

        mock_genai_client_instance = MagicMock()
        mock_genai_client_constructor.return_value = mock_genai_client_instance

        article1 = article_writer.SingleArticle(headline="Test Headline 1", content="Test Content 1")
        article2 = article_writer.SingleArticle(headline="Another Headline", content="More Content")
        # LLM should return 2 articles for each text file
        mock_generate_articles_llm.return_value = [article1, article2]


        # 2. Call run_article_writing (no arguments, it reads from mocked file system)
        article_writer.run_article_writing()

        # 3. Assertions
        # Ensure extracted_texts_dir was checked and globbed
        mock_aw_config.PROJECT_ROOT.__truediv__.assert_any_call(mock_aw_config.EXTRACTED_TEXTS_DIR_NAME)
        # The specific instance returned by __truediv__ for EXTRACTED_TEXTS_DIR_NAME should have had is_dir and glob called
        # This requires capturing that instance or ensuring MockPath.return_value was configured for it.
        # Simpler: check if any MockPath instance had these calls if only one is expected for extracted_texts

        # Find the mock instance that corresponds to the extracted_texts_dir
        found_extracted_texts_dir_mock = None
        for call_arg in mock_aw_config.PROJECT_ROOT.__truediv__.call_args_list:
            if call_arg[0][0] == mock_aw_config.EXTRACTED_TEXTS_DIR_NAME:
                # Get the return value of this specific call if possible, or rely on a single MockPath.return_value
                # This part is tricky if __truediv__ returns new mocks each time.
                # Let's assume the side effect consistently returns the same mock for the same name for simplicity in test.
                # For this test, we'll rely on the setup of mpt.glob and mpt.is_dir
                # We need to find which mock object `mpt` was (the one for extracted_texts_dir)
                # This is why assigning the result of __truediv__ to a variable and using that is better.
                # However, with the current structure:
                self.assertTrue(any(c[0][0] == mock_aw_config.EXTRACTED_TEXTS_DIR_NAME for c in mock_aw_config.PROJECT_ROOT.__truediv__.call_args_list))
                # We need to verify that the mock object that had .glob called, was the one for extracted_texts
                # This is implicitly tested if mock_open_file is called with paths derived from "text_file1.txt" etc.


        # Check open calls for reading text files
        mock_open_file.assert_any_call(unittest.mock.ANY, "r", encoding="utf-8") # ANY for path object
        read_calls = [c for c in mock_open_file.call_args_list if c[0][1] == "r"]
        self.assertEqual(len(read_calls), 2) # text_file1.txt, text_file2.txt


        mock_load_google_api_key.assert_called_once()
        mock_genai_client_constructor.assert_called_once_with(api_key="dummy_api_key")

        self.assertEqual(mock_generate_articles_llm.call_count, 2) # For 2 text files
        expected_llm_calls = [
            call(protocol_text="Full text of protocol alpha.", client=mock_genai_client_instance, model_name="test-model", prompt_template=article_writer.GENAI_JOURNALISTIC_ARTICLE_PROMPT),
            call(protocol_text="Full text of protocol beta.", client=mock_genai_client_instance, model_name="test-model", prompt_template=article_writer.GENAI_JOURNALISTIC_ARTICLE_PROMPT),
        ]
        mock_generate_articles_llm.assert_has_calls(expected_llm_calls, any_order=True)

        # Filesystem assertions for writing HTML
        # articles_dir_path_instance (the one for ARTICLES_DIR_NAME) should have mkdir called on it
        # Again, need to ensure we are checking the correct mock instance.
        # Let's find the mock for articles_dir among the __truediv__ return values
        articles_dir_mock_instance = None
        for call_obj in mock_aw_config.PROJECT_ROOT.__truediv__.call_args_list:
            dir_name_arg = call_obj[0][0]
            returned_path_mock = mock_aw_config.PROJECT_ROOT.__truediv__(dir_name_arg) # re-call to get the mock
            if dir_name_arg == mock_aw_config.ARTICLES_DIR_NAME:
                articles_dir_mock_instance = returned_path_mock
                break
        self.assertIsNotNone(articles_dir_mock_instance)
        articles_dir_mock_instance.mkdir.assert_called_once_with(parents=True, exist_ok=True)


        # File writing: 2 articles per text file, 2 text files = 4 HTML files written
        write_calls = [c for c in mock_open_file.call_args_list if c[0][1] == "w"]
        self.assertEqual(len(write_calls), 4)
        self.assertTrue(mock_open_file().write.call_count >= 4)

        self.assertEqual(mock_time_sleep.call_count, 2) # Called after each text file's LLM processing
        mock_time_sleep.assert_any_call(0.01)


    @patch('src.pipeline_steps.article_writer.time.sleep')
    @patch('src.pipeline_steps.article_writer.load_api_call_delay')
    @patch('src.pipeline_steps.article_writer.GENAI_ARTICLE_GENERATION_MODEL', "test-model")
    @patch('src.pipeline_steps.article_writer.load_google_api_key')
    @patch('src.pipeline_steps.article_writer.genai.Client')
    @patch('src.pipeline_steps.article_writer.generate_articles_from_text_llm')
    @patch('src.pipeline_steps.article_writer.pathlib.Path') # Mock Path class
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    @patch('src.pipeline_steps.article_writer.config') # Mock config module
    @patch('src.pipeline_steps.article_writer.log')
    def test_llm_failure_skips_articles_for_that_text_file(
        self, mock_log, mock_aw_config, mock_open_file, MockPath, # Patches in reverse order
        mock_generate_articles_llm, mock_genai_client_constructor, mock_load_google_api_key,
        mock_load_api_call_delay, mock_time_sleep
    ):
        mock_aw_config.PROJECT_ROOT = MagicMock(spec=pathlib.Path)
        mock_aw_config.ARTICLES_DIR_NAME = "generated_articles_test"
        mock_aw_config.EXTRACTED_TEXTS_DIR_NAME = "extracted_texts_test"
        # mock_aw_config.get_logger.return_value = mock_log # Logger is passed directly

        mock_articles_dir_path_instance = MagicMock(spec=pathlib.Path, name="ArticlesDirInstance")
        mock_articles_dir_path_instance.joinpath.return_value.exists.return_value = False
        mock_extracted_texts_dir_instance = MagicMock(spec=pathlib.Path, name="ExtractedTextsDirInstance")
        mock_extracted_texts_dir_instance.is_dir.return_value = True

        def project_root_truediv_effect(dir_name):
            if dir_name == mock_aw_config.ARTICLES_DIR_NAME: return mock_articles_dir_path_instance
            if dir_name == mock_aw_config.EXTRACTED_TEXTS_DIR_NAME: return mock_extracted_texts_dir_instance
            return MagicMock()
        mock_aw_config.PROJECT_ROOT.__truediv__.side_effect = project_root_truediv_effect

        # Simulate two text files: one for which LLM fails, one for which it succeeds
        mock_text_file_alpha = MagicMock(spec=pathlib.Path, name="alpha.txt", stem="alpha")
        mock_text_file_beta = MagicMock(spec=pathlib.Path, name="beta.txt", stem="beta")
        mock_extracted_texts_dir_instance.glob.return_value = [mock_text_file_alpha, mock_text_file_beta]

        def open_side_effect(path_obj, mode, encoding):
            m = unittest.mock.mock_open()
            if path_obj.name == "alpha.txt": m().read.return_value = "Text alpha (LLM will fail)"
            elif path_obj.name == "beta.txt": m().read.return_value = "Text beta (LLM will succeed)"
            return m()
        mock_open_file.side_effect = open_side_effect

        mock_load_google_api_key.return_value = "dummy_api_key"
        mock_load_api_call_delay.return_value = 0.01
        mock_genai_client_instance = MagicMock()
        mock_genai_client_constructor.return_value = mock_genai_client_instance

        article_beta = article_writer.SingleArticle(headline="Beta Headline", content="Beta Content")
        def llm_side_effect_func(protocol_text, client, model_name, prompt_template):
            if "alpha" in protocol_text: return None # LLM fails for alpha
            return [article_beta] # LLM succeeds for beta
        mock_generate_articles_llm.side_effect = llm_side_effect_func

        article_writer.run_article_writing()

        self.assertEqual(mock_generate_articles_llm.call_count, 2)
        # mock_open_file is called for reading (2 times) and writing (1 time for beta's article)
        write_calls = [c for c in mock_open_file.call_args_list if c[0][1] == "w"]
        self.assertEqual(len(write_calls), 1) # Only for beta's article

        self.assertTrue(any("LLM failed to generate any articles for 'alpha.pdf'" in msg[0][0] for msg in mock_log.warning.call_args_list))
        self.assertEqual(mock_time_sleep.call_count, 2)


    @patch('src.pipeline_steps.article_writer.load_google_api_key')
    @patch('src.pipeline_steps.article_writer.pathlib.Path') # Mock Path class
    @patch('src.pipeline_steps.article_writer.config')    # Mock config module
    @patch('src.pipeline_steps.article_writer.log')
    def test_no_extracted_text_files_found(
        self, mock_log, mock_aw_config, MockPath, mock_load_google_api_key
    ):
        mock_aw_config.PROJECT_ROOT = MagicMock(spec=pathlib.Path)
        mock_aw_config.EXTRACTED_TEXTS_DIR_NAME = "empty_extracted_texts"
        # mock_aw_config.get_logger.return_value = mock_log

        mock_extracted_texts_dir_instance = MagicMock(spec=pathlib.Path)
        mock_extracted_texts_dir_instance.is_dir.return_value = True
        mock_extracted_texts_dir_instance.glob.return_value = [] # No files found

        mock_aw_config.PROJECT_ROOT.__truediv__.return_value = mock_extracted_texts_dir_instance

        article_writer.run_article_writing() # Call without specific dir, uses default from config

        mock_load_google_api_key.assert_not_called()
        # Ensure articles directory (mock_articles_dir_path_instance.mkdir) is not called
        # This requires ensuring that the path for articles_dir is also mocked if it's created
        # For this specific test, it's enough that LLM calls are not made.
        # A more robust way would be to also mock ARTICLES_DIR_NAME path and check its mkdir.
        mock_log.info.assert_any_call(f"No text files found in {mock_extracted_texts_dir_instance}. Skipping article generation.")


    @patch('src.pipeline_steps.article_writer.load_google_api_key')
    @patch('src.pipeline_steps.article_writer.config') # Mock config module
    @patch('src.pipeline_steps.article_writer.log')
    def test_google_api_key_not_found(
        self, mock_log, mock_aw_config, mock_load_google_api_key # mock_load_google_api_key is already a patch object
    ):
        # mock_aw_config.get_logger.return_value = mock_log # Logger is passed directly
        mock_aw_config.PROJECT_ROOT = MagicMock(spec=pathlib.Path)
        mock_aw_config.EXTRACTED_TEXTS_DIR_NAME = "texts_for_api_key_test"

        # Simulate that there's at least one text file to process, so it attempts to load key
        mock_extracted_texts_dir_instance = MagicMock(spec=pathlib.Path)
        mock_extracted_texts_dir_instance.is_dir.return_value = True
        mock_text_file = MagicMock(spec=pathlib.Path, name="some_file.txt", stem="some_file")
        mock_extracted_texts_dir_instance.glob.return_value = [mock_text_file]
        mock_aw_config.PROJECT_ROOT.__truediv__.return_value = mock_extracted_texts_dir_instance

        # Mock open to successfully read the dummy text file
        with patch('builtins.open', unittest.mock.mock_open(read_data="Some text content")) as mock_file_open:
            mock_load_google_api_key.return_value = None # Simulate API key not found
            article_writer.run_article_writing() # Call without dir override

        mock_load_google_api_key.assert_called_once()
        mock_file_open.assert_called_once_with(mock_text_file, "r", encoding="utf-8") # Check read attempt
        mock_log.critical.assert_any_call("Google API key not found in config.ini. LLM generation disabled.")


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG) # Enable logging for test development
    # logging.disable(logging.CRITICAL) # Keep disabled for normal test runs
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
