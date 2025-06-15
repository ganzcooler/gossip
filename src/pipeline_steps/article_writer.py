# src/pipeline_steps/article_writer.py
import logging # Keep for potential direct use
import pathlib
import sys

# Ensure src directory is in sys.path for config import
project_root_for_import = pathlib.Path(__file__).resolve().parent.parent.parent
if str(project_root_for_import) not in sys.path:
    sys.path.insert(0, str(project_root_for_import))

try:
    from src import config
    from src.pipeline_steps import db_loader
except ImportError as e:
    temp_log = logging.getLogger(__name__)
    temp_log.error(f"Error importing modules in article_writer.py: {e}")
    # Fallback print
    print(f"CRITICAL: Error importing modules in article_writer.py: {e}. Check sys.path.", file=sys.stderr)
    raise

# Initialize logger using the new constant
log = config.get_logger(__name__, config.ARTICLE_WRITER_LOG_FILENAME)

def run_article_writing():
    """
    Fetches relevant TOPs (and ideally, those with references) and marks them
    as 'article_generated' in ChromaDB. Actual article content generation is not performed.
    """
    log.info("Starting article writing process (simulated: marking TOPs as generated)...")

    try:
        chroma_collection = db_loader.initialize_chroma_collection(
            db_path_name=config.CHROMA_DB_DIR_NAME,
            collection_name=config.CHROMA_COLLECTION_NAME,
            project_root=config.PROJECT_ROOT
        )
        log.info(f"ChromaDB collection '{config.CHROMA_COLLECTION_NAME}' initialized for article writing.")
    except Exception as e:
        log.critical(f"CRITICAL: Initialization error (ChromaDB) in article writing: {e}", exc_info=True)
        return

    try:
        # Fetch TOPs that are marked as relevant.
        # Optionally, could also filter for 'references_top_ids' is not None,
        # but current logic from article_generator.py applies this to all relevant TOPs.
        log.info("Fetching relevant TOPs from ChromaDB for article writing (is_relevant = True).")
        # The metadata value for boolean True in ChromaDB is just True
        relevant_tops_results = chroma_collection.get(
            where={"is_relevant": True},
            include=['ids', 'metadatas'] # Only need IDs and metadatas to check 'article_generated' status
        )
        log.info(f"Retrieved {len(relevant_tops_results.get('ids', []))} relevant TOP entries for marking as article generated.")
    except Exception as e:
        log.error(f"Error querying ChromaDB for relevant TOPs to mark as generated: {e}", exc_info=True)
        return

    if not relevant_tops_results or not relevant_tops_results['ids']:
        log.info("No relevant TOPs found to mark as article generated.")
        return

    marked_count = 0
    skipped_count = 0

    for i in range(len(relevant_tops_results['ids'])):
        chroma_id = relevant_tops_results['ids'][i]
        metadata = relevant_tops_results['metadatas'][i]
        original_top_number = metadata.get('top_number', 'N/A') # For logging

        # Check if article_generated is already True
        if metadata.get('article_generated') is True:
            log.debug(f"TOP {chroma_id} (Original: {original_top_number}) is already marked as article_generated. Skipping.")
            skipped_count +=1
            continue

        log.info(f"Marking TOP {chroma_id} (Original: {original_top_number}) as article_generated=True.")
        # Simulate article generation by just updating the status
        article_status_updated = db_loader.update_article_generated_status(
            top_id=chroma_id,
            article_generated=True,
            collection=chroma_collection
        )
        if article_status_updated:
            log.info(f"Successfully marked TOP {chroma_id} as article_generated=True.")
            marked_count += 1
        else:
            log.error(f"Failed to mark TOP {chroma_id} as article_generated=True.")

    log.info(f"Article writing process (simulation) finished. Marked {marked_count} new TOPs as article_generated. Skipped {skipped_count} already marked TOPs.")

if __name__ == "__main__":
    log.info(f"Executing article_writer.py directly. Project root: {config.PROJECT_ROOT}")
    run_article_writing()
