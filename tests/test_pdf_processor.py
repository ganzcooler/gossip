import unittest
from unittest.mock import patch, MagicMock, call
import pathlib
import sys
import json

# Add project root to sys.path to allow src imports
project_root_for_test = pathlib.Path(__file__).resolve().parent.parent
if str(project_root_for_test) not in sys.path:
    sys.path.insert(0, str(project_root_for_test))

# Import the functions and variables to be tested
from src.pipeline_steps.pdf_processor import run_pdf_text_extraction, extract_text_from_pdf_pymupdf
from src import config # For accessing config constants in assertions


class TestPDFProcessingPyMuPDF(unittest.TestCase):

    @patch('src.pipeline_steps.pdf_processor.fitz.open')
    @patch('src.pipeline_steps.pdf_processor.log')
    def test_extract_text_from_pdf_pymupdf_success(self, mock_log, mock_fitz_open):
        # Mock PyMuPDF document and page
        mock_doc = MagicMock()
        mock_page1 = MagicMock()
        mock_page1.get_text.return_value = "Text from page 1. "
        mock_page2 = MagicMock()
        mock_page2.get_text.return_value = "Text from page 2."
        mock_doc.load_page.side_effect = [mock_page1, mock_page2]
        mock_doc.__len__.return_value = 2 # Two pages
        mock_fitz_open.return_value = mock_doc

        pdf_filepath = MagicMock(spec=pathlib.Path)
        pdf_filepath.name = "test.pdf"

        extracted_text = extract_text_from_pdf_pymupdf(pdf_filepath)

        self.assertEqual(extracted_text, "Text from page 1. Text from page 2.")
        mock_fitz_open.assert_called_once_with(pdf_filepath)
        mock_doc.load_page.assert_any_call(0)
        mock_doc.load_page.assert_any_call(1)
        mock_page1.get_text.assert_called_once()
        mock_page2.get_text.assert_called_once()
        mock_doc.close.assert_called_once()
        mock_log.info.assert_any_call(f"Successfully extracted text from {pdf_filepath.name} using PyMuPDF.")

    @patch('src.pipeline_steps.pdf_processor.fitz.open')
    @patch('src.pipeline_steps.pdf_processor.log')
    def test_extract_text_from_pdf_pymupdf_error(self, mock_log, mock_fitz_open):
        mock_fitz_open.side_effect = Exception("PyMuPDF error")
        pdf_filepath = MagicMock(spec=pathlib.Path)
        pdf_filepath.name = "error.pdf"

        extracted_text = extract_text_from_pdf_pymupdf(pdf_filepath)

        self.assertEqual(extracted_text, "")
        mock_log.error.assert_any_call(f"Error extracting text from {pdf_filepath.name} using PyMuPDF: PyMuPDF error", exc_info=True)

    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    @patch('src.pipeline_steps.pdf_processor.extract_text_from_pdf_pymupdf')
    @patch('src.pipeline_steps.pdf_processor.pathlib.Path.glob') # Target for glob
    @patch('src.pipeline_steps.pdf_processor.pathlib.Path.mkdir') # Target for mkdir
    @patch('src.pipeline_steps.pdf_processor.config') # Mock the config module
    @patch('src.pipeline_steps.pdf_processor.log')
    def test_run_pdf_text_extraction_creates_text_files(
        self, mock_log, mock_config_module, mock_path_mkdir, mock_path_glob, # Correct order of patches
        mock_extract_text_pymupdf, mock_open_file
    ):
        # 1. Mock config values
        mock_config_module.PROJECT_ROOT = MagicMock(spec=pathlib.Path)
        mock_config_module.PDF_DIR_NAME = "test_pdfs_dir"
        mock_config_module.EXTRACTED_TEXTS_DIR_NAME = "test_extracted_texts_dir"

        # Mock paths
        # When PROJECT_ROOT / "name" is called, it should return a mock path
        mock_pdf_dir_path = MagicMock(spec=pathlib.Path, name="mock_pdf_dir_path_instance")
        mock_extracted_texts_path = MagicMock(spec=pathlib.Path, name="mock_extracted_texts_path_instance")

        def project_root_truediv_side_effect(name):
            if name == mock_config_module.PDF_DIR_NAME:
                return mock_pdf_dir_path
            if name == mock_config_module.EXTRACTED_TEXTS_DIR_NAME:
                return mock_extracted_texts_path
            return MagicMock() # default for other divisions

        mock_config_module.PROJECT_ROOT.__truediv__.side_effect = project_root_truediv_side_effect

        # mock_path_mkdir is the mock for pathlib.Path.mkdir
        # We need to assert it's called on mock_extracted_texts_path
        # This is tricky because Path.mkdir is a method of Path instances.
        # Instead, we check that `mock_extracted_texts_path.mkdir` is called.
        # So, `mock_extracted_texts_path` (returned by PROJECT_ROOT / EXTRACTED_TEXTS_DIR_NAME)
        # needs to have a `mkdir` mock attribute.
        mock_extracted_texts_path.mkdir = MagicMock(name="mkdir_on_extracted_texts_path")

        # Simulate PDF directory exists
        mock_pdf_dir_path.is_dir.return_value = True

        # Mock PDF files found by glob - this should be on the *instance* of the path
        mock_pdf_file1 = MagicMock(spec=pathlib.Path)
        mock_pdf_file1.name = "doc1.pdf"
        mock_pdf_file1.stem = "doc1"
        mock_pdf_file2 = MagicMock(spec=pathlib.Path)
        mock_pdf_file2.name = "doc2.pdf"
        mock_pdf_file2.stem = "doc2"
        mock_pdf_dir_path.glob.return_value = [mock_pdf_file1, mock_pdf_file2] # glob is called on the path instance


        # Mock return values for extract_text_from_pdf_pymupdf
        mock_extract_text_pymupdf.side_effect = ["Text from doc1", "Text from doc2"]

        # Mock that text files do not exist initially
        mock_txt_file1_path = MagicMock(spec=pathlib.Path, name="doc1.txt_path_instance")
        mock_txt_file1_path.exists.return_value = False
        mock_txt_file2_path = MagicMock(spec=pathlib.Path, name="doc2.txt_path_instance")
        mock_txt_file2_path.exists.return_value = False

        def extracted_texts_truediv_side_effect(filename):
            if filename == "doc1.txt": return mock_txt_file1_path
            if filename == "doc2.txt": return mock_txt_file2_path
            return MagicMock()
        mock_extracted_texts_path.__truediv__.side_effect = extracted_texts_truediv_side_effect

        # 2. Call run_pdf_text_extraction
        run_pdf_text_extraction()

        # 3. Assertions
        # Check that PROJECT_ROOT was used to create paths
        mock_config_module.PROJECT_ROOT.__truediv__.assert_any_call(mock_config_module.PDF_DIR_NAME)
        mock_config_module.PROJECT_ROOT.__truediv__.assert_any_call(mock_config_module.EXTRACTED_TEXTS_DIR_NAME)

        # Check creation of extracted_texts_dir
        mock_extracted_texts_path.mkdir.assert_called_once_with(parents=True, exist_ok=True)

        # Check glob call on the correct path object
        mock_pdf_dir_path.glob.assert_called_once_with('*.pdf')

        # Check extraction calls
        mock_extract_text_pymupdf.assert_any_call(mock_pdf_file1)
        mock_extract_text_pymupdf.assert_any_call(mock_pdf_file2)
        self.assertEqual(mock_extract_text_pymupdf.call_count, 2)

        # Check file writing operations
        # mock_open_file is the mock for the built-in open
        # We need to check it was called with the correct path objects.
        expected_write_calls = [
            call(mock_txt_file1_path, "w", encoding="utf-8"), # Path objects from truediv
            call(mock_txt_file2_path, "w", encoding="utf-8")
        ]
        mock_open_file.assert_has_calls(expected_write_calls, any_order=True)
        # Check content written
        mock_open_file().write.assert_any_call("Text from doc1")
        mock_open_file().write.assert_any_call("Text from doc2")

        mock_log.info.assert_any_call(f"Successfully processed and saved text for 2 PDF files.")


    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    @patch('src.pipeline_steps.pdf_processor.extract_text_from_pdf_pymupdf')
    @patch('src.pipeline_steps.pdf_processor.config') # Mock the config module
    @patch('src.pipeline_steps.pdf_processor.log')
    def test_run_pdf_text_extraction_skips_existing_files(
        self, mock_log, mock_config_module,
        mock_extract_text_pymupdf, mock_open_file
    ):
        mock_config_module.PROJECT_ROOT = MagicMock(spec=pathlib.Path)
        mock_config_module.PDF_DIR_NAME = "pdfs"
        mock_config_module.EXTRACTED_TEXTS_DIR_NAME = "texts"

        mock_pdf_dir_path = MagicMock(spec=pathlib.Path)
        mock_extracted_texts_path = MagicMock(spec=pathlib.Path)
        mock_config_module.PROJECT_ROOT.__truediv__.side_effect = lambda name: mock_pdf_dir_path if name == "pdfs" else mock_extracted_texts_path

        mock_extracted_texts_path.mkdir = MagicMock()
        mock_pdf_dir_path.is_dir.return_value = True

        mock_pdf_file1 = MagicMock(spec=pathlib.Path, name="existing.pdf", stem="existing")
        mock_pdf_file2 = MagicMock(spec=pathlib.Path, name="new.pdf", stem="new")
        mock_pdf_dir_path.glob.return_value = [mock_pdf_file1, mock_pdf_file2]

        mock_existing_txt_path = MagicMock(spec=pathlib.Path, name="existing.txt_path")
        mock_existing_txt_path.exists.return_value = True
        mock_new_txt_path = MagicMock(spec=pathlib.Path, name="new.txt_path")
        mock_new_txt_path.exists.return_value = False

        def truediv_side_effect(filename):
            if filename == "existing.txt": return mock_existing_txt_path
            if filename == "new.txt": return mock_new_txt_path
            return MagicMock()
        mock_extracted_texts_path.__truediv__.side_effect = truediv_side_effect

        mock_extract_text_pymupdf.return_value = "Text from new PDF"

        run_pdf_text_extraction()

        mock_extract_text_pymupdf.assert_called_once_with(mock_pdf_file2)
        mock_open_file.assert_called_once_with(mock_new_txt_path, "w", encoding="utf-8")
        mock_open_file().write.assert_called_once_with("Text from new PDF")
        mock_log.info.assert_any_call(f"Skipping PDF '{mock_pdf_file1.name}': Extracted text file already exists at '{mock_existing_txt_path}'.")
        mock_log.info.assert_any_call(f"Successfully processed and saved text for 1 PDF files.")
        mock_log.info.assert_any_call(f"Skipped 1 PDF files (text file already existed).")


    @patch('src.pipeline_steps.pdf_processor.config') # Mock config
    @patch('src.pipeline_steps.pdf_processor.log')
    def test_run_pdf_text_extraction_pdf_dir_not_found(
        self, mock_log, mock_config_module
    ):
        mock_config_module.PROJECT_ROOT = MagicMock(spec=pathlib.Path)
        mock_config_module.PDF_DIR_NAME = "non_existent_pdfs"
        mock_config_module.EXTRACTED_TEXTS_DIR_NAME = "texts_output"

        mock_pdf_dir_path = MagicMock(spec=pathlib.Path)
        mock_extracted_texts_dir_path = MagicMock(spec=pathlib.Path)

        def project_root_truediv_side_effect(name):
            if name == mock_config_module.PDF_DIR_NAME:
                return mock_pdf_dir_path
            if name == mock_config_module.EXTRACTED_TEXTS_DIR_NAME:
                return mock_extracted_texts_dir_path
            return MagicMock()
        mock_config_module.PROJECT_ROOT.__truediv__ = MagicMock(side_effect=project_root_truediv_side_effect)

        mock_extracted_texts_dir_path.mkdir = MagicMock()
        mock_pdf_dir_path.is_dir.return_value = False
        mock_pdf_dir_path.glob = MagicMock() # Add glob mock to avoid AttributeError if is_dir was True

        run_pdf_text_extraction()

        mock_extracted_texts_dir_path.mkdir.assert_called_once_with(parents=True, exist_ok=True)
        mock_log.error.assert_any_call(f"PDF directory not found: {mock_pdf_dir_path}. Please ensure it exists and contains PDF files.")
        mock_pdf_dir_path.glob.assert_not_called()

if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
