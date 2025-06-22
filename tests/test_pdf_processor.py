import unittest
from unittest.mock import patch, MagicMock, call
import pathlib
import sys
import uuid # Added
import json # Added for json.dumps in test
import chromadb # Added for type hinting

# Add project root to sys.path to allow src imports
project_root_for_test = pathlib.Path(__file__).resolve().parent.parent
if str(project_root_for_test) not in sys.path:
    sys.path.insert(0, str(project_root_for_test))

# Import the functions and variables to be tested
from src.pipeline_steps.pdf_processor import process_single_pdf, run_pdf_extraction_and_storage, PROMPT_TEXT as PDF_PROCESSOR_PROMPT_TEXT
from src import config # For accessing config constants in assertions

# db_loader is imported by pdf_processor, so we will patch it there.

class TestPDFProcessingAndChromaIngestion(unittest.TestCase):

    @patch('src.pipeline_steps.pdf_processor.time.sleep')
    @patch('src.pipeline_steps.pdf_processor.pathlib.Path.read_bytes')
    @patch('src.pipeline_steps.pdf_processor.genai.GenerativeModel')
    @patch('src.pipeline_steps.pdf_processor.uuid.uuid4')
    @patch('src.pipeline_steps.pdf_processor.db_loader') # Mocking the db_loader module used by pdf_processor
    def test_process_single_pdf_extracts_and_adds_to_chroma(
        self, mock_db_loader, mock_uuid, MockGenerativeModel, mock_read_bytes, mock_time_sleep
    ):
        # 0. Mock time.sleep
        mock_time_sleep.return_value = None

        # 1. Setup mock GenAI Model instance
        mock_model_instance = MockGenerativeModel.return_value
        llm_response_data = {
            "title": "Test Protocol",
            "datum": "2023-07-15",
            "tops": [
                "Content for TOP 1.a",
                "Content for TOP 2"
            ]
        }
        mock_llm_response = MagicMock()
        mock_llm_response.text = json.dumps(llm_response_data)
        mock_model_instance.generate_content.return_value = mock_llm_response

        # 2. Mock PDF file interactions
        mock_read_bytes.return_value = b"dummy pdf content"
        pdf_filepath = MagicMock(spec=pathlib.Path)
        pdf_filepath.name = "dummy_protocol.pdf"
        pdf_filepath.stem = "dummy_protocol" # Though stem is not used in new version

        # 3. Mock UUID generation
        mock_uuid.side_effect = [
            uuid.UUID('11111111-1111-1111-1111-111111111111'),
            uuid.UUID('22222222-2222-2222-2222-222222222222')
        ]

        # 4. Mock ChromaDB collection
        mock_chroma_collection = MagicMock(spec=chromadb.api.models.Collection.Collection)
        # Mock the return of add_top_to_chromadb to simulate success
        mock_db_loader.add_top_to_chromadb.return_value = True


        # 5. Call process_single_pdf
        process_single_pdf(
            pdf_filepath=pdf_filepath,
            genai_model_instance=mock_model_instance,
            prompt=PDF_PROCESSOR_PROMPT_TEXT,
            chroma_collection=mock_chroma_collection
        )

        # 6. Assertions
        mock_model_instance.generate_content.assert_called_once()
        # Check arguments of generate_content if necessary, e.g. prompt used

        expected_calls_to_db = [
            call(
                top_id='11111111-1111-1111-1111-111111111111',
                document="Content for TOP 1.a",
                metadata={"protocol_title": "Test Protocol", "protocol_date": "2023-07-15", "top_sequence_in_protocol": 1},
                collection=mock_chroma_collection
            ),
            call(
                top_id='22222222-2222-2222-2222-222222222222',
                document="Content for TOP 2",
                metadata={"protocol_title": "Test Protocol", "protocol_date": "2023-07-15", "top_sequence_in_protocol": 2},
                collection=mock_chroma_collection
            )
        ]
        mock_db_loader.add_top_to_chromadb.assert_has_calls(expected_calls_to_db, any_order=False)
        self.assertEqual(mock_db_loader.add_top_to_chromadb.call_count, 2)
        mock_time_sleep.assert_called_once() # Ensure sleep was called


    @patch('src.pipeline_steps.pdf_processor.config.load_google_api_key')
    @patch('src.pipeline_steps.pdf_processor.genai.configure')
    @patch('src.pipeline_steps.pdf_processor.genai.GenerativeModel')
    @patch('src.pipeline_steps.pdf_processor.db_loader.initialize_chroma_collection')
    @patch('src.pipeline_steps.pdf_processor.process_single_pdf')
    @patch('src.pipeline_steps.pdf_processor.pathlib.Path.glob')
    @patch('src.pipeline_steps.pdf_processor.config.PROJECT_ROOT', new_callable=MagicMock(spec=pathlib.Path)) # Mock project root
    def test_run_pdf_extraction_and_storage(
        self, mock_project_root, mock_glob, mock_process_single_pdf,
        mock_initialize_chroma, MockGenerativeModel, mock_genai_configure, mock_load_google_api_key
    ):
        # 1. Mock config values and setup
        mock_load_google_api_key.return_value = "dummy_key"
        # Mock PROJECT_ROOT to control pdf_dir path
        dummy_pdf_dir = MagicMock(spec=pathlib.Path)
        dummy_pdf_dir.is_dir.return_value = True # Ensure pdf_dir is seen as a directory
        mock_project_root / config.PDF_DIR_NAME = dummy_pdf_dir # Simulate path concatenation

        mock_model_instance = MockGenerativeModel.return_value
        mock_chroma_collection_instance = MagicMock(spec=chromadb.api.models.Collection.Collection)
        mock_initialize_chroma.return_value = mock_chroma_collection_instance

        mock_pdf_file1 = MagicMock(spec=pathlib.Path, name="file1.pdf")
        mock_pdf_file2 = MagicMock(spec=pathlib.Path, name="file2.pdf")
        # Configure the mock for pdf_dir.glob
        (mock_project_root / config.PDF_DIR_NAME).glob.return_value = [mock_pdf_file1, mock_pdf_file2]


        # 2. Call run_pdf_extraction_and_storage
        run_pdf_extraction_and_storage()

        # 3. Assertions
        mock_load_google_api_key.assert_called_once()
        mock_genai_configure.assert_called_once_with(api_key="dummy_key")
        MockGenerativeModel.assert_called_once_with(config.GENAI_PDF_EXTRACTION_MODEL)

        # Use the mocked config.PROJECT_ROOT for assertion if it's passed to initialize_chroma_collection
        mock_initialize_chroma.assert_called_once_with(
            db_path_name=config.CHROMA_DB_DIR_NAME,
            collection_name=config.CHROMA_COLLECTION_NAME,
            project_root=mock_project_root # Ensure this matches how it's called
        )

        (mock_project_root / config.PDF_DIR_NAME).glob.assert_called_once_with('*.pdf')

        expected_process_calls = [
            call(pdf_filepath=mock_pdf_file1, genai_model_instance=mock_model_instance, prompt=PDF_PROCESSOR_PROMPT_TEXT, chroma_collection=mock_chroma_collection_instance),
            call(pdf_filepath=mock_pdf_file2, genai_model_instance=mock_model_instance, prompt=PDF_PROCESSOR_PROMPT_TEXT, chroma_collection=mock_chroma_collection_instance)
        ]
        mock_process_single_pdf.assert_has_calls(expected_process_calls, any_order=True) # Order might not be guaranteed by glob
        self.assertEqual(mock_process_single_pdf.call_count, 2)

if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
