# src/pipeline_steps/relevance_determiner.py
import json
import logging # Keep for potential direct use, though config.get_logger is primary
import pathlib
import sys
import time # Added time module
from google import genai
from pydantic import BaseModel
from typing import List

# Ensure src directory is in sys.path for config import
project_root_for_import = pathlib.Path(__file__).resolve().parent.parent.parent
if str(project_root_for_import) not in sys.path:
    sys.path.insert(0, str(project_root_for_import))

try:
    from src import config
    from src.pipeline_steps import db_loader
    from src import prompts # Import the new prompts module
except ImportError as e:
    # Attempt to get a logger even if config import failed for some reason, or print.
    temp_log = logging.getLogger(__name__)
    temp_log.error(f"Error importing modules in relevance_determiner.py: {e}")
    temp_log.error(f"Current sys.path: {sys.path}")
    temp_log.error(f"Attempted project_root_for_import: {project_root_for_import}")
    # Fallback print if logging is not configured
    print(f"CRITICAL: Error importing modules in relevance_determiner.py: {e}. Check sys.path and module availability.", file=sys.stderr)
    raise

class TopEvaluation(BaseModel):
    original_index: int
    content_preview: str
    is_selected_relevant: bool

class TopsEvaluationResponse(BaseModel):
    tops_evaluation: List[TopEvaluation]

# Initialize logger using the new constant
log = config.get_logger(__name__, config.RELEVANCE_DETERMINER_LOG_FILENAME)

