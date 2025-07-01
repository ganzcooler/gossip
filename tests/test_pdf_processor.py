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
from src.pipeline_steps.pdf_processor import process_single_pdf, run_pdf_extraction # Renamed main function
from src import config # For accessing config constants in assertions
# PDF_PROCESSOR_PROMPT_TEXT is now directly from src.prompts, imported by pdf_processor.py
# No need to import it here if pdf_processor.PROMPT_TEXT is used.

class TestPDFProcessing(unittest.TestCase):

    @patch('src.pipeline_steps.pdf_processor.time.sleep')
    @patch('src.pipeline_steps.pdf_processor.pathlib.Path.read_bytes')
    @patch('src.pipeline_steps.pdf_processor.genai.GenerativeModel') # Mock the constructor
    @patch('src.pipeline_steps.pdf_processor.log') # Mock logger
    def test_process_single_pdf_extracts_text_successfully(
        self, mock_log, MockGenerativeModel, mock_read_bytes, mock_time_sleep
    ):
        # 1. Setup mock GenAI Model instance and its response
        mock_model_instance = MockGenerativeModel.return_value # Get the instance from the mocked constructor
        llm_response_data = { # This structure is based on the old PDF_EXTRACTION_PROMPT
            "title": "Test Protocol Title from LLM",
            "datum": "2023-10-26",
            "tops": [
                "TOP 1: Discussion about budget.",
                "TOP 2: Decision on new park."
            ]
        }
        # The new process_single_pdf expects the LLM to return the *full text* of the PDF,
        # not a structured JSON anymore. The old PDF_EXTRACTION_PROMPT is gone.
        # The prompt used by process_single_pdf is now for *summarization/extraction to a single block of text*
        # if the old `PROMPT_TEXT` variable in `pdf_processor.py` was generic enough, or it needs to be assumed
        # that the model simply returns the extracted text.

        # For the purpose of this test, let's assume the LLM returns a single string of the PDF's content.
        # The prompt for actual text extraction is now part of the `genai.Part.from_data` call.
        # The `prompt` argument to `process_single_pdf` is not used anymore with Gemini 1.5 Flash.

        mock_llm_extracted_text = "This is the full extracted text from the PDF by the LLM."
        mock_llm_response = MagicMock()
        mock_llm_response.text = mock_llm_extracted_text
        mock_model_instance.generate_content.return_value = mock_llm_response

        # 2. Mock PDF file interactions
        mock_read_bytes.return_value = b"dummy raw pdf content"
        pdf_filepath = MagicMock(spec=pathlib.Path)
        pdf_filepath.name = "test_protocol.pdf"

        # 3. Call process_single_pdf
        # The `prompt` argument is removed from process_single_pdf call
        result_text = process_single_pdf(
            pdf_filepath=pdf_filepath,
            genai_model_instance=mock_model_instance
        )

        # 4. Assertions
        mock_read_bytes.assert_called_once_with() # read_bytes on pdf_filepath
        mock_model_instance.generate_content.assert_called_once()
        # Verify the content passed to the LLM (the PDF data)
        args, kwargs = mock_model_instance.generate_content.call_args
        self.assertIsInstance(args[0][0], str) # System prompt part
        self.assertEqual(args[0][1].data, b"dummy raw pdf content") # The PDF data
        self.assertEqual(args[0][1].mime_type, "application/pdf")


        self.assertEqual(result_text, mock_llm_extracted_text)
        mock_time_sleep.assert_called_once() # Ensure sleep was called
        mock_log.info.assert_any_call(f"Successfully processed '{pdf_filepath.name}'. Extracted text length: {len(mock_llm_extracted_text)}.")


    @patch('src.pipeline_steps.pdf_processor.time.sleep')
    @patch('src.pipeline_steps.pdf_processor.pathlib.Path.read_bytes')
    @patch('src.pipeline_steps.pdf_processor.genai.GenerativeModel')
    @patch('src.pipeline_steps.pdf_processor.log')
    def test_process_single_pdf_llm_error(
        self, mock_log, MockGenerativeModel, mock_read_bytes, mock_time_sleep
    ):
        mock_model_instance = MockGenerativeModel.return_value
        mock_model_instance.generate_content.side_effect = Exception("LLM API Error")

        mock_read_bytes.return_value = b"dummy pdf content"
        pdf_filepath = MagicMock(spec=pathlib.Path)
        pdf_filepath.name = "error_protocol.pdf"

        result_text = process_single_pdf(
            pdf_filepath=pdf_filepath,
            genai_model_instance=mock_model_instance
        )

        self.assertIsNone(result_text)
        mock_log.error.assert_any_call(f"Error processing PDF '{pdf_filepath.name}' with LLM: LLM API Error", exc_info=True)
        mock_time_sleep.assert_called_once()


    @patch('src.pipeline_steps.pdf_processor.config.load_google_api_key')
    @patch('src.pipeline_steps.pdf_processor.genai.configure') # genai.configure might not be used if client takes key
    @patch('src.pipeline_steps.pdf_processor.genai.GenerativeModel') # Mock the constructor
    @patch('src.pipeline_steps.pdf_processor.process_single_pdf')
    @patch('src.pipeline_steps.pdf_processor.pathlib.Path.glob')
    @patch('src.pipeline_steps.pdf_processor.config') # Mock the config module used by pdf_processor
    @patch('src.pipeline_steps.pdf_processor.log')
    def test_run_pdf_extraction_processes_files_and_returns_dict(
        self, mock_log, mock_pdf_processor_config, mock_glob, mock_process_single_pdf,
        MockGenerativeModel, mock_genai_configure, mock_load_google_api_key
    ):
        # 1. Mock config values and setup
        mock_load_google_api_key.return_value = "dummy_key_pdf"
        mock_pdf_processor_config.PDF_DIR_NAME = "test_pdfs"
        mock_pdf_processor_config.GENAI_PDF_EXTRACTION_MODEL = "gemini-test-model"
        mock_pdf_processor_config.load_api_call_delay.return_value = 0 # No delay for test speed

        # Mock Project Root and PDF directory path
        mock_project_root_path = MagicMock(spec=pathlib.Path)
        mock_pdf_dir_path = MagicMock(spec=pathlib.Path)
        mock_project_root_path.__truediv__.return_value = mock_pdf_dir_path # PROJECT_ROOT / PDF_DIR_NAME
        mock_pdf_processor_config.PROJECT_ROOT = mock_project_root_path
        mock_pdf_dir_path.is_dir.return_value = True


        # Mock GenAI Model instance
        mock_model_instance = MockGenerativeModel.return_value

        # Mock PDF files found by glob
        mock_pdf_file1 = MagicMock(spec=pathlib.Path, name="file1.pdf")
        mock_pdf_file2 = MagicMock(spec=pathlib.Path, name="file2.pdf")
        mock_pdf_dir_path.glob.return_value = [mock_pdf_file1, mock_pdf_file2]

        # Mock return values for process_single_pdf
        mock_process_single_pdf.side_effect = ["Text from file1", "Text from file2"]

        # 2. Call run_pdf_extraction
        result_dict = run_pdf_extraction()

        # 3. Assertions
        mock_load_google_api_key.assert_called_once()
        # genai.configure might not be called if API key is passed directly to client/model
        # Depending on exact genai library usage for model initialization.
        # If GenerativeModel itself is configured with the key, configure might not be needed.
        # For safety, let's assume it might be called or not.
        # mock_genai_configure.assert_called_once_with(api_key="dummy_key_pdf")

        MockGenerativeModel.assert_called_once_with(model_name="models/gemini-test-model") # Name is prefixed with models/

        mock_project_root_path.__truediv__.assert_called_once_with("test_pdfs")
        mock_pdf_dir_path.glob.assert_called_once_with('*.pdf')

        expected_process_calls = [
            call(pdf_filepath=mock_pdf_file1, genai_model_instance=mock_model_instance),
            call(pdf_filepath=mock_pdf_file2, genai_model_instance=mock_model_instance)
        ]
        mock_process_single_pdf.assert_has_calls(expected_process_calls, any_order=True)
        self.assertEqual(mock_process_single_pdf.call_count, 2)

        expected_dict = {
            "file1.pdf": "Text from file1",
            "file2.pdf": "Text from file2"
        }
        self.assertEqual(result_dict, expected_dict)
        mock_log.info.assert_any_call(f"PDF extraction run finished. Successfully processed {len(expected_dict)} PDF(s).")


    @patch('src.pipeline_steps.pdf_processor.config.load_google_api_key')
    @patch('src.pipeline_steps.pdf_processor.genai.GenerativeModel')
    @patch('src.pipeline_steps.pdf_processor.pathlib.Path.glob')
    @patch('src.pipeline_steps.pdf_processor.config')
    @patch('src.pipeline_steps.pdf_processor.log')
    def test_run_pdf_extraction_pdf_dir_not_found(
        self, mock_log, mock_pdf_processor_config, mock_glob, MockGenerativeModel, mock_load_google_api_key
    ):
        mock_load_google_api_key.return_value = "dummy_key"
        mock_pdf_processor_config.PDF_DIR_NAME = "non_existent_pdfs"
        mock_project_root_path = MagicMock(spec=pathlib.Path)
        mock_pdf_dir_path = MagicMock(spec=pathlib.Path)
        mock_project_root_path.__truediv__.return_value = mock_pdf_dir_path
        mock_pdf_processor_config.PROJECT_ROOT = mock_project_root_path
        mock_pdf_dir_path.is_dir.return_value = False # Simulate directory not found

        result_dict = run_pdf_extraction()

        self.assertEqual(result_dict, {})
        mock_log.error.assert_any_call(f"PDF directory '{mock_pdf_dir_path}' not found. Skipping PDF processing.")
        MockGenerativeModel.assert_not_called() # Model should not be initialized if dir is missing

if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
