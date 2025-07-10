# src/pipeline_steps/article_writer.py
import pathlib
import sys
import time
import json
import re
from google import genai
from pydantic import BaseModel
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
        load_api_call_delay,
        EXTRACTED_TEXTS_DIR_NAME # Import the new directory name
    )
    from src.prompts import GENAI_JOURNALISTIC_ARTICLE_PROMPT
except ImportError as e:
    print(f"CRITICAL: Error importing modules/config in article_writer.py: {e}. Check sys.path and config.py.", file=sys.stderr)
    raise # Re-raise to ensure failure is noted

# Initialize logger using the new constant (config must be loaded by this point)
log = config.get_logger(__name__, config.ARTICLE_WRITER_LOG_FILENAME)

# --- Pydantic Models for LLM Response ---
class SingleArticle(BaseModel):
    ueberschrift: str
    inhalt: str
    tags: List[str] = []

class LLMGeneratedArticles(BaseModel):
    artikel: List[SingleArticle]

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
    
    formatted_prompt = prompt_template.replace("{PROTOCOL_TEXT}", protocol_text)

    log.debug(f"Formatted prompt for LLM (first 200 chars of protocol text): {protocol_text[:200]}...")

    try:
        schema_dict = LLMGeneratedArticles.model_json_schema()
    except Exception as e_schema:
        log.error(f"Error generating JSON schema from Pydantic model: {e_schema}", exc_info=True)
        return None

    try:
        response = client.models.generate_content(
            model=f"models/{model_name}",
            contents=[formatted_prompt],
            config={
                "response_mime_type": "application/json",
                "response_schema": LLMGeneratedArticles,
            }
        )

        if not response.text:
            log.error("LLM response text is empty. Cannot parse JSON.")
            if response.prompt_feedback:
                log.error(f"Prompt feedback: {response.prompt_feedback}")
            return None

        log.debug(f"Raw LLM response text: {response.text}")
        llm_output = json.loads(response.text)
        validated_data = LLMGeneratedArticles(**llm_output)

        log.info(f"Successfully parsed and validated LLM response: Found {len(validated_data.artikel)} articles.")
        return validated_data.artikel
    
    except Exception as e:
        log.error(f"Unexpected error during LLM article generation: {e}", exc_info=True)
        return None

