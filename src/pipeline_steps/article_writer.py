# src/pipeline_steps/article_writer.py
import logging # Keep for potential direct use
import pathlib
import sys
import time
import json
from google import genai # Changed import for google-genai
from google.genai import types as genai_types # For GenerationConfig and schema types
from google.api_core import exceptions as google_exceptions
from pydantic import BaseModel, ValidationError, TypeAdapter
from typing import List

# Ensure src directory is in sys.path for config import
project_root_for_import = pathlib.Path(__file__).resolve().parent.parent.parent
if str(project_root_for_import) not in sys.path:
    sys.path.insert(0, str(project_root_for_import))

try:
    from src import config
    from src.config import (
        load_google_api_key,
        GENAI_ARTICLE_GENERATION_MODEL,
        load_api_call_delay
    )
    from src.prompts import GENAI_JOURNALISTIC_ARTICLE_PROMPT
except ImportError as e:
    temp_log_article_writer = logging.getLogger("article_writer_bootstrap_error")
    temp_log_article_writer.error(f"Error importing modules/config in article_writer.py: {e}")
    print(f"CRITICAL: Error importing modules/config in article_writer.py: {e}. Check sys.path and config.py.", file=sys.stderr)
    raise # Re-raise to ensure failure is noted

import os # Already present
import re # Already present
import uuid # For generating unique article IDs

# Initialize logger using the new constant (config must be loaded by this point)
log = config.get_logger(__name__, config.ARTICLE_WRITER_LOG_FILENAME)


# --- Pydantic Models for LLM Response ---
class SingleArticle(BaseModel):
    headline: str
    content: str

class LLMGeneratedArticles(BaseModel):
    articles: List[SingleArticle]


# Local prompt template removed, will be imported from config.

def sanitize_filename(name: str) -> str:
    """Sanitizes a string to be a valid filename."""
    name = re.sub(r'[^\w\s-]', '', name) # Remove non-alphanumeric, non-space, non-hyphen
    name = re.sub(r'[-\s]+', '-', name).strip('-_') # Replace spaces/hyphens with single hyphen
    return name if name else "untitled_article" # Ensure not empty

def generate_articles_from_text_llm(
    protocol_text: str,
    client: genai.client.Client,
    model_name: str,
    prompt_template: str
) -> List[SingleArticle] | None:
    """
    Generates multiple journalistic articles from protocol text using the Gemini API via genai.Client.
    Expects a JSON response containing a list of articles.
    """
    if not protocol_text: # Real logic below
        log.warning("LLM generation skipped: Protocol text is empty.")
        return None

    formatted_prompt = prompt_template.format(PROTOCOL_TEXT=protocol_text)
    log.debug(f"Formatted prompt for LLM (first 200 chars of protocol text): {protocol_text[:200]}...")

    try:
        schema_dict = LLMGeneratedArticles.model_json_schema()
    except Exception as e_schema:
        log.error(f"Error generating JSON schema from Pydantic model: {e_schema}", exc_info=True)
        return None

    generation_config = genai_types.GenerationConfig(
        response_mime_type="application/json",
        response_schema=schema_dict
    )

    request_options = {"timeout": 300}

    try:
        response = client.generate_content(
            model=f"models/{model_name}",
            contents=[formatted_prompt],
            generation_config=generation_config,
            request_options=request_options
        )

        if not response.text:
            log.error("LLM response text is empty. Cannot parse JSON.")
            if response.prompt_feedback:
                log.error(f"Prompt feedback: {response.prompt_feedback}")
            return None

        log.debug(f"Raw LLM response text: {response.text}")
        llm_output = json.loads(response.text)
        validated_data = LLMGeneratedArticles(**llm_output)

        log.info(f"Successfully parsed and validated LLM response: Found {len(validated_data.articles)} articles.")
        return validated_data.articles

    except json.JSONDecodeError as e:
        log.error(f"JSONDecodeError parsing LLM response: {e}. Response text: '{response.text if hasattr(response, 'text') else 'Response text not available'}'", exc_info=True)
        return None
    except ValidationError as e:
        log.error(f"Pydantic ValidationError for LLM response: {e}. LLM output: '{llm_output if 'llm_output' in locals() else 'LLM output not available'}'", exc_info=True)
        return None
    except google_exceptions.GoogleAPIError as e:
        log.error(f"Google API Error during LLM article generation: {e}", exc_info=True)
        return None
    except Exception as e:
        log.error(f"Unexpected error during LLM article generation: {e}", exc_info=True)
        return None

