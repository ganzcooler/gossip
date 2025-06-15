# src/pipeline_steps/relevance_determiner.py
import json
import logging # Keep for potential direct use, though config.get_logger is primary
import pathlib
import sys
import google.generativeai as genai

# Ensure src directory is in sys.path for config import
project_root_for_import = pathlib.Path(__file__).resolve().parent.parent.parent
if str(project_root_for_import) not in sys.path:
    sys.path.insert(0, str(project_root_for_import))

try:
    from src import config
    from src.pipeline_steps import db_loader
except ImportError as e:
    # Attempt to get a logger even if config import failed for some reason, or print.
    temp_log = logging.getLogger(__name__)
    temp_log.error(f"Error importing modules in relevance_determiner.py: {e}")
    temp_log.error(f"Current sys.path: {sys.path}")
    temp_log.error(f"Attempted project_root_for_import: {project_root_for_import}")
    # Fallback print if logging is not configured
    print(f"CRITICAL: Error importing modules in relevance_determiner.py: {e}. Check sys.path and module availability.", file=sys.stderr)
    raise

# Initialize logger using the new constant
log = config.get_logger(__name__, config.RELEVANCE_DETERMINER_LOG_FILENAME)

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
    full_prompt_parts = [
        selection_prompt_template,
        json.dumps(llm_input_data, ensure_ascii=False)
    ]
    log.debug(f"Sending data to LLM for TOP selection. Title: {protocol_title}, Date: {protocol_date}, TOPs count: {len(current_tops)}")
    try:
        response = genai_client.generate_content(
            model=model_name,
            contents=full_prompt_parts,
            generation_config=genai.types.GenerationConfig(response_mime_type="application/json")
        )
        selected_data = json.loads(response.text)
        log.debug(f"Received {len(selected_data.get('tops_evaluation', []))} evaluated TOPs from LLM for protocol {protocol_title}")
        return selected_data
    except json.JSONDecodeError as e:
        log.error(f"Error decoding JSON response from LLM for protocol {protocol_title}: {e}. Response text: {response.text if 'response' in locals() else 'No response object'}", exc_info=True)
        return None
    except Exception as e:
        log.error(f"Error calling GenAI model for TOP selection for protocol {protocol_title}: {e}", exc_info=True)
        return None

