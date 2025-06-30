# src/pipeline_steps/article_writer.py
import logging # Keep for potential direct use
import pathlib
import sys
import time # Added for API delay
import json # Added for JSON parsing
import google.generai as genai # Added for LLM
from google.api_core import exceptions as google_exceptions # Added for specific error handling
from pydantic import BaseModel, ValidationError # Added for Pydantic model and validation error
from typing import List # Added for potential future use, good practice

# Ensure src directory is in sys.path for config import
project_root_for_import = pathlib.Path(__file__).resolve().parent.parent.parent
if str(project_root_for_import) not in sys.path:
    sys.path.insert(0, str(project_root_for_import))

try:
    from src import config # For PROJECT_ROOT, CHROMA_DB_DIR_NAME, CHROMA_COLLECTION_NAME
    from src.pipeline_steps import db_loader
    # Specific config items for LLM
    from src.config import (
        load_google_api_key,
        GENAI_ARTICLE_GENERATION_MODEL,
        load_api_call_delay
    )
    from src.prompts import GENAI_JOURNALISTIC_ARTICLE_PROMPT # Moved from config
except ImportError as e:
    # Fallback print if logging isn't configured due to config import error
    # Use a basic logger setup or print if config fails, as 'log' might not be initialized.
    temp_log_article_writer = logging.getLogger("article_writer_bootstrap_error")
    temp_log_article_writer.error(f"Error importing modules/config in article_writer.py: {e}")
    print(f"CRITICAL: Error importing modules/config in article_writer.py: {e}. Check sys.path and config.py.", file=sys.stderr)
    raise # Re-raise to ensure failure is noted

import os # Already present
import re # Already present
import uuid # For generating unique article IDs

# Initialize logger using the new constant (config must be loaded by this point)
log = config.get_logger(__name__, config.ARTICLE_WRITER_LOG_FILENAME)


# --- Pydantic Model for LLM Response ---
class JournalisticArticleResponse(BaseModel):
    article_title: str
    article_body: str


# Local prompt template removed, will be imported from config.

def sanitize_filename(name: str) -> str:
    """Sanitizes a string to be a valid filename."""
    name = re.sub(r'[^\w\s-]', '', name)
    name = re.sub(r'[-\s]+', '-', name).strip('-_')
    return name

def generate_journalistic_article_llm(
    top_content: str,
    genai_model_instance, # Expecting an initialized genai.GenerativeModel
    prompt_template: str
) -> JournalisticArticleResponse | None: # Return type changed
    """
    Generates a journalistic article using the LLM, expecting a JSON response.
    """
    if not top_content:
        log.warning("LLM generation skipped: TOP content is empty.")
        return None

    formatted_prompt = prompt_template.format(TOP_CONTENT=top_content)
    # Log a snippet of the prompt for debugging, being mindful of not logging too much if content is large
    log.debug(f"Formatted prompt for LLM (first 200 chars): {formatted_prompt[:200]}...")

    # Define generation config for JSON output
    generation_config = genai.types.GenerationConfig(
        response_mime_type="application/json",
        # For Pydantic v2, this would be JournalisticArticleResponse.model_json_schema()
        # For some SDK versions, passing the class directly might be supported.
        # Let's assume the SDK handles Pydantic class directly or it's a simplified representation.
        # If this fails, `JournalisticArticleResponse.model_json_schema()` is the way for Pydantic v2.
        response_schema=JournalisticArticleResponse
    )

    try:
        response = genai_model_instance.generate_content(
            contents=[formatted_prompt],
            generation_config=generation_config
        )

        if not response.text: # Check if response.text is empty
            log.error("LLM response text is empty. Cannot parse JSON.")
            return None

        log.debug(f"Raw LLM response text: {response.text}")

        # Parse and validate the JSON response
        llm_output = json.loads(response.text)
        validated_data = JournalisticArticleResponse(**llm_output)

        log.info(f"Successfully parsed and validated LLM response: Title='{validated_data.article_title}'")
        return validated_data

    except json.JSONDecodeError as e:
        log.error(f"JSONDecodeError parsing LLM response: {e}. Response text: '{response.text if 'response' in locals() and hasattr(response, 'text') else 'Response text not available'}'", exc_info=True)
        return None
    except ValidationError as e: # Pydantic validation error
        log.error(f"Pydantic ValidationError for LLM response: {e}. LLM output: '{llm_output if 'llm_output' in locals() else 'LLM output not available'}'", exc_info=True)
        return None
    except google_exceptions.GoogleAPIError as e:
        log.error(f"Google API Error during LLM article generation: {e}", exc_info=True)
        return None
    except Exception as e:
        log.error(f"Unexpected error during LLM article generation: {e}", exc_info=True)
        return None

