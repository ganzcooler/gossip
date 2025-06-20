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
        top_content = "This is the TOP content."
        top_number = "T123"
        expected_title = f"<title>TOP Article: {top_number}</title>"
        expected_header = f"<h1>TOP Content (Original TOP Number: {top_number})</h1>"
        expected_body_content = f'<pre style="white-space: pre-wrap; word-wrap: break-word;">{top_content}</pre>'

        html_output = article_writer.generate_html_article(top_content, top_number)

        self.assertIn("<!DOCTYPE html>", html_output)
        self.assertIn("<html lang=\"en\">", html_output)
        self.assertIn("<head>", html_output)
        self.assertIn("</head>", html_output)
        self.assertIn("<body>", html_output)
        self.assertIn("</body>", html_output)
        self.assertIn(expected_title, html_output)
        self.assertIn(expected_header, html_output)
        self.assertIn(expected_body_content, html_output)
        self.assertIn("font-family: sans-serif;", html_output) # Check for basic style

    def test_empty_content(self):
        """Test with empty TOP content."""
        top_content = ""
        top_number = "T000"
        expected_body_content = f'<pre style="white-space: pre-wrap; word-wrap: break-word;"></pre>'
        html_output = article_writer.generate_html_article(top_content, top_number)
        self.assertIn(expected_body_content, html_output)
        self.assertIn(f"<title>TOP Article: {top_number}</title>", html_output)

    def test_content_with_special_chars(self):
        """Test with TOP content having HTML special characters."""
        top_content = "<p>Hello & Welcome!</p>" # HTML content should be escaped by <pre> or browser rendering
        top_number = "T789"
        # The <pre> tag itself doesn't escape HTML, but the browser will render tags as tags.
        # The key is that the content is placed directly within the <pre> tags.
        # For this test, we're just checking if the content is included as-is.
        # More robust HTML escaping would be a feature of a more complex generator.
        expected_body_content = f'<pre style="white-space: pre-wrap; word-wrap: break-word;">{top_content}</pre>'
        html_output = article_writer.generate_html_article(top_content, top_number)
        self.assertIn(expected_body_content, html_output)

    def test_default_top_number(self):
        """Test that 'N/A' is used if top_number is not provided."""
        top_content = "Some content."
        expected_title = "<title>TOP Article: N/A</title>"
        expected_header = "<h1>TOP Content (Original TOP Number: N/A)</h1>"
        html_output = article_writer.generate_html_article(top_content) # Call without top_number
        self.assertIn(expected_title, html_output)
        self.assertIn(expected_header, html_output)


