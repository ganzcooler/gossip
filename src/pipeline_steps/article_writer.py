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
        chroma_collection = db_loader.initialize_chroma_collection(
            db_path_name=config.CHROMA_DB_DIR_NAME,
            collection_name=config.CHROMA_COLLECTION_NAME,
            project_root=config.PROJECT_ROOT
        )
        log.info(f"ChromaDB collection '{config.CHROMA_COLLECTION_NAME}' initialized.")
    except Exception as e:
        log.critical(f"CRITICAL: Initialization error (ChromaDB): {e}", exc_info=True)
        return

    # Fetch relevant TOPs
    try:
        relevant_tops_results = chroma_collection.get(
            where={"is_relevant": True},
            include=['ids', 'metadatas', 'documents']
        )
        log.info(f"Retrieved {len(relevant_tops_results.get('ids', []))} relevant TOP entries.")
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

        if metadata.get('article_generated') is True:
            log.debug(f"TOP {chroma_id} (Original: {original_top_number}) already marked 'article_generated'. Skipping.")
            skipped_count += 1
            continue

        if not document_content:
            log.warning(f"TOP {chroma_id} (Original: {original_top_number}) has no document content. Skipping LLM generation.")
            error_count += 1 # Considered an error for this item
            continue

        log.info(f"Processing TOP {chroma_id} (Original: {original_top_number}) for LLM article generation.")

        llm_response_data: JournalisticArticleResponse | None = None
        try {
            llm_response_data = generate_journalistic_article_llm(
                document_content,
                genai_model_instance,
                GENAI_JOURNALISTIC_ARTICLE_PROMPT
            )
        } except Exception as e:
            log.error(f"Unexpected outer error during LLM call for TOP {chroma_id}: {e}", exc_info=True)
        finally:
            log.debug(f"LLM processing for TOP {chroma_id} concluded. Sleeping for {api_delay}s.")
            time.sleep(api_delay)

        if llm_response_data and llm_response_data.article_body: # Ensure body has content
            log.info(f"LLM generated structured article for TOP {chroma_id} (Title: {llm_response_data.article_title}). Proceeding to HTML conversion & saving.")
            try {
                html_article_content = generate_html_article(
                    article_title=llm_response_data.article_title,
                    article_body=llm_response_data.article_body,
                    original_top_number=original_top_number # For filename, not for rendering
                )

                sanitized_filename_base = sanitize_filename(llm_response_data.article_title if llm_response_data.article_title else original_top_number)
                if not sanitized_filename_base: # Fallback if title is empty or sanitization results in empty
                     sanitized_filename_base = chroma_id
                filename = f"ART_{sanitized_filename_base}.html" # Changed prefix to ART_
                filepath = articles_dir / filename

                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(html_article_content)
                log.info(f"Saved LLM-generated HTML article to: {filepath}")

                updated_metadata = {k: v for k, v in metadata.items() if k != 'html_content'}
                updated_metadata['article_generated'] = True

                chroma_collection.update(
                    ids=[chroma_id],
                    metadatas=[updated_metadata]
                )
                log.info(f"Marked TOP {chroma_id} as article_generated=True in ChromaDB.")
                generated_count += 1
            } except Exception as e:
                log.error(f"Error converting LLM article to HTML or saving for TOP {chroma_id}: {e}", exc_info=True)
                error_count += 1
        else:
            log.warning(f"LLM failed to generate article for TOP {chroma_id} or returned empty. Skipping HTML file.")
            error_count += 1 # LLM failure means an error for this item's processing

    log.info(f"Article writing process finished. Generated {generated_count} HTML files from LLM content. Skipped {skipped_count} (already processed). Encountered {error_count} errors/skipped TOPs.")

if __name__ == "__main__":
    # Ensure GOOGLE_API_KEY is set in environment or config for direct execution
    log.info(f"Executing article_writer.py directly. Project root: {config.PROJECT_ROOT}")
    run_article_writing()
