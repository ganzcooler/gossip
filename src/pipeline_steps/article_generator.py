import os
import json
import logging
import pathlib
import sys
import google.generativeai as genai
import chromadb
from src.pipeline_steps import db_loader

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
    log.info("Starting TOP relevance update process in ChromaDB...")

    try:
        genai_api_key = config.load_google_api_key()
        genai_client = genai.Client(api_key=genai_api_key)
        log.info("Google GenAI client initialized.")

        chroma_collection = db_loader.initialize_chroma_collection(
            db_path_name=config.CHROMA_DB_DIR_NAME,
            collection_name=config.CHROMA_COLLECTION_NAME,
            project_root=config.PROJECT_ROOT
        )
    except Exception as e:
        log.critical(f"CRITICAL: Initialization error (GenAI client or ChromaDB): {e}", exc_info=True)
        return

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
        results = chroma_collection.get(where=where_filter if where_filter else None, include=['documents', 'metadatas', 'ids'])
        log.info(f"Retrieved {len(results.get('ids', []))} TOP entries from ChromaDB.")
    except Exception as e:
        log.error(f"Error querying ChromaDB: {e}", exc_info=True)
        return

    # Group TOPs by (protocol_title, protocol_date)
    grouped_protocols = {}
    if results and results['ids']:
        for i in range(len(results['ids'])):
            chroma_id = results['ids'][i]
            metadata = results['metadatas'][i]
            document = results['documents'][i]

            protocol_title = metadata.get('protocol_title', "Unknown Title")
            protocol_date = metadata.get('protocol_date', "Unknown Date")
            top_number = metadata.get('top_number') # This is the original TOP ID/number

            if not top_number:
                log.warning(f"Skipping entry with Chroma ID {chroma_id} due to missing 'top_number' in metadata: {metadata}")
                continue

            protocol_key = (protocol_title, protocol_date)

            if protocol_key not in grouped_protocols:
                grouped_protocols[protocol_key] = {
                    'tops': []
                }

            grouped_protocols[protocol_key]['tops'].append({
                'chroma_id': chroma_id,
                'top_number': top_number,
                'content': document
            })
        log.info(f"Grouped TOPs into {len(grouped_protocols)} unique protocols based on title and date.")
    else:
        log.info("No TOPs found in ChromaDB matching the criteria.")
        return

    # Main loop for processing grouped TOPs
    for protocol_key, data in grouped_protocols.items():
        protocol_title, protocol_date = protocol_key
        current_protocol_tops = data['tops'] # list of {'chroma_id', 'top_number', 'content'}

        log.info(f"Processing protocol: {protocol_title} ({protocol_date}) for LLM-based TOP relevance selection.")

        tops_for_llm_input = []
        top_number_to_chroma_id_map = {}
        for top_data in current_protocol_tops:
            if top_data['top_number'] and top_data['content']: # Ensure essential data is present
                tops_for_llm_input.append({'top_id': top_data['top_number'], 'content': top_data['content']})
                top_number_to_chroma_id_map[top_data['top_number']] = top_data['chroma_id']
            else:
                log.warning(f"Skipping TOP due to missing top_number or content for protocol {protocol_title} ({protocol_date}). Data: {top_data}")

        if not tops_for_llm_input:
            log.info(f"No suitable TOPs for LLM selection in protocol {protocol_title} ({protocol_date}). Skipping.")
            continue

        selected_tops_data = get_relevant_tops_with_llm(
            protocol_title=protocol_title,
            protocol_date=protocol_date,
            current_tops=tops_for_llm_input, # This is the list of {'top_id', 'content'}
            genai_client=genai_client,
            model_name=config.GENAI_ARTICLE_GENERATION_MODEL,
            selection_prompt_template=config.GENAI_TOPIC_SELECTION_PROMPT
        )

        if selected_tops_data and isinstance(selected_tops_data.get('tops'), list):
            selected_count = 0
            for selected_top in selected_tops_data.get('tops', []):
                original_top_id_from_llm = selected_top.get('top_id')
                if not original_top_id_from_llm:
                    log.warning(f"LLM-selected TOP for {protocol_title} ({protocol_date}) missing 'top_id'. Data: {selected_top}")
                    continue

                chroma_id_for_update = top_number_to_chroma_id_map.get(original_top_id_from_llm)

                if chroma_id_for_update:
                    success = db_loader.update_top_relevance(
                        top_id=chroma_id_for_update,
                        is_relevant=True,
                        collection=chroma_collection
                    )
                    if success:
                        selected_count +=1
                        log.info(f"Successfully updated relevance for TOP (original ID {original_top_id_from_llm}, Chroma ID {chroma_id_for_update}) in protocol {protocol_title} ({protocol_date}).")

                        # --- New logic for finding and storing references starts here ---
                        current_top_details = db_loader.get_top_by_id(chroma_id_for_update, chroma_collection)
                        if not current_top_details or not current_top_details.get('document'):
                            log.warning(f"Could not fetch document for TOP {chroma_id_for_update} (Original ID: {original_top_id_from_llm}) to find references. Skipping reference finding.")
                            continue # Skip to next selected_top_from_llm
                        document_content = current_top_details['document']

                        num_similar_to_find = config.SIMILAR_DOCS_COUNT
                        log.debug(f"Querying for {num_similar_to_find} similar TOPs for TOP ID {chroma_id_for_update} (Original ID: {original_top_id_from_llm})")

                        try:
                            query_results = chroma_collection.query(
                                query_texts=[document_content],
                                n_results=num_similar_to_find + 1,
                                include=['ids']
                            )
                            retrieved_ids = query_results['ids'][0] if query_results and query_results.get('ids') and query_results['ids'] else []
                        except Exception as e:
                            log.error(f"Error querying similar TOPs for {chroma_id_for_update} (Original ID: {original_top_id_from_llm}): {e}", exc_info=True)
                            continue # Skip to next selected_top_from_llm

                        similar_top_chroma_ids = []
                        if retrieved_ids: # Ensure there are IDs to process
                            for found_id in retrieved_ids:
                                if found_id == chroma_id_for_update: # Compare with the ID of the current TOP being processed
                                    continue
                                similar_top_chroma_ids.append(found_id)
                                if len(similar_top_chroma_ids) >= num_similar_to_find:
                                    break

                        if similar_top_chroma_ids:
                            log.info(f"Found {len(similar_top_chroma_ids)} similar TOP(s) for {chroma_id_for_update} (Original ID: {original_top_id_from_llm}): {similar_top_chroma_ids}")
                            references_updated = db_loader.update_top_references(
                                top_id=chroma_id_for_update, # Use the ID of the current TOP
                                references_top_ids=similar_top_chroma_ids,
                                collection=chroma_collection
                            )
                            if not references_updated:
                                log.error(f"Failed to update references for TOP {chroma_id_for_update} (Original ID: {original_top_id_from_llm}).")
                        else:
                            log.info(f"No distinct similar TOPs found for {chroma_id_for_update} (Original ID: {original_top_id_from_llm})")
                        # --- End of new logic for references ---

                        # --- New logic for article_generated flag starts here ---
                        # Placeholder for actual article generation logic
                        log.info(f"Simulating article generation for TOP {chroma_id_for_update} (Original ID: {original_top_id_from_llm})...")
                        # article_content_placeholder = f"Generated article for {original_top_id_from_llm}..."
                        # (Assume article is generated and saved, e.g., using original_top_id_from_llm, protocol_title, protocol_date for filename)

                        article_status_updated = db_loader.update_article_generated_status(
                            top_id=chroma_id_for_update,
                            article_generated=True,
                            collection=chroma_collection
                        )
                        if article_status_updated:
                            log.info(f"Marked TOP {chroma_id_for_update} (Original ID: {original_top_id_from_llm}) as article_generated=True.")
                        else:
                            log.error(f"Failed to mark TOP {chroma_id_for_update} (Original ID: {original_top_id_from_llm}) as article_generated=True.")
                        # --- End of new logic for article_generated flag ---
                    else:
                        log.error(f"Failed to update relevance for TOP (original ID {original_top_id_from_llm}, Chroma ID {chroma_id_for_update}) in protocol {protocol_title} ({protocol_date}).")
                else:
                    log.warning(f"Could not map LLM-selected TOP ID '{original_top_id_from_llm}' back to a Chroma ID for protocol {protocol_title} ({protocol_date}).")
            log.info(f"Marked {selected_count} TOPs as relevant and processed references in ChromaDB for protocol {protocol_title} ({protocol_date}).")
        elif selected_tops_data: # LLM returned data, but not in the expected structure
             log.warning(f"LLM output for {protocol_title} ({protocol_date}) did not match expected structure (missing 'tops' list or not a list). LLM Output: {str(selected_tops_data)[:300]}")
        else:
            log.warning(f"LLM-based TOP selection failed or returned no data for protocol {protocol_title} ({protocol_date}). No TOPs marked as relevant for this protocol.")

    log.info("TOP relevance update process in ChromaDB finished.")

if __name__ == "__main__":
    print(f"Executing article_generator.py directly. Project root: {config.PROJECT_ROOT}")
    # Example of running with date filters:
    # run_article_generation(start_date="2023-01-01", end_date="2023-12-31")
    run_article_generation()