class TestRunArticleWriting(unittest.TestCase):
    """Test suite for the run_article_writing function."""

    @patch('src.pipeline_steps.article_writer.pathlib.Path.mkdir')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    @patch('src.pipeline_steps.article_writer.db_loader.initialize_chroma_collection')
    @patch('src.pipeline_steps.article_writer.config') # Mock the config module used by article_writer
    def test_html_generation_and_file_saving(self, mock_config, mock_initialize_chroma, mock_open_file, mock_mkdir):
        """Test HTML generation, file saving, and ChromaDB update."""
        # Setup mock config
        mock_project_root = MagicMock(spec=pathlib.Path)
        mock_articles_dir = MagicMock(spec=pathlib.Path)
        # Configure the project_root mock to return articles_dir when '/' is used
        mock_project_root.__truediv__.return_value = mock_articles_dir

        mock_config.PROJECT_ROOT = mock_project_root
        mock_config.CHROMA_DB_DIR_NAME = "test_db"
        mock_config.CHROMA_COLLECTION_NAME = "test_collection"
        mock_logger = MagicMock()
        mock_config.get_logger.return_value = mock_logger

        # Setup mock ChromaDB collection
        mock_chroma_collection = MagicMock()
        mock_initialize_chroma.return_value = mock_chroma_collection

        top_id_1 = "id1"
        top_content_1 = "Content for TOP 1"
        top_metadata_1 = {"top_number": "T001", "is_relevant": True, "existing_field": "preserve_me"}

        top_id_2 = "id2" # Skipped (already processed)
        top_content_2 = "Content for TOP 2"
        # For skipping, only 'article_generated': True matters now. 'html_content' could be there from an old run.
        top_metadata_2 = {"top_number": "T002", "is_relevant": True, "article_generated": True, "html_content": "old_html_data"}

        top_id_3 = "id3" # No content
        top_content_3 = None
        top_metadata_3 = {"top_number": "T003", "is_relevant": True}

        top_id_4 = "id4" # TOP number needs sanitization
        top_content_4 = "Content for TOP 4 Special/Chars"
        top_metadata_4 = {"top_number": "T004/SC", "is_relevant": True}


        mock_chroma_collection.get.return_value = {
            "ids": [top_id_1, top_id_2, top_id_3, top_id_4],
            "documents": [top_content_1, top_content_2, top_content_3, top_content_4],
            "metadatas": [top_metadata_1, top_metadata_2, top_metadata_3, top_metadata_4]
        }

        # Call the function
        article_writer.run_article_writing()

        # 1. Assert directory creation
        mock_project_root.__truediv__.assert_called_once_with("generated_articles")
        mock_articles_dir.mkdir.assert_called_once_with(parents=True, exist_ok=True)

        # 2. Assertions for TOP 1 (processed)
        generated_html_1 = article_writer.generate_html_article(top_content_1, top_metadata_1["top_number"])
        sanitized_top_num_1 = article_writer.sanitize_filename(top_metadata_1["top_number"])
        expected_filepath_1 = mock_articles_dir / f"TOP_{sanitized_top_num_1}.html"

        # Assert file open and write for TOP 1
        mock_open_file.assert_any_call(expected_filepath_1, "w", encoding="utf-8")
        # Get the handle for this specific call to check write
        handle_1 = mock_open_file() # mock_open_file.return_value also works if only one open
        # If multiple files, need to check call_args_list for open, then check write on the specific handle
        # For simplicity here, assuming calls to write correspond to the last open or check specific calls

        # Find the write call that corresponds to generated_html_1
        # This is a bit tricky with multiple calls to open/write.
        # A more robust way would be to check mock_open_file.call_args_list and then the .write() on the handle.
        # For now, we assume the content was written by some call.
        # A more direct check:
        call_args_list = mock_open_file.return_value.write.call_args_list
        self.assertTrue(any(call(generated_html_1) in call_args_list for call_obj in call_args_list for call in call_obj)),
                        "Expected HTML content for TOP 1 was not written to file.")


        # Assert ChromaDB update for TOP 1
        updated_metadata_for_top1_arg = None
        for c_args, _ in mock_chroma_collection.update.call_args_list:
            if c_args[0] == [top_id_1]: # ids=[top_id_1]
                updated_metadata_for_top1_arg = c_args[1][0] # metadatas=[{...}]
                break

        self.assertIsNotNone(updated_metadata_for_top1_arg, "Update not called for TOP 1")
        self.assertTrue(updated_metadata_for_top1_arg.get("article_generated"))
        self.assertNotIn("html_content", updated_metadata_for_top1_arg, "html_content should not be in updated metadata for TOP 1")
        self.assertEqual(updated_metadata_for_top1_arg.get("existing_field"), "preserve_me", "Existing metadata fields were not preserved for TOP 1")
        self.assertEqual(updated_metadata_for_top1_arg.get("top_number"), top_metadata_1["top_number"])


        # 3. Assertions for TOP 4 (processed, with sanitized filename)
        generated_html_4 = article_writer.generate_html_article(top_content_4, top_metadata_4["top_number"])
        sanitized_top_num_4 = article_writer.sanitize_filename(top_metadata_4["top_number"]) # Should be "T004-SC"
        self.assertEqual(sanitized_top_num_4, "T004-SC")
        expected_filepath_4 = mock_articles_dir / f"TOP_{sanitized_top_num_4}.html"
        mock_open_file.assert_any_call(expected_filepath_4, "w", encoding="utf-8")
        # Check write for TOP 4 (similar to above, ensure its content was written)
        self.assertTrue(any(call(generated_html_4) in call_args_list for call_obj in call_args_list for call in call_obj)),
                        "Expected HTML content for TOP 4 was not written to file.")

        # Assert ChromaDB update for TOP 4
        updated_metadata_for_top4_arg = None
        for c_args, _ in mock_chroma_collection.update.call_args_list:
            if c_args[0] == [top_id_4]:
                updated_metadata_for_top4_arg = c_args[1][0]
                break
        self.assertIsNotNone(updated_metadata_for_top4_arg, "Update not called for TOP 4")
        self.assertTrue(updated_metadata_for_top4_arg.get("article_generated"))
        self.assertNotIn("html_content", updated_metadata_for_top4_arg)


        # 4. Overall call counts
        # TOP 1 and TOP 4 should be processed and saved.
        self.assertEqual(mock_open_file.call_count, 2, "File open count is incorrect.")
        self.assertEqual(mock_chroma_collection.update.call_count, 2, "ChromaDB update count is incorrect.")


    @patch('src.pipeline_steps.article_writer.pathlib.Path.mkdir')
    @patch('src.pipeline_steps.article_writer.db_loader.initialize_chroma_collection')
    @patch('src.pipeline_steps.article_writer.config')
    def test_no_relevant_tops(self, mock_config, mock_initialize_chroma, mock_mkdir):
        """Test behavior when no relevant TOPs are found."""
        mock_project_root = MagicMock(spec=pathlib.Path)
        mock_articles_dir = MagicMock(spec=pathlib.Path)
        mock_project_root.__truediv__.return_value = mock_articles_dir
        mock_config.PROJECT_ROOT = mock_project_root
        # ... other config mocks ...
        mock_logger = MagicMock()
        mock_config.get_logger.return_value = mock_logger

        mock_chroma_collection = MagicMock()
        mock_initialize_chroma.return_value = mock_chroma_collection
        mock_chroma_collection.get.return_value = {"ids": [], "documents": [], "metadatas": []}

        with patch('builtins.open', new_callable=unittest.mock.mock_open) as mock_open_file:
            article_writer.run_article_writing()
            mock_open_file.assert_not_called() # No files should be opened

        mock_chroma_collection.update.assert_not_called()
        mock_articles_dir.mkdir.assert_called_once_with(parents=True, exist_ok=True)


    @patch('src.pipeline_steps.article_writer.pathlib.Path.mkdir')
    @patch('src.pipeline_steps.article_writer.db_loader.initialize_chroma_collection')
    @patch('src.pipeline_steps.article_writer.config')
    def test_chromadb_initialization_failure(self, mock_config, mock_initialize_chroma, mock_mkdir):
        """Test behavior when ChromaDB initialization fails."""
        mock_project_root = MagicMock(spec=pathlib.Path)
        mock_articles_dir = MagicMock(spec=pathlib.Path)
        mock_project_root.__truediv__.return_value = mock_articles_dir
        mock_config.PROJECT_ROOT = mock_project_root
        mock_logger = MagicMock()
        mock_config.get_logger.return_value = mock_logger

        mock_initialize_chroma.side_effect = Exception("ChromaDB init error")

        # mock_chroma_collection_instance = MagicMock() # Not needed, get will not be called

        with patch('builtins.open', new_callable=unittest.mock.mock_open) as mock_open_file:
            article_writer.run_article_writing()
            mock_open_file.assert_not_called()

        # Ensure mkdir is still called as it's before Chroma init
        mock_articles_dir.mkdir.assert_called_once_with(parents=True, exist_ok=True)
        # Ensure get is not called on any collection object if init fails
        # This is implicitly tested as mock_chroma_collection.get would fail if mock_initialize_chroma did not return a mock.


if __name__ == '__main__':
    logging.disable(logging.CRITICAL) # Keep disabled for normal test runs
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