def generate_html_article(headline: str, content: str, tags: List[str], original_pdf_name: str) -> str:
    """
    Generates a simple HTML article from the LLM-generated headline, content, and tags.
    original_pdf_name is used for context/logging, not displayed directly in this basic HTML.
    """
    import html
    escaped_headline = html.escape(headline)
    escaped_content = html.escape(content)

    tags_html = ""
    if tags:
        escaped_tags = [html.escape(tag) for tag in tags]
        tags_html = f'<div class="tags"><strong>Tags:</strong> {", ".join(escaped_tags)}</div>'

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
        .tags {{ margin-top: 20px; font-size: 0.9em; color: #555; }}
        .tags strong {{ color: #333; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>{escaped_headline}</h1>
        <pre>{escaped_content}</pre>
        {tags_html}
        <!-- Metadaten könnten hier hinzugefügt werden, falls gewünscht, z.B. als Kommentar oder sichtbarer Text -->
        <!-- Source PDF: {html.escape(original_pdf_name)} -->
    </div>
</body>
</html>
"""
    return html_output

def run_article_writing(extracted_texts_dir_override: pathlib.Path | None = None):
    """
    Reads extracted text files from a directory, uses an LLM to generate journalistic articles for each,
    and saves these as HTML files.
    """
    log.info("Starting article writing process (LLM generation & saving HTML files)...")

    # Determine the directory to read extracted texts from
    input_texts_dir = extracted_texts_dir_override if extracted_texts_dir_override else config.PROJECT_ROOT / EXTRACTED_TEXTS_DIR_NAME

    if not input_texts_dir.is_dir():
        log.error(f"Extracted texts directory not found: {input_texts_dir}. Cannot proceed with article writing.")
        return

    # Read text files and populate a dictionary similar to the old extracted_texts
    extracted_texts_map = {}
    text_files = list(input_texts_dir.glob('*.txt'))

    if not text_files:
        log.info(f"No text files found in {input_texts_dir}. Skipping article generation.")
        return

    log.info(f"Found {len(text_files)} text files to process from {input_texts_dir}.")

    for text_filepath in text_files:
        try:
            with open(text_filepath, "r", encoding="utf-8") as f:
                content = f.read()
            # Store with original PDF filename convention (e.g., "document.pdf" from "document.txt")
            # This assumes that other parts of the system might still expect the .pdf extension in logs or metadata.
            # If only the stem is needed internally, this can be text_filepath.stem
            original_pdf_name = text_filepath.stem + ".pdf" # Or just text_filepath.stem if .pdf is not needed
            extracted_texts_map[original_pdf_name] = content
            log.debug(f"Successfully read text from '{text_filepath.name}'.")
        except IOError as e:
            log.error(f"Error reading text file {text_filepath.name}: {e}", exc_info=True)
            continue # Skip this file

    if not extracted_texts_map:
        log.info("No texts successfully read from files. Skipping article generation.")
        return

    # Initialize Google GenAI Client
    genai_client = None
    try:
        google_api_key = load_google_api_key()
        if not google_api_key:
            log.critical("Google API key not found in config.ini. LLM generation disabled.")
            return
        
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

    # Get a list of existing article filenames for checking
    existing_articles = [f.name for f in articles_dir.glob('*.html')]
    log.debug(f"Found existing articles: {existing_articles}")

    total_articles_generated_count = 0
    protocols_processed_count = 0
    error_count = 0

    for pdf_filename, protocol_full_text in extracted_texts_map.items(): # Use the new map
        # pdf_filename is like "document.pdf", text_file_stem is "document"
        text_file_stem = pathlib.Path(pdf_filename).stem
        log.info(f"Checking processing for text file stem: '{text_file_stem}' (derived from {pdf_filename})")

        # Check if articles for this text file already exist
        # An article filename is like "text_file_stem_some_headline.html"
        article_exists_for_stem = any(name.startswith(text_file_stem + "_") for name in existing_articles)

        if article_exists_for_stem:
            log.info(f"Articles for '{text_file_stem}' already exist. Skipping generation for this file.")
            # Optionally, count as skipped rather than error, or just log and continue
            continue # Skip to the next text file

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
            # Adjust sleep condition if necessary, e.g., if processing one by one and map size changes.
            # For now, using the size of the initially populated map.
            if len(extracted_texts_map) > 1 : # Check against the total number of files to process
                log.debug(f"LLM processing for '{pdf_filename}' concluded. Sleeping for {api_delay}s before next text file (if any).")
                time.sleep(api_delay)


        if articles_from_llm:
            log.info(f"LLM generated {len(articles_from_llm)} articles for '{pdf_filename}'.")
            protocols_processed_count +=1

            for article_index, article_data in enumerate(articles_from_llm):
                if article_data and article_data.inhalt and article_data.ueberschrift:
                    log.info(f"  Article {article_index+1}/{len(articles_from_llm)} from '{pdf_filename}': '{article_data.ueberschrift}'")

                    try:
                        html_article_content = generate_html_article(
                            headline=article_data.ueberschrift,
                            content=article_data.inhalt,
                            tags=article_data.tags, # Pass tags
                            original_pdf_name=pdf_filename # Pass PDF name for context
                        )

                        # Create a unique filename for each article
                        # Sanitize PDF name and headline for use in filename
                        sane_pdf_name = sanitize_filename(pathlib.Path(pdf_filename).stem)
                        sane_headline = sanitize_filename(article_data.ueberschrift)

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
                        log.error(f"  Error saving HTML article file for '{article_data.ueberschrift}' from '{pdf_filename}': {e}", exc_info=True)
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
    # This will now attempt to read from the default extracted_texts directory.
    # For direct execution, ensure that pdf_processor.py has been run first,
    # or manually place .txt files in the 'extracted_texts' directory.
    print(f"Attempting to run article_writer.py directly.")
    print(f"This script will look for .txt files in the '{EXTRACTED_TEXTS_DIR_NAME}' directory.")
    print(f"Make sure that directory exists and contains text files from PDF processing.")

    # Create a dummy extracted_texts directory and a file for testing if it doesn't exist
    dummy_test_dir = config.PROJECT_ROOT / EXTRACTED_TEXTS_DIR_NAME
    dummy_test_file = dummy_test_dir / "test_document.txt"

    if not dummy_test_dir.exists():
        dummy_test_dir.mkdir(parents=True, exist_ok=True)
        log.info(f"Created dummy directory for direct run: {dummy_test_dir}")

    if not list(dummy_test_dir.glob('*.txt')): # If no text files exist, create one for testing
        log.info(f"No .txt files found in {dummy_test_dir}. Creating a dummy file for testing.")
        try:
            with open(dummy_test_file, "w", encoding="utf-8") as f:
                f.write("This is a dummy text from a test document for article_writer.py direct execution.")
            log.info(f"Created dummy file: {dummy_test_file}")
            run_article_writing() # Run with the default directory
            # Clean up the dummy file after the test run
            # dummy_test_file.unlink() # Optional: remove dummy file
            # log.info(f"Removed dummy file: {dummy_test_file}")
        except Exception as e:
            log.error(f"Could not create or process dummy file for testing: {e}")
    else:
        log.info(f"Found existing .txt files in {dummy_test_dir}. Proceeding with those.")
        run_article_writing()

    print(f"Article writing process finished. Check the '{config.ARTICLES_DIR_NAME}' directory for output HTML files.")