def generate_html_article(article_title: str, article_body: str, original_top_number: str) -> str:
    """
    Generates a simple HTML article from the LLM-generated title and body.
    original_top_number is used for non-content purposes like logging or context, not displayed.
    """
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{article_title}</title> {/* Use LLM generated title */}
    <style>
        body {{ font-family: sans-serif; margin: 20px; line-height: 1.6; }}
        h1 {{ color: #333; }}
        pre {{ white-space: pre-wrap; word-wrap: break-word; background-color: #f9f9f9; border: 1px solid #eee; padding: 15px; border-radius: 4px;}}
    </style>
</head>
<body>
    <h1>{article_title}</h1> {/* Use LLM generated title */}
    <pre>{article_body}</pre> {/* Use LLM generated body */}
</body>
</html>
"""
    return html_content

def run_article_writing():
    """
    Fetches relevant TOPs, uses an LLM to generate journalistic articles,
    saves these as HTML files, and marks them as 'article_generated' in ChromaDB.
    """
    log.info("Starting article writing process (LLM generation & saving HTML files)...")

    # Initialize Google Generative AI client
    genai_model_instance = None
    try:
        google_api_key = load_google_api_key()
        if not google_api_key:
            log.critical("Google API key not found. LLM generation disabled.")
            return # Cannot proceed without API key for LLM
        genai.configure(api_key=google_api_key)

        llm_model_name = GENAI_ARTICLE_GENERATION_MODEL
        if not llm_model_name:
            log.critical("GENAI_ARTICLE_GENERATION_MODEL not set in config. LLM generation disabled.")
            return # Cannot proceed without model name
        genai_model_instance = genai.GenerativeModel(llm_model_name)
        log.info(f"Google GenAI client initialized with model: {llm_model_name}")
    except Exception as e:
        log.critical(f"Failed to initialize Google GenAI client: {e}. LLM generation will be skipped.", exc_info=True)
        return # Stop if GenAI client cannot be initialized

    api_delay = load_api_call_delay() # Load delay, defaults to 0 if not set
    log.info(f"Using API call delay of {api_delay} seconds between LLM calls.")

    # Create generated_articles directory
    articles_dir = config.PROJECT_ROOT / "generated_articles"
    try:
        articles_dir.mkdir(parents=True, exist_ok=True)
        log.info(f"Ensured 'generated_articles' directory exists at: {articles_dir}")
    except OSError as e:
        log.error(f"Error creating directory {articles_dir}: {e}", exc_info=True)
        return

    # Initialize ChromaDB
    try:
        tops_collection = db_loader.initialize_chroma_collection(
            db_path_name=config.CHROMA_DB_DIR_NAME,
            collection_name=config.CHROMA_COLLECTION_NAME, # Existing TOPs collection
            project_root=config.PROJECT_ROOT
        )
        articles_collection = db_loader.initialize_chroma_collection(
            db_path_name=config.CHROMA_DB_DIR_NAME, # Same DB, different collection
            collection_name=config.CHROMA_ARTICLES_COLLECTION_NAME, # New articles collection
            project_root=config.PROJECT_ROOT
        )
        log.info(f"ChromaDB TOPs collection '{config.CHROMA_COLLECTION_NAME}' initialized.")
        log.info(f"ChromaDB Articles collection '{config.CHROMA_ARTICLES_COLLECTION_NAME}' initialized.")
    except Exception as e:
        log.critical(f"CRITICAL: Initialization error (ChromaDB): {e}", exc_info=True)
        return

    # Fetch relevant TOPs
    try:
        # We still fetch from the main TOPs collection
        relevant_tops_results = tops_collection.get(
            where={"is_relevant": True}, # Assuming 'is_relevant' is still key for selection
            include=['ids', 'metadatas', 'documents']
        )
        log.info(f"Retrieved {len(relevant_tops_results.get('ids', []))} relevant TOP entries from '{config.CHROMA_COLLECTION_NAME}'.")
    except Exception as e:
        log.error(f"Error querying ChromaDB for relevant TOPs: {e}", exc_info=True)
        return

    if not relevant_tops_results or not relevant_tops_results['ids']:
        log.info("No relevant TOPs found for article generation.")
        return

    # Get existing article IDs to avoid re-processing for this run if desired,
    # or rely on the image generator to check. For now, this step will generate
    # articles if they are not in the articles_collection.
    # A more robust check would be to query articles_collection for existing original_top_id.
    existing_article_original_top_ids = set()
    try:
        existing_articles = articles_collection.get(include=['metadatas'])
        if existing_articles and existing_articles['metadatas']:
            for meta in existing_articles['metadatas']:
                if meta and 'original_top_id' in meta:
                     existing_article_original_top_ids.add(meta['original_top_id'])
        log.info(f"Found {len(existing_article_original_top_ids)} TOP IDs already present in the articles collection.")
    except Exception as e:
        log.warning(f"Could not fetch existing articles to check for duplicates: {e}. May re-generate existing articles.", exc_info=True)


    generated_count = 0
    skipped_due_to_existing_article = 0
    error_count = 0

    for i in range(len(relevant_tops_results['ids'])):
        top_chroma_id = relevant_tops_results['ids'][i] # This is the ID from the 'tops_content' collection
        top_metadata = relevant_tops_results['metadatas'][i]
        top_document_content = relevant_tops_results['documents'][i] if relevant_tops_results['documents'] and len(relevant_tops_results['documents']) > i else None
        original_top_number_for_logging = top_metadata.get('top_number', 'N/A')

        # Check if an article for this TOP already exists in the articles_collection
        if top_chroma_id in existing_article_original_top_ids:
            log.debug(f"TOP {top_chroma_id} (Original: {original_top_number_for_logging}) already has an article in '{config.CHROMA_ARTICLES_COLLECTION_NAME}'. Skipping article generation.")
            skipped_due_to_existing_article +=1
            continue

        # The old check for 'article_generated' in top_metadata is removed.
        # if top_metadata.get('article_generated') is True:
        #     log.debug(f"TOP {top_chroma_id} (Original: {original_top_number_for_logging}) already marked 'article_generated'. Skipping.")
        #     skipped_count += 1 # old counter, can be removed or merged
        #     continue

        if not top_document_content:
            log.warning(f"TOP {top_chroma_id} (Original: {original_top_number_for_logging}) has no document content. Skipping LLM generation.")
            error_count += 1
            continue

        log.info(f"Processing TOP {top_chroma_id} (Original: {original_top_number_for_logging}) for LLM article generation.")

        llm_response_data: JournalisticArticleResponse | None = None
        try {
            llm_response_data = generate_journalistic_article_llm(
                top_document_content,
                genai_model_instance,
                GENAI_JOURNALISTIC_ARTICLE_PROMPT # From src.prompts
            )
        } except Exception as e:
            log.error(f"Unexpected outer error during LLM call for TOP {top_chroma_id}: {e}", exc_info=True)
        finally:
            log.debug(f"LLM processing for TOP {top_chroma_id} concluded. Sleeping for {api_delay}s.")
            time.sleep(api_delay)

        if llm_response_data and llm_response_data.article_body:
            log.info(f"LLM generated structured article for TOP {top_chroma_id} (Title: {llm_response_data.article_title}).")

            # Generate a unique ID for the article itself
            article_uuid = str(uuid.uuid4())
            article_id_for_db = f"ART_{top_chroma_id}_{article_uuid[:8]}" # Example: ART_top123_abcdef12

            # Save the HTML file (optional, but current behavior)
            try {
                html_article_content = generate_html_article(
                    article_title=llm_response_data.article_title,
                    article_body=llm_response_data.article_body,
                    original_top_number=original_top_number_for_logging
                )

                sanitized_filename_base = sanitize_filename(llm_response_data.article_title if llm_response_data.article_title else original_top_number_for_logging)
                if not sanitized_filename_base:
                     sanitized_filename_base = top_chroma_id
                html_filename = f"ART_{sanitized_filename_base}.html"
                html_filepath = articles_dir / html_filename

                with open(html_filepath, "w", encoding="utf-8") as f:
                    f.write(html_article_content)
                log.info(f"Saved LLM-generated HTML article to: {html_filepath}")

            } except Exception as e:
                log.error(f"Error saving HTML article file for TOP {top_chroma_id}: {e}", exc_info=True)
                # Decide if this is critical enough to stop adding to DB or just log
                # For now, we'll still try to add to DB.

            # Add to the new articles ChromaDB collection
            try {
                success_db_add = db_loader.add_article_to_collection(
                    article_id=article_id_for_db,
                    original_top_id=top_chroma_id, # Link back to the original TOP
                    article_title=llm_response_data.article_title,
                    article_text=llm_response_data.article_body, # Store the full body
                    collection=articles_collection
                )
                if success_db_add:
                    log.info(f"Successfully added article {article_id_for_db} (from TOP {top_chroma_id}) to '{config.CHROMA_ARTICLES_COLLECTION_NAME}' collection.")
                    generated_count += 1
                else:
                    log.error(f"Failed to add article {article_id_for_db} (from TOP {top_chroma_id}) to ChromaDB collection.")
                    error_count +=1 # Count as an error if DB add fails

            } except Exception as e:
                log.error(f"Error adding article for TOP {top_chroma_id} to articles ChromaDB collection: {e}", exc_info=True)
                error_count += 1

            # The part that updated 'article_generated' in the original tops_collection is removed:
            # updated_metadata = {k: v for k, v in top_metadata.items() if k != 'html_content'}
            # updated_metadata['article_generated'] = True
            # tops_collection.update(ids=[top_chroma_id], metadatas=[updated_metadata])
            # log.info(f"Marked TOP {top_chroma_id} as article_generated=True in ChromaDB.") # This log is now obsolete

        else:
            log.warning(f"LLM failed to generate article for TOP {top_chroma_id} or returned empty. Skipping DB storage.")
            error_count += 1

    log.info(f"Article writing process finished. "
             f"Successfully generated and stored {generated_count} new articles in DB. "
             f"Skipped {skipped_due_to_existing_article} TOPs as articles already existed. "
             f"Encountered {error_count} errors/skipped TOPs during processing.")


if __name__ == "__main__":
    # Ensure GOOGLE_API_KEY is set in environment or config for direct execution
    log.info(f"Executing article_writer.py directly. Project root: {config.PROJECT_ROOT}")
    run_article_writing()
