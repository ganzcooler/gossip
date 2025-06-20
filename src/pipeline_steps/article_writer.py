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

import os # Added for path operations
import re # Added for filename sanitization
# Initialize logger using the new constant
log = config.get_logger(__name__, config.ARTICLE_WRITER_LOG_FILENAME)

def sanitize_filename(name: str) -> str:
    """Sanitizes a string to be a valid filename."""
    name = re.sub(r'[^\w\s-]', '', name) # Remove non-alphanumeric, non-whitespace, non-hyphen
    name = re.sub(r'[-\s]+', '-', name).strip('-_') # Replace whitespace/hyphens with single hyphen
    return name

def generate_html_article(top_content: str, top_number: str = "N/A") -> str:
    """
    Generates a simple HTML article from TOP content.
    """
    # Basic HTML structure
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TOP Article: {top_number}</title>
    <style>
        body {{ font-family: sans-serif; margin: 20px; line-height: 1.6; }}
        h1 {{ color: #333; }}
        p {{ text-align: justify; }}
    </style>
</head>
<body>
    <h1>TOP Content (Original TOP Number: {top_number})</h1>
    <pre style="white-space: pre-wrap; word-wrap: break-word;">{top_content}</pre>
</body>
</html>
"""
    return html_content

def run_article_writing():
    """
    Fetches relevant TOPs, generates HTML articles for them, saves them to files,
    and marks them as 'article_generated' in ChromaDB.
    """
    log.info("Starting article writing process (saving HTML to files)...")

    # Create generated_articles directory if it doesn't exist
    articles_dir = config.PROJECT_ROOT / "generated_articles"
    try:
        articles_dir.mkdir(parents=True, exist_ok=True)
        log.info(f"Ensured 'generated_articles' directory exists at: {articles_dir}")
    except OSError as e:
        log.error(f"Error creating directory {articles_dir}: {e}", exc_info=True)
        return # Cannot proceed if directory creation fails

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
        log.info("Fetching relevant TOPs from ChromaDB for article writing (is_relevant = True).")
        relevant_tops_results = chroma_collection.get(
            where={"is_relevant": True},
            include=['ids', 'metadatas', 'documents'] # Added 'documents' to get TOP content
        )
        log.info(f"Retrieved {len(relevant_tops_results.get('ids', []))} relevant TOP entries for article generation.")
    except Exception as e:
        log.error(f"Error querying ChromaDB for relevant TOPs: {e}", exc_info=True)
        return

    if not relevant_tops_results or not relevant_tops_results['ids']:
        log.info("No relevant TOPs found for article generation.")
        return

    generated_count = 0
    skipped_count = 0
    error_count = 0

    for i in range(len(relevant_tops_results['ids'])):
        chroma_id = relevant_tops_results['ids'][i]
        metadata = relevant_tops_results['metadatas'][i]
        document_content = relevant_tops_results['documents'][i] if relevant_tops_results['documents'] and len(relevant_tops_results['documents']) > i else None
        original_top_number = metadata.get('top_number', 'N/A')

        # Check if article_generated is already True.
        # We no longer check for html_content in metadata for skipping,
        # as the source of truth is now the file system + article_generated flag.
        # A more robust check could see if the file already exists, but that's an enhancement.
        if metadata.get('article_generated') is True:
            log.debug(f"TOP {chroma_id} (Original: {original_top_number}) is already marked as article_generated. Skipping file generation.")
            skipped_count += 1
            continue

        if not document_content:
            log.warning(f"TOP {chroma_id} (Original: {original_top_number}) has no document content. Skipping HTML file generation.")
            error_count += 1
            continue

        log.info(f"Generating HTML article file for TOP {chroma_id} (Original: {original_top_number}).")
        try:
            html_article_content = generate_html_article(document_content, original_top_number)

            # Sanitize top_number for filename
            sanitized_top_number = sanitize_filename(original_top_number if original_top_number != "N/A" else chroma_id)
            if not sanitized_top_number: # Fallback if sanitization results in empty string
                sanitized_top_number = chroma_id
            filename = f"TOP_{sanitized_top_number}.html"
            filepath = articles_dir / filename

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(html_article_content)
            log.info(f"Successfully generated and saved HTML article to: {filepath}")

            # Prepare metadata update: only article_generated = True
            # Remove 'html_content' if it exists from previous runs.
            updated_metadata = {k: v for k, v in metadata.items() if k != 'html_content'}
            updated_metadata['article_generated'] = True

            chroma_collection.update(
                ids=[chroma_id],
                metadatas=[updated_metadata]
            )
            log.info(f"Marked TOP {chroma_id} as article_generated=True in ChromaDB.")
            generated_count += 1
        except Exception as e:
            log.error(f"Error generating or saving HTML file for TOP {chroma_id} (Original: {original_top_number}): {e}", exc_info=True)
            error_count += 1

    log.info(f"Article writing process finished. Generated {generated_count} new HTML article files. Skipped {skipped_count} already marked TOPs. Encountered {error_count} errors.")

if __name__ == "__main__":
    log.info(f"Executing article_writer.py directly. Project root: {config.PROJECT_ROOT}")
    run_article_writing()