def get_relevant_tops_with_llm(protocol_title: str, protocol_date: str, current_tops_content_list: List[str], genai_model_instance: genai.GenerativeModel, selection_prompt_template: str, delay_duration: int) -> dict | None:
    """
    Uses a GenAI model to select relevant TOPs from a list of content strings based on a given prompt.
    Returns a dictionary (parsed from JSON) with the LLM's evaluation, or None on failure.
    The genai_model_instance is now passed directly.
    """
    llm_input_data = {
        "title": protocol_title,
        "datum": protocol_date,
        "tops": current_tops_content_list # This is now List[str]
    }
    full_prompt_parts = [
        selection_prompt_template,
        json.dumps(llm_input_data, ensure_ascii=False)
    ]
    log.debug(f"Sending data to LLM for TOP selection. Title: {protocol_title}, Date: {protocol_date}, TOPs count: {len(current_tops_content_list)}")
    try:
        generation_config = {
            "response_mime_type": "application/json",
            "response_schema": TopsEvaluationResponse  # Pass the Pydantic model here
        }
        # Assuming genai_model_instance is a configured GenerativeModel instance
        response = genai_model_instance.generate_content(
            contents=full_prompt_parts,
            generation_config=generation_config
        )
        # The response.text should be directly usable if the LLM respects the schema.
        # Pydantic validation happens automatically if the schema is part of generation_config
        # and the response is directly a Pydantic model instance or can be parsed into one.
        # Forcing json.loads here might be redundant if response.text is already the parsed object
        # due to the schema, but it depends on the exact behavior of genai_client.generate_content
        # when a response_schema is provided. Assuming response.text is a string needing parsing for now.
        selected_data = json.loads(response.text)
        log.debug(f"Received {len(selected_data.get('tops_evaluation', []))} evaluated TOPs from LLM for protocol {protocol_title}")
        log.info(f"Waiting for {delay_duration} seconds before next API call.")
        time.sleep(delay_duration)
        return selected_data
    except json.JSONDecodeError as e:
        log.error(f"Error decoding JSON response from LLM for protocol {protocol_title}: {e}. Response text: {response.text if 'response' in locals() else 'No response object'}", exc_info=True)
        return None
    except Exception as e: # Catch other GenAI errors
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
        genai.configure(api_key=genai_api_key) # Configure the SDK
        # Create a GenerativeModel instance
        # Assuming GENAI_ARTICLE_GENERATION_MODEL is appropriate for this JSON task
        # If a specific model for relevance determination exists in config, it should be used.
        genai_model_instance = genai.GenerativeModel(config.GENAI_ARTICLE_GENERATION_MODEL)
        log.info(f"Google GenAI model '{config.GENAI_ARTICLE_GENERATION_MODEL}' initialized for relevance determination.")


        delay_duration = config.load_api_call_delay()
        log.info(f"API call delay set to {delay_duration} seconds.")

        chroma_collection = db_loader.initialize_chroma_collection(
            db_path_name=config.CHROMA_DB_DIR_NAME,
            collection_name=config.CHROMA_COLLECTION_NAME,
            project_root=config.PROJECT_ROOT
        )
        log.info(f"ChromaDB collection '{config.CHROMA_COLLECTION_NAME}' initialized for relevance determination.")
    except Exception as e:
        log.critical(f"CRITICAL: Initialization error (GenAI client/model or ChromaDB) in relevance determination: {e}", exc_info=True)
        return

    try:
        log.info("Fetching all TOPs from ChromaDB for relevance determination.")
        # Fetch 'top_sequence_in_protocol' if available, though not strictly used by LLM input, good for reference
        results = chroma_collection.get(include=['documents', 'metadatas', 'ids']) # Fetch all
        log.info(f"Retrieved {len(results.get('ids', []))} TOP entries from ChromaDB.")
    except Exception as e:
        log.error(f"Error querying ChromaDB for all TOPs: {e}", exc_info=True)
        return

    grouped_protocols = {}
    if results and results['ids']:
        for i in range(len(results['ids'])):
            chroma_id = results['ids'][i]
            metadata = results['metadatas'][i]
            document = results['documents'][i] # This is the TOP content
            protocol_title = metadata.get('protocol_title', "Unknown Title")
            protocol_date = metadata.get('protocol_date', "Unknown Date")
            # top_sequence_in_protocol = metadata.get('top_sequence_in_protocol') # Available if set by pdf_processor

            protocol_key = (protocol_title, protocol_date)
            if protocol_key not in grouped_protocols:
                grouped_protocols[protocol_key] = {'tops_data': []} # Changed 'tops' to 'tops_data' for clarity

            # Store chroma_id, content, and original metadata
            grouped_protocols[protocol_key]['tops_data'].append({
                'chroma_id': chroma_id,
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
        all_tops_for_protocol = data['tops_data']
        log.info(f"Processing protocol: {protocol_title} ({protocol_date}) for relevance determination.")

        tops_content_list_for_llm = []
        index_to_chroma_id_map = [] # Maps 0-based index of LLM input list to chroma_id

        for top_entry in all_tops_for_protocol:
            # Only process if 'is_relevant' is not already set (None or missing)
            if top_entry['metadata'].get('is_relevant') is None:
                if top_entry['content'] and top_entry['content'].strip():
                    tops_content_list_for_llm.append(top_entry['content'])
                    index_to_chroma_id_map.append(top_entry['chroma_id'])
                else:
                    log.warning(f"Skipping TOP with Chroma ID {top_entry.get('chroma_id')} for LLM input due to missing or empty content for protocol {protocol_title} ({protocol_date}).")
            else:
                log.debug(f"TOP with Chroma ID {top_entry['chroma_id']} already has 'is_relevant' set to {top_entry['metadata']['is_relevant']}. Skipping LLM evaluation for this TOP.")

        if not tops_content_list_for_llm:
            log.info(f"No TOPs requiring relevance determination in protocol {protocol_title} ({protocol_date}). Skipping LLM call.")
            continue

        log.info(f"Sending {len(tops_content_list_for_llm)} TOPs from protocol {protocol_title} ({protocol_date}) to LLM for relevance evaluation.")
        llm_evaluation_data = get_relevant_tops_with_llm(
            protocol_title=protocol_title,
            protocol_date=protocol_date,
            current_tops_content_list=tops_content_list_for_llm,
            genai_model_instance=genai_model_instance, # Pass the model instance
            selection_prompt_template=prompts.GENAI_TOPIC_SELECTION_PROMPT,
            delay_duration=delay_duration
        )

        protocol_updated_count = 0
        if llm_evaluation_data and isinstance(llm_evaluation_data.get('tops_evaluation'), list):
            for evaluated_top in llm_evaluation_data.get('tops_evaluation', []):
                original_index = evaluated_top.get('original_index')
                llm_relevance_status = evaluated_top.get('is_selected_relevant')
                content_preview = evaluated_top.get('content_preview', "N/A") # Get content_preview for logging

                if original_index is None or not isinstance(llm_relevance_status, bool):
                    log.warning(f"Invalid item from LLM evaluation for {protocol_title} ({protocol_date}): missing 'original_index' or 'is_selected_relevant' is not boolean. Data: {evaluated_top}")
                    continue

                if not (0 <= original_index < len(index_to_chroma_id_map)):
                    log.error(f"LLM returned invalid 'original_index' {original_index} for protocol {protocol_title} ({protocol_date}). Max valid index: {len(index_to_chroma_id_map) - 1}. Skipping this evaluation.")
                    continue

                chroma_id_for_update = index_to_chroma_id_map[original_index]
                if chroma_id_for_update:
                    update_success = db_loader.update_top_relevance(
                        top_id=chroma_id_for_update,
                        is_relevant=llm_relevance_status,
                        collection=chroma_collection
                    )
                    if update_success:
                        log.info(f"Successfully set 'is_relevant={llm_relevance_status}' for TOP (Chroma ID {chroma_id_for_update}, Original Index {original_index}, Preview: '{content_preview}').")
                        protocol_updated_count += 1
                    else:
                        log.error(f"Failed to update 'is_relevant' for TOP (Chroma ID {chroma_id_for_update}, Original Index {original_index}).")
                else:
                    # This case should ideally not be reached if original_index is validated against map bounds
                    log.warning(f"Could not map LLM-evaluated original_index '{original_index}' back to a Chroma ID for protocol {protocol_title} ({protocol_date}). This indicates an issue with index_to_chroma_id_map or the LLM response.")
            log.info(f"Updated 'is_relevant' status for {protocol_updated_count} TOPs in protocol {protocol_title} ({protocol_date}).")
            total_updated_count += protocol_updated_count
        elif llm_evaluation_data:
             log.warning(f"LLM output for {protocol_title} ({protocol_date}) did not match expected structure (e.g., 'tops_evaluation' not a list). LLM Output (first 300 chars): {str(llm_evaluation_data)[:300]}")
        else:
            log.warning(f"LLM-based TOP evaluation failed or returned no data for protocol {protocol_title} ({protocol_date}). No TOPs updated.")

    log.info(f"Relevance determination process finished. Total TOPs updated: {total_updated_count}.")

if __name__ == "__main__":
    # This allows running the step directly for testing if needed
    log.info(f"Executing relevance_determiner.py directly. Project root: {config.PROJECT_ROOT}")
    run_relevance_determination()
