import os
import json
import logging
import pathlib
import sys
import google.generativeai as genai
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
        metadata={"hnsw:space": "cosine"} # Note: This metadata is for creation, may not be needed for get_or_create_collection if already exists
    )
    log.info(f"Using ChromaDB collection: {collection_name}")
    return collection

def get_relevant_tops_with_llm(protocol_title: str, protocol_date: str, current_tops: list[dict], genai_client, model_name: str, selection_prompt_template: str) -> dict | None:
    """
    Uses a GenAI model to select relevant TOPs from a list based on a given prompt.
    Returns a dictionary with the selected TOPs in the same structure as the input protocol, or None on failure.
    """
    llm_input_data = {
        "title": protocol_title,
        "datum": protocol_date,
        "tops": current_tops
    }

    # The prompt template already contains instructions. We just need to append the data.
    # The prompt is structured so the LLM knows how to use the provided JSON data.
    full_prompt_parts = [
        selection_prompt_template,
        json.dumps(llm_input_data, ensure_ascii=False)
    ]

    log.debug(f"Sending data to LLM for TOP selection. Title: {protocol_title}, Date: {protocol_date}, TOPs count: {len(current_tops)}")

    try:
        response = genai_client.generate_content(
            model=model_name,
            contents=full_prompt_parts, # Pass as a list of parts
            generation_config=genai.types.GenerationConfig(response_mime_type="application/json")
        )
        # Assuming response.text contains the JSON string
        selected_data = json.loads(response.text)
        log.debug(f"Received {len(selected_data.get('tops', []))} TOPs from LLM selection for protocol {protocol_title}")
        return selected_data
    except json.JSONDecodeError as e:
        log.error(f"Error decoding JSON response from LLM for protocol {protocol_title}: {e}. Response text: {response.text if 'response' in locals() else 'No response object'}", exc_info=True)
        return None
    except Exception as e:
        log.error(f"Error calling GenAI model for TOP selection for protocol {protocol_title}: {e}", exc_info=True)
        return None

