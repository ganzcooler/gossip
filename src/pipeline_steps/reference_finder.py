# src/pipeline_steps/reference_finder.py
import logging # Keep for potential direct use
import pathlib
import sys
import ollama # For embedding generation

# Ensure src directory is in sys.path for config import
project_root_for_import = pathlib.Path(__file__).resolve().parent.parent.parent
if str(project_root_for_import) not in sys.path:
    sys.path.insert(0, str(project_root_for_import))

try:
    from src import config
    from src.pipeline_steps import db_loader
except ImportError as e:
    temp_log = logging.getLogger(__name__)
    temp_log.error(f"Error importing modules in reference_finder.py: {e}")
    # Fallback print
    print(f"CRITICAL: Error importing modules in reference_finder.py: {e}. Check sys.path.", file=sys.stderr)
    raise

# Initialize logger using the new constant
log = config.get_logger(__name__, config.REFERENCE_FINDER_LOG_FILENAME)

def run_reference_finding():
    """
    Fetches TOPs marked as relevant, generates embeddings, queries ChromaDB for similar TOPs,
    and stores these references.
    """
    log.info("Starting reference finding process for relevant TOPs...")

    try:
        chroma_collection = db_loader.initialize_chroma_collection(
            db_path_name=config.CHROMA_DB_DIR_NAME,
            collection_name=config.CHROMA_COLLECTION_NAME,
            project_root=config.PROJECT_ROOT
        )
        log.info(f"ChromaDB collection '{config.CHROMA_COLLECTION_NAME}' initialized for reference finding.")
    except Exception as e:
        log.critical(f"CRITICAL: Initialization error (ChromaDB) in reference finding: {e}", exc_info=True)
        return

    try:
        # Fetch only TOPs that are marked as relevant and don't have references yet (optional)
        # For now, fetching all relevant ones. Logic can be added to filter those with existing references.
        log.info("Fetching relevant TOPs from ChromaDB for reference finding (is_relevant = True).")
        # The metadata value for boolean True in ChromaDB is just True, not "true"
        relevant_tops_results = chroma_collection.get(
            where={"is_relevant": True},
            include=['documents', 'metadatas', 'ids']
        )
        log.info(f"Retrieved {len(relevant_tops_results.get('ids', []))} relevant TOP entries for reference finding.")
    except Exception as e:
        log.error(f"Error querying ChromaDB for relevant TOPs: {e}", exc_info=True)
        return

    if not relevant_tops_results or not relevant_tops_results['ids']:
        log.info("No relevant TOPs found to process for reference finding.")
        return

    processed_count = 0
    updated_reference_count = 0

    for i in range(len(relevant_tops_results['ids'])):
        chroma_id = relevant_tops_results['ids'][i]
        document_content = relevant_tops_results['documents'][i]
        metadata = relevant_tops_results['metadatas'][i]
        original_top_number = metadata.get('top_number', 'N/A') # For logging

        # Check if references already exist and skip if needed (optional optimization)
        # if metadata.get('references_top_ids') is not None:
        #     log.debug(f"TOP {chroma_id} (Original: {original_top_number}) already has references. Skipping.")
        #     continue

        if not document_content:
            log.warning(f"Skipping TOP {chroma_id} (Original: {original_top_number}) for reference finding due to empty document content.")
            continue

        log.info(f"Processing TOP {chroma_id} (Original: {original_top_number}) for reference finding.")
        processed_count += 1
        query_embedding = None
        try:
            log.debug(f"Generating Ollama embedding for query text (TOP ID {chroma_id}) using model {config.OLLAMA_EMBEDDING_MODEL}...")
            response = ollama.embeddings(model=config.OLLAMA_EMBEDDING_MODEL, prompt=document_content)
            query_embedding = response["embedding"]
            log.debug(f"Query embedding generated for TOP ID {chroma_id}.")
        except Exception as e_embed:
            log.error(f"Error generating Ollama embedding for TOP ID {chroma_id}: {e_embed}", exc_info=True)
            continue # Skip to next TOP if embedding fails

        if query_embedding:
            try:
                num_similar_to_find = config.SIMILAR_DOCS_COUNT
                log.debug(f"Querying ChromaDB with embedding for TOP ID {chroma_id} to find {num_similar_to_find} similar docs...")
                # Query for n+1 results to exclude the item itself if it's returned
                query_results = chroma_collection.query(
                    query_embeddings=[query_embedding],
                    n_results=num_similar_to_find + 1, # Fetch one extra to allow self-removal
                    include=['ids', 'metadatas'] # Include metadatas to check for relevance
                )

                retrieved_ids = query_results['ids'][0] if query_results and query_results.get('ids') and query_results['ids'] else []
                retrieved_metadatas = query_results['metadatas'][0] if query_results and query_results.get('metadatas') and query_results['metadatas'] else []

                similar_top_chroma_ids = []
                if retrieved_ids:
                    for idx, found_id in enumerate(retrieved_ids):
                        if found_id == chroma_id: # Exclude self
                            continue
                        # Optionally, filter references to also be relevant.
                        # For now, any similar TOP is considered a reference.
                        # found_metadata = retrieved_metadatas[idx]
                        # if found_metadata.get("is_relevant") is not True:
                        #    log.debug(f"Skipping potential reference {found_id} for TOP {chroma_id} as it is not marked relevant.")
                        #    continue

                        similar_top_chroma_ids.append(found_id)
                        if len(similar_top_chroma_ids) >= num_similar_to_find:
                            break

                if similar_top_chroma_ids:
                    log.info(f"Found {len(similar_top_chroma_ids)} similar TOP(s) for {chroma_id} (Original: {original_top_number}): {similar_top_chroma_ids}")
                    references_updated = db_loader.update_top_references(
                        top_id=chroma_id,
                        references_top_ids=similar_top_chroma_ids,
                        collection=chroma_collection
                    )
                    if references_updated:
                        log.info(f"Successfully updated references for TOP {chroma_id}.")
                        updated_reference_count += 1
                    else:
                        log.error(f"Failed to update references for TOP {chroma_id}.")
                else:
                    log.info(f"No distinct similar TOPs found for {chroma_id} (Original: {original_top_number}).")
            except Exception as e_query:
                log.error(f"Error querying similar TOPs or updating references for {chroma_id}: {e_query}", exc_info=True)
        else:
            log.warning(f"Skipping ChromaDB query for references for TOP ID {chroma_id} because query embedding generation failed.")

    log.info(f"Reference finding process finished. Processed {processed_count} relevant TOPs. Updated references for {updated_reference_count} TOPs.")

if __name__ == "__main__":
    log.info(f"Executing reference_finder.py directly. Project root: {config.PROJECT_ROOT}")
    run_reference_finding()
