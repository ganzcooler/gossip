import unittest
from unittest.mock import patch, MagicMock
import chromadb
import uuid # For generating test IDs
import pathlib # For config.PROJECT_ROOT
import sys

# Add project root to sys.path to allow src imports
project_root_for_test = pathlib.Path(__file__).resolve().parent.parent
if str(project_root_for_test) not in sys.path:
    sys.path.insert(0, str(project_root_for_test))

from src.pipeline_steps import db_loader
from src import config # For config.CHROMA_COLLECTION_NAME etc.

class TestDbLoader(unittest.TestCase):

    def setUp(self):
        """Set up an in-memory ChromaDB client and collection for each test."""
        # Using an in-memory client for isolated testing
        self.test_client = chromadb.Client()
        self.test_collection_name = "test_tops_collection"
        # Get the collection directly for tests, similar to how initialize_chroma_collection would work
        self.test_collection = self.test_client.get_or_create_collection(
            name=self.test_collection_name,
            metadata={"hnsw:space": "cosine"}
        )

        # Mock the logger used in db_loader to suppress output during tests if desired,
        # or to make assertions on log calls. For now, just basic patch.
        self.log_patcher = patch('src.pipeline_steps.db_loader.log')
        self.mock_log = self.log_patcher.start()

    def tearDown(self):
        """Stop any patchers started in setUp."""
        self.log_patcher.stop()
        # No need to explicitly delete in-memory client or collection,
        # but if using PersistentClient with a temp dir, cleanup would go here.

    @patch('src.pipeline_steps.db_loader.ollama.embeddings')
    def test_add_top_to_chromadb_and_get_top_by_id(self, mock_ollama_embeddings):
        """Test adding a TOP and retrieving it."""
        test_id = str(uuid.uuid4())
        test_doc = "This is a test document about something interesting."
        test_meta = {"protocol_title": "Test Protocol Alpha", "protocol_date": "2024-01-01", "top_number": "T1"}

        mock_generated_embedding = [0.1, 0.2, 0.3] # Example
        mock_ollama_embeddings.return_value = {"embedding": mock_generated_embedding}

        # Spy on self.test_collection.add to check arguments but still execute the real add
        original_add = self.test_collection.add
        with patch.object(self.test_collection, 'add', side_effect=original_add, autospec=True) as spied_collection_add:
            add_success = db_loader.add_top_to_chromadb(test_id, test_doc, test_meta, self.test_collection)
            self.assertTrue(add_success)

            # Assert ollama.embeddings was called
            mock_ollama_embeddings.assert_called_once_with(
                model=config.OLLAMA_EMBEDDING_MODEL,
                prompt=test_doc
            )
            # Assert self.test_collection.add was called with embeddings
            spied_collection_add.assert_called_once_with(
                ids=[test_id],
                embeddings=[mock_generated_embedding],
                documents=[test_doc],
                metadatas=[test_meta]
            )

        # Retrieve TOP using get_top_by_id from db_loader - this should still work
        retrieved_top = db_loader.get_top_by_id(test_id, self.test_collection)

        self.assertIsNotNone(retrieved_top)
        self.assertEqual(retrieved_top['id'], test_id)
        self.assertEqual(retrieved_top['document'], test_doc)
        self.assertEqual(retrieved_top['metadata'], test_meta)

        # Test getting a non-existent ID
        non_existent_id = str(uuid.uuid4())
        self.assertIsNone(db_loader.get_top_by_id(non_existent_id, self.test_collection))

    @patch('src.pipeline_steps.db_loader.ollama.embeddings')
    def test_update_top_relevance(self, mock_ollama_embeddings):
        """Test updating the 'is_relevant' metadata field."""
        mock_ollama_embeddings.return_value = {"embedding": [0.1, 0.2, 0.3]} # Basic mock for add
        top_id = str(uuid.uuid4())
        initial_meta = {"protocol_title": "Relevance Test", "protocol_date": "2024-01-02", "top_number": "R1"}
        db_loader.add_top_to_chromadb(top_id, "Relevance document", initial_meta, self.test_collection)

        # Update relevance to True
        update_success_true = db_loader.update_top_relevance(top_id, True, self.test_collection)
        self.assertTrue(update_success_true)
        retrieved_top_true = db_loader.get_top_by_id(top_id, self.test_collection)
        self.assertTrue(retrieved_top_true['metadata'].get('is_relevant'))

        # Update relevance to False
        update_success_false = db_loader.update_top_relevance(top_id, False, self.test_collection)
        self.assertTrue(update_success_false)
        retrieved_top_false = db_loader.get_top_by_id(top_id, self.test_collection)
        self.assertFalse(retrieved_top_false['metadata'].get('is_relevant'))

        # Check other metadata is preserved
        self.assertEqual(retrieved_top_false['metadata']['protocol_title'], "Relevance Test")

    @patch('src.pipeline_steps.db_loader.ollama.embeddings')
    def test_update_top_references(self, mock_ollama_embeddings):
        """Test updating the 'references_top_ids' metadata field."""
        mock_ollama_embeddings.return_value = {"embedding": [0.1, 0.2, 0.3]} # Basic mock for add
        top_id = str(uuid.uuid4())
        initial_meta = {"protocol_title": "Reference Test", "protocol_date": "2024-01-03", "top_number": "REF1"}
        db_loader.add_top_to_chromadb(top_id, "Reference document", initial_meta, self.test_collection)

        ref_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
        update_success = db_loader.update_top_references(top_id, ref_ids, self.test_collection)
        self.assertTrue(update_success)

        retrieved_top = db_loader.get_top_by_id(top_id, self.test_collection)
        self.assertEqual(retrieved_top['metadata'].get('references_top_ids'), ref_ids)
        self.assertEqual(retrieved_top['metadata']['protocol_title'], "Reference Test")

    @patch('src.pipeline_steps.db_loader.ollama.embeddings')
    def test_update_article_generated_status(self, mock_ollama_embeddings):
        """Test updating the 'article_generated' metadata field."""
        mock_ollama_embeddings.return_value = {"embedding": [0.1, 0.2, 0.3]} # Basic mock for add
        top_id = str(uuid.uuid4())
        initial_meta = {"protocol_title": "Article Gen Test", "protocol_date": "2024-01-04", "top_number": "AG1"}
        db_loader.add_top_to_chromadb(top_id, "Article gen document", initial_meta, self.test_collection)

        # Update status to True
        update_success_true = db_loader.update_article_generated_status(top_id, True, self.test_collection)
        self.assertTrue(update_success_true)
        retrieved_top_true = db_loader.get_top_by_id(top_id, self.test_collection)
        self.assertTrue(retrieved_top_true['metadata'].get('article_generated'))

        # Update status to False
        update_success_false = db_loader.update_article_generated_status(top_id, False, self.test_collection)
        self.assertTrue(update_success_false)
        retrieved_top_false = db_loader.get_top_by_id(top_id, self.test_collection)
        self.assertFalse(retrieved_top_false['metadata'].get('article_generated'))
        self.assertEqual(retrieved_top_false['metadata']['protocol_title'], "Article Gen Test")

    def test_update_non_existent_top(self):
        """Test updating metadata for a non-existent TOP ID."""
        non_existent_id = str(uuid.uuid4())
        self.assertFalse(db_loader.update_top_relevance(non_existent_id, True, self.test_collection))
        self.mock_log.error.assert_called_with(f"Cannot update metadata for TOP {non_existent_id}: Not found or metadata missing.")

    # Test for initialize_chroma_collection (using PersistentClient)
    # This test is more of an integration test for this specific function.
    @patch('src.pipeline_steps.db_loader.chromadb.PersistentClient')
    def test_initialize_chroma_collection(self, MockPersistentClient):
        """Test that initialize_chroma_collection calls PersistentClient and get_or_create_collection."""
        mock_client_instance = MockPersistentClient.return_value
        mock_collection_instance = MagicMock(spec=chromadb.api.models.Collection.Collection)
        mock_client_instance.get_or_create_collection.return_value = mock_collection_instance

        test_db_path = "test_db_dir"
        test_collection_name = "my_test_collection"

        # Use a concrete path for PROJECT_ROOT for this test, or mock config.PROJECT_ROOT
        # Assuming config.PROJECT_ROOT is already a pathlib.Path
        expected_full_path = str(config.PROJECT_ROOT / test_db_path)

        collection = db_loader.initialize_chroma_collection(
            db_path_name=test_db_path,
            collection_name=test_collection_name,
            project_root=config.PROJECT_ROOT
        )

        MockPersistentClient.assert_called_once_with(path=expected_full_path)
        mock_client_instance.get_or_create_collection.assert_called_once_with(
            name=test_collection_name,
            metadata={"hnsw:space": "cosine"}
        )
        self.assertEqual(collection, mock_collection_instance)
        self.mock_log.info.assert_any_call(f'ChromaDB client initialized with path: {expected_full_path}')
        self.mock_log.info.assert_any_call(f"Using ChromaDB collection: {test_collection_name}")


if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