def run_article_generation(start_date: str = None, end_date: str = None):
    """
    Fetches TOPs from ChromaDB within the given date range, groups them by protocol,
    uses an LLM to select relevant TOPs, and saves them as filtered JSON files.
    """
    log.info("Starting TOP filtering and JSON generation process...")

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

    filtered_json_output_dir = config.PROJECT_ROOT / config.FILTERED_JSON_DIR_NAME
    filtered_json_output_dir.mkdir(parents=True, exist_ok=True)
    log.info(f"Filtered JSON output directory: {filtered_json_output_dir}")

    # Construct ChromaDB where_filter
    where_filter = {}
    if start_date and end_date:
        where_filter = {"$and": [{"datum": {"$gte": start_date}}, {"datum": {"$lte": end_date}}]}
        log.info(f"Filtering TOPs between {start_date} and {end_date}")
    elif start_date:
        where_filter = {"datum": {"$gte": start_date}}
        log.info(f"Filtering TOPs from {start_date} onwards")
    elif end_date:
        where_filter = {"datum": {"$lte": end_date}}
        log.info(f"Filtering TOPs up to {end_date}")
    else:
        log.info("No date filters provided, fetching all TOPs.")
        # For ChromaDB, an empty dict or None usually means no filter.
        # If it requires a non-null value, an empty dict `{}` is standard.

    try:
        # If where_filter is empty, pass it as is. ChromaDB client should handle it.
        results = chroma_collection.get(where=where_filter if where_filter else None, include=['documents', 'metadatas', 'ids']) # ids might not be strictly needed here but good for reference
        log.info(f"Retrieved {len(results.get('ids', []))} TOP entries from ChromaDB.")
    except Exception as e:
        log.error(f"Error querying ChromaDB: {e}", exc_info=True)
        return

    # Group TOPs by original protocol
    grouped_protocols = {}
    if results and results['ids']:
        for i in range(len(results['ids'])):
            metadata = results['metadatas'][i]
            document = results['documents'][i]

            source_file = metadata.get('source_file')
            if not source_file:
                log.warning(f"Skipping entry with ID {results['ids'][i]} due to missing 'source_file' in metadata: {metadata}")
                continue

            top_id = metadata.get('top_id', f"unknown_top_id_{i}") # Fallback if top_id is missing
            protocol_title = metadata.get('title', "Unknown Title")
            protocol_date = metadata.get('datum', "Unknown Date")

            if source_file not in grouped_protocols:
                grouped_protocols[source_file] = {
                    'title': protocol_title,
                    'datum': protocol_date,
                    'tops': []
                }

            grouped_protocols[source_file]['tops'].append({
                'top_id': top_id,
                'content': document
            })
        log.info(f"Grouped TOPs into {len(grouped_protocols)} protocols.")
    else:
        log.info("No TOPs found in ChromaDB matching the criteria.")
        return


    # Main loop for processing grouped TOPs
    for source_file, data in grouped_protocols.items():
        # Use original source_file name (e.g., 'protocol_xyz.json') for the filtered output stem
        # Sanitize source_file if it's an absolute path or contains problematic characters for a filename stem
        base_name = os.path.basename(source_file)
        output_filename = pathlib.Path(base_name).stem + "_filtered.json"
        output_json_path = filtered_json_output_dir / output_filename

        if output_json_path.exists():
            log.info(f"Filtered JSON {output_json_path.name} already exists. Skipping processing for {source_file}.")
            continue

        log.info(f"Processing protocol: {source_file} for LLM-based TOP selection.")

        protocol_title = data['title']
        protocol_date = data['datum']
        tops_for_llm = data['tops']

        if not tops_for_llm:
            log.info(f"No TOPs to process for LLM selection in {source_file}. Skipping.")
            # Optionally, write an empty protocol structure if needed
            # empty_protocol_structure = {"title": protocol_title, "datum": protocol_date, "tops": []}
            # with open(output_json_path, "w", encoding="utf-8") as f:
            #    json.dump(empty_protocol_structure, f, ensure_ascii=False, indent=2)
            # log.info(f"Saved empty filtered JSON to {output_json_path}")
            continue

        selected_tops_data = get_relevant_tops_with_llm(
            protocol_title=protocol_title,
            protocol_date=protocol_date,
            current_tops=tops_for_llm,
            genai_client=genai_client,
            model_name=config.GENAI_PDF_EXTRACTION_MODEL, # Using this model as per instruction, ensure it's suitable for this task
            selection_prompt_template=config.GENAI_TOPIC_SELECTION_PROMPT
        )

        if selected_tops_data:
            # Basic validation of the LLM output
            if isinstance(selected_tops_data, dict) and \
               'title' in selected_tops_data and \
               'datum' in selected_tops_data and \
               'tops' in selected_tops_data and isinstance(selected_tops_data['tops'], list):
                try:
                    with open(output_json_path, "w", encoding="utf-8") as f:
                        json.dump(selected_tops_data, f, ensure_ascii=False, indent=2)
                    log.info(f"Successfully saved filtered JSON with {len(selected_tops_data['tops'])} TOPs to {output_json_path}")
                except Exception as e:
                    log.error(f"Error writing selected TOPs to JSON file {output_json_path} for protocol {source_file}: {e}", exc_info=True)
            else:
                log.warning(f"LLM output for {source_file} did not match expected structure. LLM Output: {selected_tops_data}")
        else:
            log.warning(f"LLM-based TOP selection failed or returned no data for protocol {source_file}. No filtered JSON will be saved for this protocol.")

    log.info("TOP filtering and JSON generation process finished.")

if __name__ == "__main__":
    print(f"Executing article_generator.py directly. Project root: {config.PROJECT_ROOT}")
    # Example of running with date filters:
    # run_article_generation(start_date="2023-01-01", end_date="2023-12-31")
    run_article_generation()
