import os
import glob
import json
import logging
import pathlib
import sys
from google import genai
import ollama
import chromadb

# Ensure src directory is in sys.path for config import
project_root_for_import = pathlib.Path(__file__).resolve().parent.parent.parent
if str(project_root_for_import) not in sys.path:
    sys.path.insert(0, str(project_root_for_import))

try:
    from src import config
except ImportError as e:
    print(f"Error importing src.config or other modules: {e}")
    print(f"Current sys.path: {sys.path}")
    print(f"Attempted project_root_for_import: {project_root_for_import}")
    raise

# Initialize logger
log = config.get_logger(__name__, config.CHROMA_TO_ARTICLES_LOG_FILENAME)

def initialize_chroma_collection(db_path_name: str, collection_name: str, project_root: pathlib.Path):
    """Initializes and returns a ChromaDB collection."""
    persistent_client = chromadb.PersistentClient(path=str(project_root / db_path_name))
    log.info(f'ChromaDB client initialized with path: {project_root / db_path_name}')
    collection = persistent_client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"}
    )
    log.info(f"Using ChromaDB collection: {collection_name}")
    return collection

def build_prompt_for_article(source_file_name: str, new_entries_data: list[dict], similar_older_texts: list[str]) -> str:
    """Builds the prompt for the GenAI model to generate articles."""
    prompt_parts = [f"Basierend auf dem folgenden Protokoll aus '{source_file_name}' sollen mehrere journalistische Artikel erstellt werden.\n"]

    for idx, entry in enumerate(new_entries_data, 1):
        prompt_parts.append(f"### Neuer Eintrag {idx} (TOP ID: {entry.get('top_id', 'N/A')}):
{entry.get('content', '')}\n")

    if similar_older_texts:
        prompt_parts.append("Es wurden ältere, thematisch ähnliche Artikel aus anderen Quellen gefunden, die zur Inspiration verwendet werden können, aber nicht müssen:\n")
        for idx, text in enumerate(similar_older_texts, 1):
            prompt_parts.append(f"--- Älterer Artikel {idx} ---\n{text}\n")

    prompt_parts.append(
        "\nBitte analysiere die neuen Einträge und wähle die relevantesten oder interessantesten Themen (TOPs) für die Leserschaft aus. "
        "Verfasse anschließend mehrere journalistische Artikel, jeweils zu einem Thema. "
        "Die Artikel sollen informativ, klar und gut strukturiert sein."
    )
    return "\n".join(prompt_parts)

def run_article_generation():
    """Main function to generate articles based on new entries and similar texts from ChromaDB."""
    log.info("Starting article generation process...")

    try:
        genai_api_key = config.load_google_api_key()
        genai_client = genai.Client(api_key=genai_api_key)
        log.info("Google GenAI client initialized.")

        chroma_collection = initialize_chroma_collection(
            db_path_name=config.CHROMA_DB_DIR_NAME,
            collection_name=config.CHROMA_COLLECTION_NAME,
            project_root=config.PROJECT_ROOT
        )
    except Exception as e:
        log.critical(f"CRITICAL: Initialization error (GenAI client or ChromaDB): {e}", exc_info=True)
        return

    json_input_dir = config.PROJECT_ROOT / config.JSON_DIR_NAME
    article_output_dir = config.PROJECT_ROOT / config.ARTICLES_DIR_NAME
    article_output_dir.mkdir(parents=True, exist_ok=True)

    log.info(f"JSON input directory: {json_input_dir}")
    log.info(f"Article output directory: {article_output_dir}")

    if not json_input_dir.is_dir():
        log.error(f"JSON input directory not found: {json_input_dir}")
        return

    json_files = list(json_input_dir.glob('*.json'))
    if not json_files:
        log.warning(f"No JSON files found in {json_input_dir} to process for article generation.")
        return

    log.info(f"Found {len(json_files)} JSON files to process.")

    for json_filepath in json_files:
        source_filename = json_filepath.name
        md_output_path = article_output_dir / f"{json_filepath.stem}.md"

        if md_output_path.exists():
            log.info(f"Article {md_output_path.name} already exists. Skipping generation for {source_filename}.")
            continue

        log.info(f"Processing source file for new entries: {source_filename}")

        try:
            with open(json_filepath, 'r', encoding='utf-8') as f:
                source_data = json.load(f)
        except Exception as e:
            log.error(f"Error loading JSON file {source_filename}: {e}", exc_info=True)
            continue

        new_entries_for_prompt = []
        texts_for_similarity_search = []
        for top_item in source_data.get('tops', []):
            content = top_item.get('content', '').strip()
            if content:
                new_entries_for_prompt.append({'top_id': top_item.get('top_id'), 'content': content})
                texts_for_similarity_search.append(content)

        if not new_entries_for_prompt:
            log.info(f"No processable TOPs with content found in {source_filename}. Skipping article generation.")
            continue

        similar_older_texts = []
        if texts_for_similarity_search:
            log.info(f"Querying ChromaDB for texts similar to entries in {source_filename}...")
            try:
                query_embeddings = [ollama.embeddings(model=config.OLLAMA_EMBEDDING_MODEL, prompt=text)["embedding"] for text in texts_for_similarity_search]

                results = chroma_collection.query(
                    query_embeddings=query_embeddings,
                    n_results=config.SIMILAR_DOCS_COUNT,
                    include=["documents", "metadatas"]
                )

                if results and results.get("documents"):
                    for per_query_docs, per_query_metas in zip(results.get("documents"), results.get("metadatas")):
                        for doc_content, doc_meta in zip(per_query_docs, per_query_metas):
                            if doc_meta.get("source_file") != source_filename:
                                if doc_content not in similar_older_texts:
                                    similar_older_texts.append(doc_content)
                log.info(f"Found {len(similar_older_texts)} similar older texts from other sources.")
            except Exception as e:
                log.error(f"Error during similarity search for {source_filename}: {e}", exc_info=True)

        prompt_text = build_prompt_for_article(source_filename, new_entries_for_prompt, similar_older_texts)
        log.info(f"Generating article for {source_filename} with {len(new_entries_for_prompt)} new entries and {len(similar_older_texts)} reference texts.")

        try:
            response = genai_client.generate_content(
                model=config.GENAI_ARTICLE_GENERATION_MODEL,
                contents=prompt_text,
                request_options={"timeout": 300}
            )
            article_text = response.text if response.text else ""
        except Exception as e:
            log.error(f"Error calling GenAI model for {source_filename}: {e}", exc_info=True)
            continue

        try:
            with open(md_output_path, "w", encoding="utf-8") as f:
                f.write(f"# Artikel basierend auf {source_filename}\n\n")
                f.write(article_text)
            log.info(f"Article successfully saved to: {md_output_path}")
        except Exception as e:
            log.error(f"Error writing article to file {md_output_path}: {e}", exc_info=True)

    log.info("Article generation process finished.")

if __name__ == "__main__":
    print(f"Executing article_generator.py directly. Project root: {config.PROJECT_ROOT}")
    run_article_generation()
