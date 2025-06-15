import logging
import pathlib
import sys
import chromadb
import ollama

# Ensure src directory is in sys.path for config import
project_root_for_import = pathlib.Path(__file__).resolve().parent.parent.parent
if str(project_root_for_import) not in sys.path:
    sys.path.insert(0, str(project_root_for_import))

try:
    from src import config
except ImportError as e:
    print(f"Error importing src.config: {e}")
    print(f"Current sys.path: {sys.path}")
    print(f"Attempted project_root_for_import: {project_root_for_import}")
    raise

# Initialize logger
log = config.get_logger(__name__, config.CHROMA_DB_UTILS_LOG_FILENAME)

def initialize_chroma_collection(db_path_name: str, collection_name: str, project_root: pathlib.Path):
    """Initializes and returns a ChromaDB collection."""
    persistent_client = chromadb.PersistentClient(path=str(project_root / db_path_name))
    log.info(f'ChromaDB client initialized with path: {project_root / db_path_name}')
    collection = persistent_client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"} # Default, can be configured if needed
    )
    log.info(f"Using ChromaDB collection: {collection_name}")
    return collection

def add_top_to_chromadb(top_id: str, document: str, metadata: dict, collection: chromadb.api.models.Collection.Collection):
    """Adds a single TOP document to the ChromaDB collection."""
    try:
        log.debug(f"Generating Ollama embedding for TOP ID {top_id} using model {config.OLLAMA_EMBEDDING_MODEL}...")
        embedding = ollama.embeddings(
            model=config.OLLAMA_EMBEDDING_MODEL,
            prompt=document
        )["embedding"]
        log.debug(f"Embedding generated successfully for TOP ID {top_id}.")

        collection.add(
            ids=[top_id],
            embeddings=[embedding], # Add this line
            documents=[document],
            metadatas=[metadata]
        )
        log.info(f"Added TOP with ID {top_id} to ChromaDB.")
        return True
    except Exception as e:
        log.error(f"Error adding TOP ID {top_id} to ChromaDB (embedding or add failed): {e}", exc_info=True)
        return False

def get_top_by_id(top_id: str, collection: chromadb.api.models.Collection.Collection) -> dict | None:
    """Retrieves a TOP document and its metadata from ChromaDB by its ID."""
    try:
        # Ensure all necessary data parts are requested
        result = collection.get(ids=[top_id], include=['metadatas', 'documents'])
        if result and result['ids'] and result['ids'][0] is not None:
            # Check if document and metadata are present and not None
            doc = result['documents'][0] if result['documents'] and result['documents'][0] is not None else None
            meta = result['metadatas'][0] if result['metadatas'] and result['metadatas'][0] is not None else {} # Default to empty dict if no metadata

            if doc is None:
                log.warning(f"Document for TOP ID {top_id} is missing, though ID was found.")

            return {
                "id": result['ids'][0],
                "document": doc,
                "metadata": meta
            }
        log.warning(f"TOP with ID {top_id} not found or data incomplete in ChromaDB.")
        return None
    except Exception as e:
        log.error(f"Error retrieving TOP ID {top_id} from ChromaDB: {e}", exc_info=True)
        return None

def update_top_metadata_field(top_id: str, field_name: str, field_value: any, collection: chromadb.api.models.Collection.Collection) -> bool:
    """Updates a specific metadata field for a TOP in ChromaDB."""
    try:
        current_doc = get_top_by_id(top_id, collection)
        if not current_doc or current_doc.get('metadata') is None: # Check if metadata exists
            log.error(f"Cannot update metadata for TOP {top_id}: Not found or metadata missing.")
            return False

        new_metadata = current_doc['metadata'].copy()
        new_metadata[field_name] = field_value

        # Ensure we only update metadatas, not trying to update documents or embeddings here unless intended
        collection.update(
            ids=[top_id],
            metadatas=[new_metadata]
        )
        log.info(f"Updated metadata field '{field_name}' for TOP ID {top_id} to '{field_value}'.")
        return True
    except Exception as e:
        log.error(f"Error updating metadata field '{field_name}' for TOP ID {top_id}: {e}", exc_info=True)
        return False

def update_top_relevance(top_id: str, is_relevant: bool, collection: chromadb.api.models.Collection.Collection) -> bool:
    """Sets or updates the 'is_relevant' flag for a TOP."""
    return update_top_metadata_field(top_id, 'is_relevant', is_relevant, collection)

def update_top_references(top_id: str, references_top_ids: list[str], collection: chromadb.api.models.Collection.Collection) -> bool:
    """Sets or updates the 'references_top_ids' list for a TOP."""
    return update_top_metadata_field(top_id, 'references_top_ids', references_top_ids, collection)

def update_article_generated_status(top_id: str, article_generated: bool, collection: chromadb.api.models.Collection.Collection) -> bool:
    """Sets or updates the 'article_generated' flag for a TOP."""
    return update_top_metadata_field(top_id, 'article_generated', article_generated, collection)