def run_relevance_determination():
    """
    Fetches all TOPs from ChromaDB, groups them by protocol, uses an LLM to select
    relevant TOPs, and updates their 'is_relevant' status in ChromaDB.
    """
    log.info("Starting TOP relevance determination process...")

    try:
        genai_api_key = config.load_google_api_key()
        genai_client = genai.Client(api_key=genai_api_key)
        log.info("Google GenAI client initialized for relevance determination.")

        chroma_collection = db_loader.initialize_chroma_collection(
            db_path_name=config.CHROMA_DB_DIR_NAME,
            collection_name=config.CHROMA_COLLECTION_NAME,
            project_root=config.PROJECT_ROOT
        )
        log.info(f"ChromaDB collection '{config.CHROMA_COLLECTION_NAME}' initialized for relevance determination.")
    except Exception as e:
        log.critical(f"CRITICAL: Initialization error (GenAI client or ChromaDB) in relevance determination: {e}", exc_info=True)
        return

    try:
        log.info("Fetching all TOPs from ChromaDB for relevance determination.")
        results = chroma_collection.get(where=None, include=['documents', 'metadatas', 'ids']) # Fetch all
        log.info(f"Retrieved {len(results.get('ids', []))} TOP entries from ChromaDB.")
    except Exception as e:
        log.error(f"Error querying ChromaDB for all TOPs: {e}", exc_info=True)
        return

    grouped_protocols = {}
    if results and results['ids']:
        for i in range(len(results['ids'])):
            chroma_id = results['ids'][i]
            metadata = results['metadatas'][i]
            document = results['documents'][i]
            protocol_title = metadata.get('protocol_title', "Unknown Title")
            protocol_date = metadata.get('protocol_date', "Unknown Date")
            top_number = metadata.get('top_number')

            if not top_number:
                log.warning(f"Skipping entry with Chroma ID {chroma_id} due to missing 'top_number' in metadata: {metadata}")
                continue

            protocol_key = (protocol_title, protocol_date)
            if protocol_key not in grouped_protocols:
                grouped_protocols[protocol_key] = {'tops': []}

            grouped_protocols[protocol_key]['tops'].append({
                'chroma_id': chroma_id,
                'top_number': top_number,
                'content': document,
                'metadata': metadata
            })
        log.info(f"Grouped TOPs into {len(grouped_protocols)} unique protocols.")
    else:
        log.info("No TOPs found in ChromaDB for relevance determination.")
        return

    total_updated_count = 0
    for protocol_key, data in grouped_protocols.items():
        protocol_title, protocol_date = protocol_key
        all_tops_for_protocol = data['tops']
        log.info(f"Processing protocol: {protocol_title} ({protocol_date}) for relevance determination.")

        tops_to_evaluate_for_llm = []
        top_number_to_chroma_id_map = {} # Map original top_number to chroma_id

        for top_data in all_tops_for_protocol:
            # Only process if 'is_relevant' is not already set (None or missing)
            if top_data['metadata'].get('is_relevant') is None:
                if top_data['top_number'] and top_data['content']:
                    tops_to_evaluate_for_llm.append({'top_id': top_data['top_number'], 'content': top_data['content']})
                    top_number_to_chroma_id_map[top_data['top_number']] = top_data['chroma_id']
                else:
                    log.warning(f"Skipping TOP {top_data.get('chroma_id')} for LLM input due to missing top_number or content for protocol {protocol_title} ({protocol_date}).")
            else:
                log.debug(f"TOP {top_data['chroma_id']} (Original: {top_data['top_number']}) already has 'is_relevant' set to {top_data['metadata']['is_relevant']}. Skipping LLM evaluation for this TOP.")

        if not tops_to_evaluate_for_llm:
            log.info(f"No TOPs requiring relevance determination in protocol {protocol_title} ({protocol_date}). Skipping LLM call.")
            continue

        log.info(f"Sending {len(tops_to_evaluate_for_llm)} TOPs from protocol {protocol_title} ({protocol_date}) to LLM for relevance evaluation.")
        llm_evaluation_data = get_relevant_tops_with_llm(
            protocol_title=protocol_title,
            protocol_date=protocol_date,
            current_tops=tops_to_evaluate_for_llm,
            genai_client=genai_client,
            model_name=config.GENAI_ARTICLE_GENERATION_MODEL, # Using the model specified for article generation, assuming it's suitable for selection
            selection_prompt_template=config.GENAI_TOPIC_SELECTION_PROMPT
        )

        protocol_updated_count = 0
        if llm_evaluation_data and isinstance(llm_evaluation_data.get('tops_evaluation'), list):
            for evaluated_top in llm_evaluation_data.get('tops_evaluation', []):
                original_top_id_from_llm = evaluated_top.get('top_id')
                llm_relevance_status = evaluated_top.get('is_selected_relevant')

                if original_top_id_from_llm is None or not isinstance(llm_relevance_status, bool):
                    log.warning(f"Invalid item from LLM evaluation for {protocol_title} ({protocol_date}): missing 'top_id' or 'is_selected_relevant' is not boolean. Data: {evaluated_top}")
                    continue

                chroma_id_for_update = top_number_to_chroma_id_map.get(original_top_id_from_llm)
                if chroma_id_for_update:
                    update_success = db_loader.update_top_relevance(
                        top_id=chroma_id_for_update,
                        is_relevant=llm_relevance_status,
                        collection=chroma_collection
                    )
                    if update_success:
                        log.info(f"Successfully set 'is_relevant={llm_relevance_status}' for TOP (Original ID {original_top_id_from_llm}, Chroma ID {chroma_id_for_update}).")
                        protocol_updated_count += 1
                    else:
                        log.error(f"Failed to update 'is_relevant' for TOP (Original ID {original_top_id_from_llm}, Chroma ID {chroma_id_for_update}).")
                else:
                    log.warning(f"Could not map LLM-evaluated TOP ID '{original_top_id_from_llm}' back to a Chroma ID for protocol {protocol_title} ({protocol_date}).")
            log.info(f"Updated 'is_relevant' status for {protocol_updated_count} TOPs in protocol {protocol_title} ({protocol_date}).")
            total_updated_count += protocol_updated_count
        elif llm_evaluation_data:
             log.warning(f"LLM output for {protocol_title} ({protocol_date}) did not match expected structure. LLM Output (first 300 chars): {str(llm_evaluation_data)[:300]}")
        else:
            log.warning(f"LLM-based TOP evaluation failed or returned no data for protocol {protocol_title} ({protocol_date}). No TOPs updated.")

    log.info(f"Relevance determination process finished. Total TOPs updated: {total_updated_count}.")

if __name__ == "__main__":
    # This allows running the step directly for testing if needed
    log.info(f"Executing relevance_determiner.py directly. Project root: {config.PROJECT_ROOT}")
    run_relevance_determination()
