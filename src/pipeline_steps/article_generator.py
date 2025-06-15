import os
import json
import logging
import pathlib
import sys
import google.generativeai as genai
import chromadb
import ollama
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

def run_article_generation():
    """
    Fetches all TOPs from ChromaDB, groups them by protocol, uses an LLM to select
    relevant TOPs, updates their relevance, finds references, and marks them as
    article_generated in ChromaDB.
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

    # Construct ChromaDB where_filter # Removed
    # Date filtering logic removed.

    try:
        log.info("Fetching all TOPs from ChromaDB.")
        results = chroma_collection.get(where=None, include=['documents', 'metadatas', 'ids'])
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
                'content': document,
                'metadata': metadata # Ensure full metadata is carried
            })
        log.info(f"Grouped TOPs into {len(grouped_protocols)} unique protocols based on title and date.")
    else:
        log.info("No TOPs found in ChromaDB matching the criteria.")
        return

    # Main loop for processing grouped TOPs
    for protocol_key, data in grouped_protocols.items():
        protocol_title, protocol_date = protocol_key
        all_tops_for_protocol = data['tops']

        log.info(f"Processing protocol: {protocol_title} ({protocol_date}) for relevance determination.")

        tops_to_evaluate_for_llm = []
        top_number_to_chroma_id_map_for_undetermined = {}

        for top_data in all_tops_for_protocol:
            if top_data['metadata'].get('is_relevant') is None:
                if top_data['top_number'] and top_data['content']:
                    tops_to_evaluate_for_llm.append({'top_id': top_data['top_number'], 'content': top_data['content']})
                    top_number_to_chroma_id_map_for_undetermined[top_data['top_number']] = top_data['chroma_id']
                else:
                    log.warning(f"Skipping TOP {top_data.get('chroma_id')} for LLM input due to missing top_number or content for protocol {protocol_title} ({protocol_date}).")
            else:
                log.info(f"Skipping TOP {top_data['chroma_id']} (Original: {top_data['top_number']}) for relevance determination as 'is_relevant' is already set to {top_data['metadata']['is_relevant']}.")

        if not tops_to_evaluate_for_llm:
            log.info(f"No TOPs requiring relevance determination in protocol {protocol_title} ({protocol_date}). Skipping LLM call.")
            continue

        llm_evaluation_data = get_relevant_tops_with_llm(
            protocol_title=protocol_title,
            protocol_date=protocol_date,
            current_tops=tops_to_evaluate_for_llm,
            genai_client=genai_client,
            model_name=config.GENAI_ARTICLE_GENERATION_MODEL, # Ensure this is the model for selection/evaluation
            selection_prompt_template=config.GENAI_TOPIC_SELECTION_PROMPT
        )

        updated_count = 0
        if llm_evaluation_data and isinstance(llm_evaluation_data.get('tops_evaluation'), list):
            for evaluated_top in llm_evaluation_data.get('tops_evaluation', []):
                original_top_id_from_llm = evaluated_top.get('top_id')
                llm_relevance_status = evaluated_top.get('is_selected_relevant')

                if original_top_id_from_llm is None or not isinstance(llm_relevance_status, bool):
                    log.warning(f"Invalid item from LLM evaluation for {protocol_title} ({protocol_date}): missing 'top_id' or 'is_selected_relevant' is not boolean. Data: {evaluated_top}")
                    continue

                chroma_id_for_update = top_number_to_chroma_id_map_for_undetermined.get(original_top_id_from_llm)

                if chroma_id_for_update:
                    update_success = db_loader.update_top_relevance(
                        top_id=chroma_id_for_update,
                        is_relevant=llm_relevance_status,
                        collection=chroma_collection
                    )
                    if update_success:
                        log.info(f"Successfully set 'is_relevant={llm_relevance_status}' for TOP (original ID {original_top_id_from_llm}, Chroma ID {chroma_id_for_update}).")
                        updated_count += 1

                        if llm_relevance_status is True: # Only proceed if LLM marked it as relevant
                            # --- Reference finding and Article Gen flag logic ---
                            current_top_details = db_loader.get_top_by_id(chroma_id_for_update, chroma_collection)
                            if not current_top_details or not current_top_details.get('document'):
                                log.warning(f"Could not fetch document for TOP {chroma_id_for_update} (Original ID: {original_top_id_from_llm}) to find references. Skipping reference finding.")
                            else: # Document fetched, proceed with reference finding
                                document_content = current_top_details['document']
                                num_similar_to_find = config.SIMILAR_DOCS_COUNT
                                query_embedding = None
                                try:
                                    log.debug(f"Generating Ollama embedding for query text (TOP ID {chroma_id_for_update}, Original ID: {original_top_id_from_llm}) using model {config.OLLAMA_EMBEDDING_MODEL}...")
                                    query_embedding = ollama.embeddings(model=config.OLLAMA_EMBEDDING_MODEL, prompt=document_content)["embedding"]
                                    log.debug(f"Query embedding generated for TOP ID {chroma_id_for_update} (Original ID: {original_top_id_from_llm}).")
                                except Exception as e_embed:
                                    log.error(f"Error generating Ollama embedding for query for TOP ID {chroma_id_for_update} (Original ID: {original_top_id_from_llm}): {e_embed}", exc_info=True)

                                if query_embedding:
                                    try:
                                        log.debug(f"Querying ChromaDB with embedding for TOP ID {chroma_id_for_update} (Original ID: {original_top_id_from_llm})...")
                                        query_results = chroma_collection.query(query_embeddings=[query_embedding], n_results=num_similar_to_find + 1, include=['ids'])
                                        retrieved_ids = query_results['ids'][0] if query_results and query_results.get('ids') and query_results['ids'] else []
                                        similar_top_chroma_ids = []
                                        if retrieved_ids:
                                            for found_id in retrieved_ids:
                                                if found_id == chroma_id_for_update: continue
                                                similar_top_chroma_ids.append(found_id)
                                                if len(similar_top_chroma_ids) >= num_similar_to_find: break
                                        if similar_top_chroma_ids:
                                            log.info(f"Found {len(similar_top_chroma_ids)} similar TOP(s) for {chroma_id_for_update} (Original ID: {original_top_id_from_llm}): {similar_top_chroma_ids}")
                                            references_updated = db_loader.update_top_references(top_id=chroma_id_for_update, references_top_ids=similar_top_chroma_ids, collection=chroma_collection)
                                            if not references_updated: log.error(f"Failed to update references for TOP {chroma_id_for_update} (Original ID: {original_top_id_from_llm}).")
                                        else:
                                            log.info(f"No distinct similar TOPs found for {chroma_id_for_update} (Original ID: {original_top_id_from_llm}) after processing query results.")
                                    except Exception as e_query:
                                        log.error(f"Error querying similar TOPs with embedding for {chroma_id_for_update} (Original ID: {original_top_id_from_llm}): {e_query}", exc_info=True)
                                else: # if query_embedding generation failed
                                    log.warning(f"Skipping ChromaDB query for references for TOP ID {chroma_id_for_update} (Original ID: {original_top_id_from_llm}) because query embedding generation failed.")

                            # Article generation status update (still inside "if llm_relevance_status is True:")
                            log.info(f"Simulating article generation for relevant TOP {chroma_id_for_update} (Original ID: {original_top_id_from_llm})...")
                            article_status_updated = db_loader.update_article_generated_status(top_id=chroma_id_for_update, article_generated=True, collection=chroma_collection)
                            if article_status_updated: log.info(f"Marked TOP {chroma_id_for_update} as article_generated=True.")
                            else: log.error(f"Failed to mark TOP {chroma_id_for_update} as article_generated=True.")
                            # --- End of conditional block for relevant TOPs ---
                    else: # if update_top_relevance failed
                        log.error(f"Failed to update 'is_relevant' for TOP (original ID {original_top_id_from_llm}, Chroma ID {chroma_id_for_update}).")
                else: # if chroma_id_for_update not found in map
                    log.warning(f"Could not map LLM-evaluated TOP ID '{original_top_id_from_llm}' back to a Chroma ID for protocol {protocol_title} ({protocol_date}). Was it part of the input to LLM for this protocol batch?")
            log.info(f"Updated 'is_relevant' status for {updated_count} TOPs in protocol {protocol_title} ({protocol_date}) based on LLM evaluation.")
        elif llm_evaluation_data: # LLM returned data, but not in the expected structure
             log.warning(f"LLM output for {protocol_title} ({protocol_date}) did not match expected structure (e.g., missing 'tops_evaluation' list). LLM Output: {str(llm_evaluation_data)[:300]}")
        else: # LLM call failed or returned None
            log.warning(f"LLM-based TOP evaluation failed or returned no data for protocol {protocol_title} ({protocol_date}). No TOPs updated for this protocol batch.")

    log.info("TOP relevance update process in ChromaDB finished.")

if __name__ == "__main__":
    print(f"Executing article_generator.py directly. Project root: {config.PROJECT_ROOT}")
    run_article_generation()
