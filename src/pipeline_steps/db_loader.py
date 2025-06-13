import os
import glob
import json
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
log = config.get_logger(__name__, config.JSON_TO_CHROMA_LOG_FILENAME)

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

def process_json_file(json_filepath: pathlib.Path,
                        chroma_collection: chromadb.api.models.Collection.Collection,
                        embedding_model_name: str):
    """Loads records from a single JSON file, generates embeddings, and adds them to ChromaDB."""
    log.info(f"Processing JSON file: {json_filepath.name}")
    try:
        with open(json_filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        log.error(f"Error loading JSON file {json_filepath.name}: {e}", exc_info=True)
        return 0

    texts = []
    metadatas = []
    ids = []

    source_file_name = json_filepath.name
    title = data.get('title', '')
    datum = data.get('datum', '')
    tops = data.get('tops', [])

    for idx, top_item in enumerate(tops):
        top_id = top_item.get('top_id', '')
        content = top_item.get('content', '')
        if not content.strip():
            log.warning(f"Empty content for TOP ID {top_id} in {source_file_name}, skipping.")
            continue

        texts.append(content.strip())
        metadatas.append({
            'title': title,
            'datum': datum,
            'top_id': top_id,
            'source_file': source_file_name
        })
        ids.append(f"{source_file_name}_{top_id}_{idx}")

    if texts:
        try:
            log.info(f'Generating {len(texts)} embeddings using {embedding_model_name} for {source_file_name}...')
            embeddings = [ollama.embeddings(model=embedding_model_name, prompt=text)["embedding"] for text in texts]
            log.info(f'Embeddings generated. Adding to ChromaDB for {source_file_name}.')
            chroma_collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=texts,
                metadatas=metadatas
            )
            added_count = len(texts)
            log.info(f"Added {added_count} entries to ChromaDB from {source_file_name}")
            return added_count
        except Exception as e:
            log.error(f"Error generating embeddings or adding to ChromaDB for {source_file_name}: {e}", exc_info=True)
            return 0
    else:
        log.info(f"No text entries found to process in {json_filepath.name}")
        return 0

def run_json_to_chroma_loading():
    """Main function to orchestrate loading JSON data into ChromaDB."""
    log.info("Starting JSON to ChromaDB loading process...")

    try:
        chroma_collection = initialize_chroma_collection(
            db_path_name=config.CHROMA_DB_DIR_NAME,
            collection_name=config.CHROMA_COLLECTION_NAME,
            project_root=config.PROJECT_ROOT
        )
    except Exception as e:
        log.critical(f"CRITICAL: Could not initialize ChromaDB: {e}", exc_info=True)
        return

    json_input_dir = config.PROJECT_ROOT / config.JSON_DIR_NAME
    log.info(f"JSON input directory set to: {json_input_dir}")

    if not json_input_dir.is_dir():
        log.error(f"JSON input directory not found: {json_input_dir}")
        return

    json_files = list(json_input_dir.glob('*.json'))
    if not json_files:
        log.warning(f"No JSON files found in {json_input_dir}")
        return

    log.info(f"Found {len(json_files)} JSON files to process.")
    total_added_overall = 0

    for json_filepath in json_files:
        total_added_overall += process_json_file(
            json_filepath=json_filepath,
            chroma_collection=chroma_collection,
            embedding_model_name=config.OLLAMA_EMBEDDING_MODEL
        )

    log.info(f"JSON to ChromaDB loading process finished. Total entries added overall: {total_added_overall}")

if __name__ == "__main__":
    print(f"Executing db_loader.py directly. Project root: {config.PROJECT_ROOT}")
    run_json_to_chroma_loading()
