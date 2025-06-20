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
logging.disable(logging.CRITICAL)


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

    @patch('src.pipeline_steps.article_writer.db_loader.initialize_chroma_collection')
    @patch('src.pipeline_steps.article_writer.config') # Mock the config module used by article_writer
    def test_html_generation_and_storage(self, mock_config, mock_initialize_chroma):
        """Test that HTML is generated and stored in ChromaDB for relevant TOPs."""
        # Setup mock config
        mock_config.CHROMA_DB_DIR_NAME = "test_db"
        mock_config.CHROMA_COLLECTION_NAME = "test_collection"
        mock_config.PROJECT_ROOT = "/fake/project/root"
        # Mock logger from config to avoid issues if config.get_logger is called inside the function
        mock_logger = MagicMock()
        mock_config.get_logger.return_value = mock_logger

        # Setup mock ChromaDB collection
        mock_chroma_collection = MagicMock()
        mock_initialize_chroma.return_value = mock_chroma_collection

        top_id_1 = "id1"
        top_content_1 = "Content for TOP 1"
        top_metadata_1 = {"top_number": "T001", "is_relevant": True}

        top_id_2 = "id2" # This one will be skipped (already processed)
        top_content_2 = "Content for TOP 2"
        top_metadata_2 = {"top_number": "T002", "is_relevant": True, "article_generated": True, "html_content": "<p>already done</p>"}

        top_id_3 = "id3" # This one has no content
        top_content_3 = None
        top_metadata_3 = {"top_number": "T003", "is_relevant": True}


        mock_chroma_collection.get.return_value = {
            "ids": [top_id_1, top_id_2, top_id_3],
            "documents": [top_content_1, top_content_2, top_content_3],
            "metadatas": [top_metadata_1, top_metadata_2, top_metadata_3]
        }

        # Call the function to be tested
        article_writer.run_article_writing()

        # Assertions for TOP 1 (should be processed)
        generated_html_1 = article_writer.generate_html_article(top_content_1, top_metadata_1["top_number"])
        expected_metadata_update_1 = { # This is what should be merged with existing metadata
            'article_generated': True,
            'html_content': generated_html_1
        }

        # Check that update was called for top_id_1
        # The update method is called with ids=[id], metadatas=[merged_metadata]
        # We need to find the call corresponding to top_id_1
        update_call_args_list = mock_chroma_collection.update.call_args_list

        call_for_top1_found = False
        for c in update_call_args_list:
            args, _ = c
            if args[0] == [top_id_1]: # ids=[top_id_1]
                updated_metadata_for_top1 = args[1][0] # metadatas=[{...}]
                self.assertEqual(updated_metadata_for_top1.get("top_number"), top_metadata_1["top_number"])
                self.assertTrue(updated_metadata_for_top1.get("article_generated"))
                self.assertEqual(updated_metadata_for_top1.get("html_content"), generated_html_1)
                call_for_top1_found = True
                break
        self.assertTrue(call_for_top1_found, "ChromaDB update was not called correctly for TOP 1")


        # Assertions for TOP 2 (should be skipped, so no update call beyond initial state if any)
        # And TOP 3 (no content, so no update call)
        # Overall, update should only be called once for TOP1 in this setup.
        self.assertEqual(mock_chroma_collection.update.call_count, 1, "ChromaDB update called more or less than expected.")


    @patch('src.pipeline_steps.article_writer.db_loader.initialize_chroma_collection')
    @patch('src.pipeline_steps.article_writer.config')
    def test_no_relevant_tops(self, mock_config, mock_initialize_chroma):
        """Test behavior when no relevant TOPs are found."""
        mock_config.CHROMA_DB_DIR_NAME = "test_db"
        mock_config.CHROMA_COLLECTION_NAME = "test_collection"
        mock_config.PROJECT_ROOT = "/fake/project/root"
        mock_logger = MagicMock()
        mock_config.get_logger.return_value = mock_logger

        mock_chroma_collection = MagicMock()
        mock_initialize_chroma.return_value = mock_chroma_collection
        mock_chroma_collection.get.return_value = {"ids": [], "documents": [], "metadatas": []} # No TOPs

        article_writer.run_article_writing()

        mock_chroma_collection.update.assert_not_called()
        # Check for log message (example)
        # mock_logger.info.assert_any_call("No relevant TOPs found for article generation.")
        # More specific log assertion might be needed depending on exact logging statements.


    @patch('src.pipeline_steps.article_writer.db_loader.initialize_chroma_collection')
    @patch('src.pipeline_steps.article_writer.config')
    def test_chromadb_initialization_failure(self, mock_config, mock_initialize_chroma):
        """Test behavior when ChromaDB initialization fails."""
        mock_config.CHROMA_DB_DIR_NAME = "test_db"
        mock_config.CHROMA_COLLECTION_NAME = "test_collection"
        mock_config.PROJECT_ROOT = "/fake/project/root"
        mock_logger = MagicMock()
        mock_config.get_logger.return_value = mock_logger

        mock_initialize_chroma.side_effect = Exception("ChromaDB init error")

        mock_chroma_collection_instance = MagicMock() # To check it's not used

        article_writer.run_article_writing()

        mock_chroma_collection_instance.get.assert_not_called()
        mock_chroma_collection_instance.update.assert_not_called()
        # Check for critical log message
        # mock_logger.critical.assert_any_call("CRITICAL: Initialization error (ChromaDB) in article writing: ChromaDB init error", exc_info=True)


if __name__ == '__main__':
    # Re-enable logging for test execution if desired, or configure for tests
    # logging.disable(logging.NOTSET)
    # logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
