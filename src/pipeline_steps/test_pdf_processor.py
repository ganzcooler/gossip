import unittest
from unittest.mock import patch, MagicMock, call # Ensure 'call' is imported
import pathlib
import json
import tempfile
import sys
import time # Keep time for the sleep mock if process_single_pdf still has it

# Add project root to sys.path to allow src imports
project_root_for_test = pathlib.Path(__file__).resolve().parent.parent.parent
if str(project_root_for_test) not in sys.path:
    sys.path.insert(0, str(project_root_for_test))

from src.pipeline_steps.pdf_processor import process_single_pdf, PROMPT_TEXT as PDF_PROCESSOR_PROMPT_TEXT
from src import config # For accessing config.GENAI_TOP_RELEVANCE_PROMPT

class TestPDFProcessorRelevance(unittest.TestCase):

    @patch('src.pipeline_steps.pdf_processor.time.sleep')
    @patch('src.pipeline_steps.pdf_processor.pathlib.Path.read_bytes')
    # Removed @patch for get_top_relevance as it's no longer called
    @patch('src.pipeline_steps.pdf_processor.genai.GenerativeModel')
    def test_relevance_added_to_tops(self, MockGenerativeModel, mock_read_bytes, mock_time_sleep): # mock_get_top_relevance removed
        # 0. Mock time.sleep to avoid delays during testing
        mock_time_sleep.return_value = None

        # 1. Setup mock GenAI Model instance for PDF extraction
        mock_model_instance = MockGenerativeModel.return_value

        mock_llm_extraction_response = MagicMock()
        # The initial LLM call is now expected to return the 'relevant' field directly
        initial_extraction_data = {
            "title": "Test Committee",
            "datum": "2024-01-01",
            "tops": [
                {"top_id": "1", "content": "Content for TOP 1 that is relevant", "relevant": True},
                {"top_id": "2", "content": "Content for TOP 2 that is not relevant", "relevant": False}
            ]
        }
        mock_llm_extraction_response.text = json.dumps(initial_extraction_data)
        mock_model_instance.generate_content.return_value = mock_llm_extraction_response

        # 2. get_top_relevance is no longer called, so no mock setup needed for it here.

        # 3. Mock PDF file interactions
        mock_read_bytes.return_value = b"dummy pdf content"

        # 4. Use TemporaryDirectory for json_output_dir
        with tempfile.TemporaryDirectory() as tmpdir:
            json_output_dir = pathlib.Path(tmpdir)
            # Create a dummy pdf_filepath object, ensuring it has a 'stem' attribute
            pdf_filepath = MagicMock(spec=pathlib.Path)
            pdf_filepath.name = "dummy_protocol.pdf"
            pdf_filepath.stem = "dummy_protocol"

            # Ensure read_bytes is associated with this specific mock path object if needed by patching Path constructor
            # For now, the direct patch on 'src.pipeline_steps.pdf_processor.pathlib.Path.read_bytes' should be global enough.

            # 5. Call process_single_pdf
            process_single_pdf(
                pdf_filepath=pdf_filepath,
                json_output_dir=json_output_dir,
                genai_model_instance=mock_model_instance, # Pass the mocked model instance
                prompt=PDF_PROCESSOR_PROMPT_TEXT # Use the imported prompt
            )

            # 6. Assertions
            output_json_path = json_output_dir / (pdf_filepath.stem + '.json')
            self.assertTrue(output_json_path.exists(), f"Output JSON file not found at {output_json_path}")

            with open(output_json_path, 'r', encoding='utf-8') as f:
                saved_data = json.load(f)

            self.assertEqual(saved_data.get('title'), "Test Committee")
            self.assertIn('tops', saved_data)
            self.assertEqual(len(saved_data['tops']), 2)

            top1_data = saved_data['tops'][0]
            top2_data = saved_data['tops'][1]

            self.assertEqual(top1_data.get('content'), "Content for TOP 1 that is relevant")
            self.assertTrue(top1_data.get('relevant'))

            self.assertEqual(top2_data.get('content'), "Content for TOP 2 that is not relevant")
            self.assertFalse(top2_data.get('relevant'))

            # Assertions for get_top_relevance calls are removed as it's no longer called.

            # Verify that the main LLM call for extraction happened once on the mock_model_instance.
            self.assertEqual(mock_model_instance.generate_content.call_count, 1)


if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
