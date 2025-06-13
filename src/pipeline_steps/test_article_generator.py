import unittest
from unittest.mock import patch, MagicMock, call
import pathlib
import json
import tempfile
import logging

# Ensure src directory is in sys.path for module imports from src
import sys
project_root_for_test = pathlib.Path(__file__).resolve().parent.parent.parent
if str(project_root_for_test) not in sys.path:
    sys.path.insert(0, str(project_root_for_test))

from src.pipeline_steps import article_generator
from src import config as app_config # Use an alias to avoid confusion with local 'config' variables

# Disable logging for most tests to keep output clean, can be enabled for debugging
# logging.disable(logging.CRITICAL)

class TestArticleGenerator(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.mock_project_root = pathlib.Path(self.temp_dir.name)

        # Create necessary subdirectories within the temporary project root
        (self.mock_project_root / app_config.FILTERED_JSON_DIR_NAME).mkdir(parents=True, exist_ok=True)

        # Store original values to restore them in tearDown if necessary, though patching should handle most.
        self.original_project_root = app_config.PROJECT_ROOT
        # The critical part is ensuring the module under test uses the mocked path.
        # This is primarily handled by @patch('src.pipeline_steps.article_generator.config.PROJECT_ROOT')
        # but for direct config access from the test itself, we might also want to set it.
        app_config.PROJECT_ROOT = self.mock_project_root

        # Ensure other config values are as expected for tests, e.g. model names.
        # These are usually constants, so just ensuring they are available.
        self.test_model_name = "test-model"
        self.test_selection_prompt = "Test prompt: {json_data}"
        app_config.GENAI_PDF_EXTRACTION_MODEL = self.test_model_name # Override if necessary
        app_config.GENAI_TOPIC_SELECTION_PROMPT = self.test_selection_prompt # Override if necessary
        app_config.CHROMA_DB_DIR_NAME = "test_chroma_db" # Ensure test isolation for db path
        app_config.CHROMA_COLLECTION_NAME = "test_collection"


    def tearDown(self):
        self.temp_dir.cleanup()
        app_config.PROJECT_ROOT = self.original_project_root # Restore original project root

    # --- Unit Tests for get_relevant_tops_with_llm ---

    @patch('src.pipeline_steps.article_generator.json.loads')
    @patch('src.pipeline_steps.article_generator.genai.Client') # Mock the client constructor if get_relevant_tops_with_llm creates its own
    def test_get_relevant_tops_with_llm_success(self, mock_genai_client_constructor, mock_json_loads):
        mock_genai_client = MagicMock() # This will be the instance returned by the (potentially mocked) constructor or passed in

        # If genai_client is passed as an argument to get_relevant_tops_with_llm:
        # We don't need to mock the constructor, just pass the mock_genai_client instance.
        # The function signature is: get_relevant_tops_with_llm(..., genai_client, ...)

        mock_response_text = {"title": "Test Title", "datum": "2023-01-01", "tops": [{"top_id": "1", "content": "Relevant TOP"}]}
        mock_response_obj = MagicMock()
        mock_response_obj.text = json.dumps(mock_response_text)

        mock_genai_client.generate_content.return_value = mock_response_obj
        mock_json_loads.return_value = mock_response_text # Ensure json.loads returns the dict

        protocol_title = "Test Title"
        protocol_date = "2023-01-01"
        current_tops = [{"top_id": "1", "content": "Original Content"}]

        result = article_generator.get_relevant_tops_with_llm(
            protocol_title, protocol_date, current_tops,
            mock_genai_client, self.test_model_name, self.test_selection_prompt
        )

        self.assertEqual(result, mock_response_text)

        expected_llm_input_data = {
            "title": protocol_title, "datum": protocol_date, "tops": current_tops
        }
        # The prompt is [template, json_string_of_input_data]
        mock_genai_client.generate_content.assert_called_once()
        args, kwargs = mock_genai_client.generate_content.call_args

        self.assertEqual(kwargs['model'], self.test_model_name)
        self.assertIn(self.test_selection_prompt, kwargs['contents'][0]) # Prompt template is the first part
        self.assertEqual(json.loads(kwargs['contents'][1]), expected_llm_input_data) # JSON data is the second part

        # Check generation_config
        generation_config = kwargs['generation_config']
        self.assertEqual(generation_config.response_mime_type, "application/json")
        mock_json_loads.assert_called_once_with(mock_response_obj.text)


    @patch('src.pipeline_steps.article_generator.log.error') # Mocking the logger instance's error method
    def test_get_relevant_tops_with_llm_api_error(self, mock_log_error):
        mock_genai_client = MagicMock()
        mock_genai_client.generate_content.side_effect = Exception("API Error")

        result = article_generator.get_relevant_tops_with_llm(
            "Title", "Date", [], mock_genai_client, self.test_model_name, self.test_selection_prompt
        )
        self.assertIsNone(result)
        mock_log_error.assert_called_once()
        self.assertIn("Error calling GenAI model for TOP selection", mock_log_error.call_args[0][0])

    @patch('src.pipeline_steps.article_generator.log.error') # Mocking the logger instance's error method
    @patch('src.pipeline_steps.article_generator.json.loads')
    def test_get_relevant_tops_with_llm_json_error(self, mock_json_loads, mock_log_error):
        mock_genai_client = MagicMock()
        mock_response_obj = MagicMock()
        mock_response_obj.text = "invalid json"
        mock_genai_client.generate_content.return_value = mock_response_obj

        mock_json_loads.side_effect = json.JSONDecodeError("err", "doc", 0)

        result = article_generator.get_relevant_tops_with_llm(
            "Title", "Date", [], mock_genai_client, self.test_model_name, self.test_selection_prompt
        )
        self.assertIsNone(result)
        mock_log_error.assert_called_once()
        self.assertIn("Error decoding JSON response from LLM", mock_log_error.call_args[0][0])

    # --- Integration Tests for run_article_generation ---

    @patch('src.pipeline_steps.article_generator.config', new_callable=MagicMock) # Mock the entire config module used by article_generator
    @patch('src.pipeline_steps.article_generator.chromadb.PersistentClient')
    @patch('src.pipeline_steps.article_generator.genai.Client')
    def test_run_article_generation_e2e(self, mock_genai_client_constructor, mock_chroma_client_constructor, mock_config_module):

        # Setup the mock_config_module that article_generator will use
        mock_config_module.PROJECT_ROOT = self.mock_project_root
        mock_config_module.FILTERED_JSON_DIR_NAME = "filtered_json_files"
        mock_config_module.GENAI_PDF_EXTRACTION_MODEL = self.test_model_name
        mock_config_module.GENAI_TOPIC_SELECTION_PROMPT = self.test_selection_prompt
        mock_config_module.CHROMA_DB_DIR_NAME = "test_chroma_db"
        mock_config_module.CHROMA_COLLECTION_NAME = "test_collection"
        # Mock load_google_api_key if it's called within run_article_generation
        mock_config_module.load_google_api_key.return_value = "test_api_key"


        # Mock ChromaDB
        mock_chroma_collection = MagicMock()
        mock_chroma_client_constructor.return_value.get_or_create_collection.return_value = mock_chroma_collection

        chroma_get_return_value = {
            'ids': ['f1_t1', 'f1_t2', 'f2_t1', 'f3_t1_no_metadata_source'],
            'documents': ['Content 1.1', 'Content 1.2', 'Content 2.1', 'Content 3.1'],
            'metadatas': [
                {'source_file': 'file1.json', 'top_id': 'T1', 'title': 'Proto 1', 'datum': '2023-10-01'},
                {'source_file': 'file1.json', 'top_id': 'T2', 'title': 'Proto 1', 'datum': '2023-10-01'},
                {'source_file': 'file2.json', 'top_id': 'T1', 'title': 'Proto 2', 'datum': '2023-10-05'},
                {'top_id': 'T_NO_SOURCE', 'title': 'Proto 3 No Source', 'datum': '2023-10-06'} # Missing source_file
            ]
        }
        mock_chroma_collection.get.return_value = chroma_get_return_value

        # Mock GenAI Client
        mock_genai_instance = MagicMock()
        mock_genai_client_constructor.return_value = mock_genai_instance

        expected_output_proto1 = {
            "title": "Proto 1", "datum": "2023-10-01",
            "tops": [{"top_id": "T1", "content": "Relevant Content 1.1"}] # Simulating selection
        }
        expected_output_proto2 = {
            "title": "Proto 2", "datum": "2023-10-05",
            "tops": [] # Simulating no relevant TOPs
        }

        def genai_side_effect(*args, **kwargs):
            json_input_string = kwargs['contents'][1] # Data is the second element
            input_data = json.loads(json_input_string)
            if input_data['title'] == 'Proto 1':
                response = MagicMock()
                response.text = json.dumps(expected_output_proto1)
                return response
            elif input_data['title'] == 'Proto 2':
                response = MagicMock()
                response.text = json.dumps(expected_output_proto2)
                return response
            # Should not be called for Proto 3 as it's missing source_file
            return MagicMock(text=json.dumps({"title": "Error", "datum": "Error", "tops": []}))

        mock_genai_instance.generate_content.side_effect = genai_side_effect

        # Call the function to test
        article_generator.run_article_generation(start_date='2023-10-01', end_date='2023-10-05')

        # Assert ChromaDB calls
        mock_chroma_collection.get.assert_called_once()
        _, chroma_kwargs = mock_chroma_collection.get.call_args
        self.assertEqual(chroma_kwargs['where'], {"$and": [{"datum": {"$gte": '2023-10-01'}}, {"datum": {"$lte": '2023-10-05'}}]})
        self.assertEqual(chroma_kwargs['include'], ['documents', 'metadatas', 'ids'])


        # Assert GenAI calls (should be called for Proto 1 and Proto 2)
        self.assertEqual(mock_genai_instance.generate_content.call_count, 2)

        # Check calls made to GenAI (order might not be guaranteed, so check contents)
        call_args_list = mock_genai_instance.generate_content.call_args_list
        # call_args_list[0] is Call object, call_args_list[0][1] is kwargs

        # Verify data sent for Proto 1
        proto1_found_in_calls = False
        for call_obj in call_args_list:
            input_data = json.loads(call_obj[1]['contents'][1])
            if input_data['title'] == 'Proto 1':
                proto1_found_in_calls = True
                self.assertEqual(len(input_data['tops']), 2) # Proto 1 had 2 TOPs from Chroma
                self.assertEqual(input_data['tops'][0]['content'], 'Content 1.1')
        self.assertTrue(proto1_found_in_calls, "GenAI call for Proto 1 not found or data mismatch")

        # Verify data sent for Proto 2
        proto2_found_in_calls = False
        for call_obj in call_args_list:
            input_data = json.loads(call_obj[1]['contents'][1])
            if input_data['title'] == 'Proto 2':
                proto2_found_in_calls = True
                self.assertEqual(len(input_data['tops']), 1) # Proto 2 had 1 TOP from Chroma
                self.assertEqual(input_data['tops'][0]['content'], 'Content 2.1')
        self.assertTrue(proto2_found_in_calls, "GenAI call for Proto 2 not found or data mismatch")


        # Assert Output Files
        filtered_dir = self.mock_project_root / mock_config_module.FILTERED_JSON_DIR_NAME
        file1_output_path = filtered_dir / "file1_filtered.json"
        file2_output_path = filtered_dir / "file2_filtered.json"

        self.assertTrue(file1_output_path.exists())
        self.assertTrue(file2_output_path.exists())

        with open(file1_output_path, 'r', encoding='utf-8') as f:
            file1_data = json.load(f)
        self.assertEqual(file1_data, expected_output_proto1)

        with open(file2_output_path, 'r', encoding='utf-8') as f:
            file2_data = json.load(f)
        self.assertEqual(file2_data, expected_output_proto2)

        # Ensure file for Proto 3 (with no source_file) was not created
        file3_output_path = filtered_dir / "_filtered.json" # if source_file was None or empty, Path("").stem is ""
        self.assertFalse(file3_output_path.exists(), "File for protocol with missing source_file should not be created")


    @patch('src.pipeline_steps.article_generator.config', new_callable=MagicMock)
    @patch('src.pipeline_steps.article_generator.chromadb.PersistentClient')
    @patch('src.pipeline_steps.article_generator.genai.Client')
    def test_run_article_generation_date_filters(self, mock_genai_client_constructor, mock_chroma_client_constructor, mock_config_module):
        mock_config_module.PROJECT_ROOT = self.mock_project_root
        mock_config_module.FILTERED_JSON_DIR_NAME = "filtered_json_files"
        mock_config_module.GENAI_PDF_EXTRACTION_MODEL = self.test_model_name
        mock_config_module.GENAI_TOPIC_SELECTION_PROMPT = self.test_selection_prompt
        mock_config_module.CHROMA_DB_DIR_NAME = "test_chroma_db"
        mock_config_module.CHROMA_COLLECTION_NAME = "test_collection"
        mock_config_module.load_google_api_key.return_value = "test_api_key"

        mock_chroma_collection = MagicMock()
        mock_chroma_client_constructor.return_value.get_or_create_collection.return_value = mock_chroma_collection

        # Simplified GenAI mock for this test
        mock_genai_instance = MagicMock()
        mock_genai_client_constructor.return_value = mock_genai_instance
        mock_genai_instance.generate_content.return_value = MagicMock(text=json.dumps({"title": "", "datum": "", "tops": []}))

        # Test with start_date only
        mock_chroma_collection.get.return_value = {'ids': [], 'documents': [], 'metadatas': []} # Reset for call count
        article_generator.run_article_generation(start_date='2023-10-04')
        mock_chroma_collection.get.assert_called_with(where={'datum': {'$gte': '2023-10-04'}}, include=['documents', 'metadatas', 'ids'])

        # Test with end_date only
        mock_chroma_collection.get.return_value = {'ids': [], 'documents': [], 'metadatas': []}
        article_generator.run_article_generation(end_date='2023-10-02')
        mock_chroma_collection.get.assert_called_with(where={'datum': {'$lte': '2023-10-02'}}, include=['documents', 'metadatas', 'ids'])

        # Test with no dates (should pass None or {} as filter)
        mock_chroma_collection.get.return_value = {'ids': [], 'documents': [], 'metadatas': []}
        article_generator.run_article_generation()
        mock_chroma_collection.get.assert_called_with(where=None, include=['documents', 'metadatas', 'ids'])


    @patch('src.pipeline_steps.article_generator.config', new_callable=MagicMock)
    @patch('src.pipeline_steps.article_generator.chromadb.PersistentClient')
    @patch('src.pipeline_steps.article_generator.genai.Client')
    @patch('src.pipeline_steps.article_generator.get_relevant_tops_with_llm') # Mock the LLM call function directly
    def test_run_article_generation_skip_existing(self, mock_get_relevant_tops_llm, mock_genai_client_constructor, mock_chroma_client_constructor, mock_config_module):
        mock_config_module.PROJECT_ROOT = self.mock_project_root
        mock_config_module.FILTERED_JSON_DIR_NAME = "filtered_json_files"
        # ... other config mocks ...
        mock_config_module.GENAI_PDF_EXTRACTION_MODEL = self.test_model_name
        mock_config_module.GENAI_TOPIC_SELECTION_PROMPT = self.test_selection_prompt
        mock_config_module.CHROMA_DB_DIR_NAME = "test_chroma_db"
        mock_config_module.CHROMA_COLLECTION_NAME = "test_collection"
        mock_config_module.load_google_api_key.return_value = "test_api_key"


        mock_chroma_collection = MagicMock()
        mock_chroma_client_constructor.return_value.get_or_create_collection.return_value = mock_chroma_collection

        # Simulate two protocols from ChromaDB
        mock_chroma_collection.get.return_value = {
            'ids': ['f1_t1', 'f2_t1'],
            'documents': ['Content 1.1', 'Content 2.1'],
            'metadatas': [
                {'source_file': 'file1.json', 'top_id': 'T1', 'title': 'Proto 1', 'datum': '2023-10-01'},
                {'source_file': 'file2.json', 'top_id': 'T1', 'title': 'Proto 2', 'datum': '2023-10-05'}
            ]
        }

        # Pre-create an output file for 'file1.json'
        filtered_dir = self.mock_project_root / mock_config_module.FILTERED_JSON_DIR_NAME
        existing_output_path = filtered_dir / "file1_filtered.json"
        with open(existing_output_path, 'w') as f:
            json.dump({"title": "Proto 1", "datum": "2023-10-01", "tops": []}, f)

        # Mock the LLM call to see if it's invoked
        mock_get_relevant_tops_llm.return_value = {"title": "Proto 2", "datum": "2023-10-05", "tops": [{"top_id":"T1", "content":"Selected Content"}]}

        article_generator.run_article_generation()

        # Assert that get_relevant_tops_with_llm was called only once (for file2.json)
        mock_get_relevant_tops_llm.assert_called_once()

        # Verify the call was for Proto 2 data
        args, _ = mock_get_relevant_tops_llm.call_args
        self.assertEqual(args[0], "Proto 2") # protocol_title
        self.assertEqual(len(args[2]), 1)     # current_tops for Proto 2
        self.assertEqual(args[2][0]['content'], 'Content 2.1')

        # Ensure the existing file was untouched (optional, but good check)
        with open(existing_output_path, 'r') as f:
            existing_data = json.load(f)
        self.assertEqual(existing_data, {"title": "Proto 1", "datum": "2023-10-01", "tops": []})

        # Ensure new file for Proto 2 was created by the mocked LLM call
        file2_output_path = filtered_dir / "file2_filtered.json"
        self.assertTrue(file2_output_path.exists())
        with open(file2_output_path, 'r') as f:
            file2_data = json.load(f)
        self.assertEqual(file2_data["title"], "Proto 2")


if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