def generate_html_article(headline: str, content: str, original_pdf_name: str) -> str:
    """
    Generates a simple HTML article from the LLM-generated headline and content.
    original_pdf_name is used for context/logging, not displayed directly in this basic HTML.
    """
    # Basic HTML escaping for content to be safe in <pre> or body
    import html
    escaped_headline = html.escape(headline)
    escaped_content = html.escape(content)

    html_output = f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{escaped_headline}</title>
    <style>
        body {{ font-family: sans-serif; margin: 20px; line-height: 1.6; color: #333; background-color: #fdfdfd; }}
        .container {{ max-width: 800px; margin: 0 auto; background-color: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 0 10px rgba(0,0,0,0.1); }}
        h1 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
        p {{ text-align: justify; }}
        /* Using <pre> for content to preserve line breaks from LLM, but with word wrap */
        pre {{ white-space: pre-wrap; word-wrap: break-word; background-color: #f9f9f9; border: 1px solid #eee; padding: 15px; border-radius: 4px; font-family: inherit; font-size: inherit;}}
    </style>
</head>
<body>
    <div class="container">
        <h1>{escaped_headline}</h1>
        <pre>{escaped_content}</pre>
        <!-- Metadaten könnten hier hinzugefügt werden, falls gewünscht, z.B. als Kommentar oder sichtbarer Text -->
        <!-- Source PDF: {html.escape(original_pdf_name)} -->
    </div>
</body>
</html>
"""
    return html_output

def run_article_writing(extracted_texts: dict[str, str]): # Takes dict of pdf_filename: text_content
    """
    Takes extracted texts from PDFs, uses an LLM to generate journalistic articles for each,
    and saves these as HTML files.
    """
    log.info("Starting article writing process (LLM generation & saving HTML files)...")

    if not extracted_texts:
        log.info("No extracted texts provided. Skipping article generation.")
        return

    # Initialize Google GenAI Client
    genai_client = None
    try:
        google_api_key = load_google_api_key()
        if not google_api_key:
            log.critical("Google API key not found in config.ini. LLM generation disabled.")
            return
        # For google-genai, client is initialized with the key.
        # Global configuration via genai.configure() might still work or be relevant for other genai functions,
        # but client object will use the key passed to its constructor if any.
        # Based on research, genai.Client(api_key=...) is the way.
        genai_client = genai.Client(api_key=google_api_key)
        log.info(f"Google GenAI client initialized successfully.")
    except Exception as e:
        log.critical(f"Failed to initialize Google GenAI client: {e}. LLM generation will be skipped.", exc_info=True)
        return

    llm_model_name = GENAI_ARTICLE_GENERATION_MODEL
    if not llm_model_name:
        log.critical("GENAI_ARTICLE_GENERATION_MODEL not set in config. LLM generation disabled.")
        return
    log.info(f"Using LLM model for article generation: {llm_model_name}")

    api_delay = load_api_call_delay()
    log.info(f"Using API call delay of {api_delay} seconds between LLM calls for different PDFs.")

    # Create generated_articles directory (using config.ARTICLES_DIR_NAME)
    articles_dir = config.PROJECT_ROOT / config.ARTICLES_DIR_NAME
    try:
        articles_dir.mkdir(parents=True, exist_ok=True)
        log.info(f"Ensured '{config.ARTICLES_DIR_NAME}' directory exists at: {articles_dir}")
    except OSError as e:
        log.error(f"Error creating directory {articles_dir}: {e}", exc_info=True)
        return

    # Removed ChromaDB initialization and fetching logic

    total_articles_generated_count = 0
    protocols_processed_count = 0
    error_count = 0

    for pdf_filename, protocol_full_text in extracted_texts.items():
        log.info(f"Processing extracted text from '{pdf_filename}' for LLM article generation.")

        if not protocol_full_text.strip():
            log.warning(f"Protocol text for '{pdf_filename}' is empty or whitespace. Skipping LLM generation.")
            error_count += 1
            continue

        articles_from_llm: List[SingleArticle] | None = None
        try:
            articles_from_llm = generate_articles_from_text_llm(
                protocol_text=protocol_full_text,
                client=genai_client,
                model_name=llm_model_name,
                prompt_template=GENAI_JOURNALISTIC_ARTICLE_PROMPT
            )
        except Exception as e: # Catch any unexpected error from the generation function itself
            log.error(f"Unexpected outer error during LLM call for '{pdf_filename}': {e}", exc_info=True)
            error_count += 1 # Count this as an error for the protocol
        finally:
            if len(extracted_texts) > 1 : # Only sleep if there are more PDFs to process
                log.debug(f"LLM processing for '{pdf_filename}' concluded. Sleeping for {api_delay}s before next PDF (if any).")
                time.sleep(api_delay)


        if articles_from_llm:
            log.info(f"LLM generated {len(articles_from_llm)} articles for '{pdf_filename}'.")
            protocols_processed_count +=1

            for article_index, article_data in enumerate(articles_from_llm):
                if article_data and article_data.content and article_data.headline:
                    log.info(f"  Article {article_index+1}/{len(articles_from_llm)} from '{pdf_filename}': '{article_data.headline}'")

                    try:
                        html_article_content = generate_html_article(
                            headline=article_data.headline,
                            content=article_data.content,
                            original_pdf_name=pdf_filename # Pass PDF name for context
                        )

                        # Create a unique filename for each article
                        # Sanitize PDF name and headline for use in filename
                        sane_pdf_name = sanitize_filename(pathlib.Path(pdf_filename).stem)
                        sane_headline = sanitize_filename(article_data.headline)

                        # Ensure filename is not too long and is unique enough
                        # Using first few words of headline and index
                        short_headline = "_".join(sane_headline.split('-')[:5])
                        if not short_headline: short_headline = f"article_{article_index+1}"

                        html_filename = f"{sane_pdf_name}_{short_headline}.html"
                        html_filepath = articles_dir / html_filename

                        # Ensure unique filenames if many articles have similar headlines
                        counter = 1
                        temp_filepath = html_filepath
                        while temp_filepath.exists():
                            html_filename = f"{sane_pdf_name}_{short_headline}_{counter}.html"
                            temp_filepath = articles_dir / html_filename
                            counter += 1
                        html_filepath = temp_filepath


                        with open(html_filepath, "w", encoding="utf-8") as f:
                            f.write(html_article_content)
                        log.info(f"  Saved HTML article to: {html_filepath}")
                        total_articles_generated_count += 1

                    except Exception as e:
                        log.error(f"  Error saving HTML article file for '{article_data.headline}' from '{pdf_filename}': {e}", exc_info=True)
                        error_count += 1 # Count error for this specific article saving
                else:
                    log.warning(f"  LLM returned an incomplete article item (missing headline or content) for '{pdf_filename}'. Skipping this item.")
                    error_count += 1
        else:
            log.warning(f"LLM failed to generate any articles for '{pdf_filename}' or returned empty/invalid structure.")
            # If generate_articles_from_text_llm returns None, it means an error occurred during the LLM call or parsing
            # So, this protocol counts towards errors if no articles are produced.
            # If it returns an empty list, it means the LLM chose not to make any articles, which is not an error per se.
            if articles_from_llm is None: # Explicitly None means error in LLM call/parsing
                 error_count += 1


    log.info(f"Article writing process finished. "
             f"Processed {protocols_processed_count} protocols. "
             f"Successfully generated and saved {total_articles_generated_count} HTML articles. "
             f"Encountered {error_count} errors/skipped items during processing.")


if __name__ == "__main__":
    log.info(f"Executing article_writer.py directly. Project root: {config.PROJECT_ROOT}")
    # This direct execution part needs to be updated to simulate input
    # For example, create a dummy extracted_texts dictionary
    dummy_texts = {
        "protocol1.pdf": "This is the full text of protocol one. It contains discussion on Topic A and a decision on Topic B.",
        "protocol2.pdf": "Protocol two details the new budget allocations and a lengthy debate on future projects."
    }
    # To run this standalone, you'd need to ensure pdf_processor.py has run or provide sample text.
    # For now, this part is more for illustration.
    # run_article_writing(dummy_texts)
    print("To run article_writer.py directly, provide a dictionary of extracted texts.")
    print("Example: run_article_writing({'my_doc.pdf': 'Text of the document...'})")
