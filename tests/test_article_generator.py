import unittest
from unittest.mock import patch, MagicMock, call # Ensure 'call' is imported
import pathlib
import json
import logging
import chromadb # For spec

# Ensure src directory is in sys.path for module imports from src
import sys
project_root_for_test = pathlib.Path(__file__).resolve().parent.parent
if str(project_root_for_test) not in sys.path:
    sys.path.insert(0, str(project_root_for_test))

from src.pipeline_steps import article_generator
# Use an alias to avoid confusion with local 'config' variables in test methods
from src import config as app_config_module
# Import db_loader for patching its methods
from src.pipeline_steps import db_loader

# Disable logging for most tests to keep output clean
# logging.disable(logging.CRITICAL)

class TestArticleGenerator(unittest.TestCase):

    def setUp(self):
        # We don't need a real temp_dir for project_root if config is properly mocked where PROJECT_ROOT is used.
        # However, if any part of the code under test *directly* accesses app_config.PROJECT_ROOT for path construction
        # without it being passed as an argument or part of a patched object, this might still be relevant.
        # For now, relying on @patch('src.pipeline_steps.article_generator.config', ...) for most cases.

        # Store original values to restore them in tearDown if necessary.
        # This is good practice, though with proper patching it might not always be strictly needed.
        self.original_genai_article_model = app_config_module.GENAI_ARTICLE_GENERATION_MODEL
        self.original_selection_prompt = app_config_module.GENAI_TOPIC_SELECTION_PROMPT
        self.original_similar_docs_count = app_config_module.SIMILAR_DOCS_COUNT

        # Set test-specific values (can also be done via the mock_config_module in each test)
        app_config_module.GENAI_ARTICLE_GENERATION_MODEL = "test-article-gen-model"
        app_config_module.GENAI_TOPIC_SELECTION_PROMPT = "Test Select: {json_data}"
        app_config_module.SIMILAR_DOCS_COUNT = 2 # Example value

    def tearDown(self):
        # Restore original config values
        app_config_module.GENAI_ARTICLE_GENERATION_MODEL = self.original_genai_article_model
        app_config_module.GENAI_TOPIC_SELECTION_PROMPT = self.original_selection_prompt
        app_config_module.SIMILAR_DOCS_COUNT = self.original_similar_docs_count


    # --- Unit Tests for get_relevant_tops_with_llm ---
    # These tests are largely the same as they test a helper function.
    # Ensure model name is used from app_config_module.GENAI_ARTICLE_GENERATION_MODEL

    @patch('src.pipeline_steps.article_generator.json.loads')
    def test_get_relevant_tops_with_llm_success(self, mock_json_loads):
        mock_genai_client = MagicMock()
        # Updated mock_response_text to new structure
        mock_response_text = {
            "title": "Test Title",
            "datum": "2023-01-01",
            "tops_evaluation": [{"top_id": "1", "is_selected_relevant": True}]
        }
        mock_response_obj = MagicMock()
        mock_response_obj.text = json.dumps(mock_response_text)

        mock_genai_client.generate_content.return_value = mock_response_obj
        mock_json_loads.return_value = mock_response_text

        protocol_title = "Test Title"
        protocol_date = "2023-01-01"
        current_tops = [{"top_id": "1", "content": "Original Content"}]

        result = article_generator.get_relevant_tops_with_llm(
            protocol_title, protocol_date, current_tops,
            mock_genai_client,
            app_config_module.GENAI_ARTICLE_GENERATION_MODEL, # Use the config value
            app_config_module.GENAI_TOPIC_SELECTION_PROMPT  # Use the config value
        )
        self.assertEqual(result, mock_response_text)
        mock_genai_client.generate_content.assert_called_once()
        _, kwargs = mock_genai_client.generate_content.call_args
        self.assertEqual(kwargs['model'], app_config_module.GENAI_ARTICLE_GENERATION_MODEL)


    @patch('src.pipeline_steps.article_generator.log.error')
    def test_get_relevant_tops_with_llm_api_error(self, mock_log_error):
        mock_genai_client = MagicMock()
        mock_genai_client.generate_content.side_effect = Exception("API Error")
        result = article_generator.get_relevant_tops_with_llm(
            "Title", "Date", [], mock_genai_client, "model", "prompt"
        )
        self.assertIsNone(result)
        mock_log_error.assert_called_once()

    @patch('src.pipeline_steps.article_generator.log.error')
    @patch('src.pipeline_steps.article_generator.json.loads')
    def test_get_relevant_tops_with_llm_json_error(self, mock_json_loads, mock_log_error):
        mock_genai_client = MagicMock()
        mock_response_obj = MagicMock()
        mock_response_obj.text = "invalid json"
        mock_genai_client.generate_content.return_value = mock_response_obj
        mock_json_loads.side_effect = json.JSONDecodeError("err", "doc", 0)
        result = article_generator.get_relevant_tops_with_llm(
            "Title", "Date", [], mock_genai_client, "model", "prompt"
        )
        self.assertIsNone(result)
        mock_log_error.assert_called_once()

    # --- Integration-style Test for run_article_generation ---

    @patch('src.pipeline_steps.article_generator.config', new_callable=MagicMock)
    @patch('src.pipeline_steps.article_generator.db_loader.initialize_chroma_collection')
    @patch('src.pipeline_steps.article_generator.db_loader.get_top_by_id')
    @patch('src.pipeline_steps.article_generator.db_loader.update_top_relevance')
    @patch('src.pipeline_steps.article_generator.db_loader.update_top_references')
    @patch('src.pipeline_steps.article_generator.db_loader.update_article_generated_status')
    @patch('src.pipeline_steps.article_generator.get_relevant_tops_with_llm')
    @patch('src.pipeline_steps.article_generator.genai.Client') # For the client instance used by run_article_generation
    @patch('src.pipeline_steps.article_generator.ollama.embeddings') # Added
    def test_run_article_generation_updates_chromadb(
        self, mock_ollama_embeddings, mock_genai_client_constructor, mock_get_relevant_tops_llm, # Added mock_ollama_embeddings
        mock_update_article_status, mock_update_references, mock_update_relevance,
        mock_get_top_by_id, mock_initialize_chroma, mock_config_module
    ):
        # 1. Configure the overarching mock_config_module
        mock_config_module.SIMILAR_DOCS_COUNT = 1
        mock_config_module.GENAI_ARTICLE_GENERATION_MODEL = "article-gen-model-for-test"
        mock_config_module.GENAI_TOPIC_SELECTION_PROMPT = "Select relevant for test: {json_data}"
        mock_config_module.OLLAMA_EMBEDDING_MODEL = "test-ollama-model"
        mock_config_module.load_google_api_key.return_value = "test_api_key"

        # 2. Mock ChromaDB and db_loader interactions
        mock_chroma_collection = MagicMock(spec=chromadb.api.models.Collection.Collection)
        mock_initialize_chroma.return_value = mock_chroma_collection

        mock_chroma_tops_data = {
            'ids': ['uuidA1', 'uuidA2', 'uuidB1', 'uuidB2'],
            'documents': ['Doc A1 content', 'Doc A2 content', 'Doc B1 content', 'Doc B2 content'],
            'metadatas': [
                {'protocol_title': 'Proto A', 'protocol_date': '2023-01-01', 'top_number': 'A1', 'is_relevant': None},
                {'protocol_title': 'Proto A', 'protocol_date': '2023-01-01', 'top_number': 'A2', 'is_relevant': True, 'references_top_ids': [], 'article_generated': False},
                {'protocol_title': 'Proto B', 'protocol_date': '2023-01-02', 'top_number': 'B1', 'is_relevant': None},
                {'protocol_title': 'Proto B', 'protocol_date': '2023-01-02', 'top_number': 'B2', 'is_relevant': False}
            ]
        }
        mock_chroma_collection.get.return_value = mock_chroma_tops_data

        # Define LLM responses for each protocol based on what it would receive
        mock_llm_eval_proto_A = { # For Proto A, LLM only gets A1
            "title": "Proto A", "datum": "2023-01-01",
            "tops_evaluation": [{"top_id": "A1", "is_selected_relevant": True}]
        }
        mock_llm_eval_proto_B = { # For Proto B, LLM only gets B1
            "title": "Proto B", "datum": "2023-01-02",
            "tops_evaluation": [{"top_id": "B1", "is_selected_relevant": False}]
        }

        # Side effect for get_relevant_tops_with_llm
        processed_protocols_for_llm_input = {} # To store what was actually sent to LLM
        def get_relevant_side_effect(protocol_title, protocol_date, current_tops, genai_client, model_name, selection_prompt_template):
            processed_protocols_for_llm_input[protocol_title] = current_tops
            if protocol_title == "Proto A": return mock_llm_eval_proto_A
            if protocol_title == "Proto B": return mock_llm_eval_proto_B
            return {"title": protocol_title, "datum": protocol_date, "tops_evaluation": []}
        mock_get_relevant_tops_llm.side_effect = get_relevant_side_effect

        # Mock for db_loader.get_top_by_id (called only for A1 because it's marked True by LLM)
        mock_get_top_by_id.return_value = {'id': 'uuidA1', 'document': 'Doc A1 content', 'metadata': mock_chroma_tops_data['metadatas'][0]}

        # Mock for chroma_collection.query (called only for A1)
        mock_chroma_collection.query.return_value = {'ids': [['uuid_ref_for_A1', 'uuidA1']]} # uuidA1 is self

        # Mock ollama.embeddings for the query (called only for A1)
        mock_query_embedding = [0.4, 0.5, 0.6]
        mock_ollama_embeddings.return_value = {"embedding": mock_query_embedding}

        # Mock return values for successful DB updates
        mock_update_relevance.return_value = True
        mock_update_references.return_value = True
        mock_update_article_status.return_value = True

        # 3. Call run_article_generation
        article_generator.run_article_generation()

        # 4. Assertions
        mock_chroma_collection.get.assert_called_once_with(where=None, include=['documents', 'metadatas', 'ids'])

        # Assert input to get_relevant_tops_with_llm
        self.assertEqual(mock_get_relevant_tops_llm.call_count, 2) # Called for Proto A and Proto B
        # Check Proto A call - should only contain A1 (is_relevant: None)
        self.assertIn('Proto A', processed_protocols_for_llm_input)
        self.assertEqual(len(processed_protocols_for_llm_input['Proto A']), 1)
        self.assertEqual(processed_protocols_for_llm_input['Proto A'][0]['top_id'], 'A1')
        # Check Proto B call - should only contain B1 (is_relevant: None)
        self.assertIn('Proto B', processed_protocols_for_llm_input)
        self.assertEqual(len(processed_protocols_for_llm_input['Proto B']), 1)
        self.assertEqual(processed_protocols_for_llm_input['Proto B'][0]['top_id'], 'B1')

        # Assertions for mock_update_relevance
        # Called for A1 (to True) and B1 (to False)
        calls_relevance = [
            call(top_id='uuidA1', is_relevant=True, collection=mock_chroma_collection),
            call(top_id='uuidB1', is_relevant=False, collection=mock_chroma_collection)
        ]
        mock_update_relevance.assert_has_calls(calls_relevance, any_order=True)
        self.assertEqual(mock_update_relevance.call_count, 2)

        # Assertions for conditional execution (only for uuidA1 as it was set to True)
        mock_get_top_by_id.assert_called_once_with('uuidA1', mock_chroma_collection)

        mock_ollama_embeddings.assert_called_once_with(
            model=mock_config_module.OLLAMA_EMBEDDING_MODEL,
            prompt='Doc A1 content'
        )
        mock_chroma_collection.query.assert_called_once_with(
            query_embeddings=[mock_query_embedding],
            n_results=mock_config_module.SIMILAR_DOCS_COUNT + 1,
            include=['ids']
        )
        mock_update_references.assert_called_once_with(top_id='uuidA1', references_top_ids=['uuid_ref_for_A1'], collection=mock_chroma_collection)
        mock_update_article_status.assert_called_once_with(top_id='uuidA1', article_generated=True, collection=mock_chroma_collection)

        # Ensure these were NOT called for uuidB1 (marked False) or uuidA2/uuidB2 (skipped by pre-filter)
        # Call counts already asserted for most. If get_top_by_id was called more, it would fail above.

# test_run_article_generation_date_filters has been removed.

if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
