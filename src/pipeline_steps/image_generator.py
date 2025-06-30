# src/pipeline_steps/image_generator.py
import logging
import pathlib
import sys
import time
# import random # No longer needed for mock generation
import os # For path joining
import re # For parsing HTML
import google.generativeai as genai
from google.generativeai import types
from google.api_core import exceptions as google_exceptions
from PIL import Image # For image processing, though not strictly needed if just saving bytes
from io import BytesIO

# Ensure src directory is in sys.path for config import
project_root_for_import = pathlib.Path(__file__).resolve().parent.parent.parent
if str(project_root_for_import) not in sys.path:
    sys.path.insert(0, str(project_root_for_import))

try:
    from src import config
    from src.config import (
        load_google_api_key, # Now needed for actual API call
        GENAI_IMAGE_GENERATION_MODEL,
        load_api_call_delay
    )
except ImportError as e:
    temp_log_image_generator = logging.getLogger("image_generator_bootstrap_error")
    temp_log_image_generator.error(f"Error importing modules/config in image_generator.py: {e}")
    print(f"CRITICAL: Error importing modules/config in image_generator.py: {e}. Check sys.path and config.py.", file=sys.stderr)
    raise

log = config.get_logger(__name__, config.IMAGE_GENERATOR_LOG_FILENAME)

# Global GenAI model instance for image generation
# Initialize it once if possible, or ensure API key is configured before first call.
# For simplicity here, we'll initialize it in the run_image_generation or ensure it's configured.
genai_image_model_instance = None


def _initialize_genai_for_image_generation():
    """Initializes the GenAI client and model for image generation if not already done."""
    global genai_image_model_instance
    if genai_image_model_instance is None:
        try:
            api_key = load_google_api_key()
            genai.configure(api_key=api_key)
            model_name = config.GENAI_IMAGE_GENERATION_MODEL
            if not model_name:
                log.critical("GENAI_IMAGE_GENERATION_MODEL not set in config. Cannot generate images.")
                raise ValueError("Image generation model name not configured.")
            # For some specific tasks or models, you might use client.get_model or similar
            # but for generate_content, a GenerativeModel instance is typical.
            genai_image_model_instance = genai.GenerativeModel(model_name)
            log.info(f"Google GenAI model '{model_name}' initialized for image generation.")
        except Exception as e:
            log.critical(f"Failed to initialize Google GenAI for image generation: {e}", exc_info=True)
            # genai_image_model_instance remains None, subsequent calls will fail or be skipped.
            raise # Re-raise to halt if initialization is critical at call time


def parse_html_article(html_content: str) -> tuple[str | None, str | None]:
    """
    Parses HTML content to extract title (from <h1>) and body (from <pre>).
    This is a very basic parser assuming the specific HTML structure used.
    Returns (title, body)
    """
    title = None
    body = None

    # Extract title from <h1>
    title_match = re.search(r"<h1[^>]*>(.*?)</h1>", html_content, re.IGNORECASE | re.DOTALL)
    if title_match:
        title = title_match.group(1).strip()

    # Extract body from <pre>
    # Assuming the first <pre> tag encountered contains the main article body
    body_match = re.search(r"<pre[^>]*>(.*?)</pre>", html_content, re.IGNORECASE | re.DOTALL)
    if body_match:
        body = body_match.group(1).strip()

    if not title:
        log.warning("Could not parse title from HTML.")
    if not body:
        log.warning("Could not parse body from HTML.")

    return title, body


# --- Actual LLM Image Generation ---
def generate_featured_image_llm(article_title: str, article_text_snippet: str) -> bytes | None:
    """
    Generates a featured image using the Gemini API based on article title and text snippet.
    Uses the globally initialized genai_image_model_instance.
    """
    global genai_image_model_instance # Original code below
    if genai_image_model_instance is None:
        log.error("GenAI image model not initialized. Cannot generate image.")
        return None

    prompt = f"Generate a compelling and relevant featured image for a news article titled '{article_title}'. The article is about: {article_text_snippet}"
    log.info(f"Generating image with prompt (first 150 chars): {prompt[:150]}...")

    try:
        response = genai_image_model_instance.generate_content(
            contents=[prompt],
            generation_config=types.GenerationConfig()
        )

        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if part.inline_data and part.inline_data.data:
                    log.info(f"Successfully generated image for article: '{article_title}'.")
                    return part.inline_data.data

        log.warning(f"No image data found in response for article: '{article_title}'. Response: {response}")
        return None

    except google_exceptions.GoogleAPIError as e:
        log.error(f"Google API Error during image generation for '{article_title}': {e}", exc_info=True)
        return None
    except Exception as e:
        log.error(f"Unexpected error during image generation for '{article_title}': {e}", exc_info=True)
        return None

def get_image_filepath(html_filepath: pathlib.Path, images_output_dir: pathlib.Path) -> pathlib.Path:
    """Determines the corresponding image filepath based on the HTML article filepath."""
    image_filename_stem = html_filepath.stem # e.g., "my-article" from "my-article.html"
    image_filename = f"{image_filename_stem}.png" # Assuming PNG, can be configurable
    return images_output_dir / image_filename

def run_image_generation():
    """
    Scans the articles directory for HTML files, generates a featured image for each
    (if one doesn't already exist), and saves it to the images directory.
    """
    log.info("Starting image generation process...")
    try:
        # Initialize the GenAI model for image generation (loads API key)
        _initialize_genai_for_image_generation()
    except Exception:
        # Error already logged by _initialize_genai_for_image_generation
        log.error("Halting image generation due to initialization failure.")
        return

    if genai_image_model_instance is None:
        log.error("Image generation model could not be initialized. Skipping image generation.")
        return

    api_delay = load_api_call_delay()
    log.info(f"Using API call delay of {api_delay} seconds between image generation calls.")

    articles_input_dir = config.PROJECT_ROOT / config.ARTICLES_DIR_NAME
    images_output_dir = config.PROJECT_ROOT / config.IMAGES_DIR_NAME

    # Ensure directories exist
    try:
        articles_input_dir.mkdir(parents=True, exist_ok=True)
        images_output_dir.mkdir(parents=True, exist_ok=True)
        log.info(f"Article input directory: {articles_input_dir}")
        log.info(f"Image output directory: {images_output_dir}")
    except OSError as e:
        log.error(f"Error creating directories: {e}", exc_info=True)
        return

    html_files = list(articles_input_dir.glob('*.html'))
    if not html_files:
        log.info(f"No HTML articles found in {articles_input_dir}. Nothing to process.")
        return

    log.info(f"Found {len(html_files)} HTML articles to check for image generation.")

    generated_count = 0
    skipped_count = 0
    error_count = 0

    for html_filepath in html_files:
        log.info(f"Processing article: {html_filepath.name}")

        # Determine the target image filepath; re-create Path object for a fresh check
        image_filename_stem = html_filepath.stem
        image_filename = f"{image_filename_stem}.png"
        target_image_filepath = images_output_dir / image_filename

        # Explicitly create a new Path object for the existence check
        check_image_path = pathlib.Path(target_image_filepath)

        if check_image_path.exists():
            log.info(f"Image already exists for {html_filepath.name} at {check_image_path}. Skipping.")
            skipped_count += 1
            continue

        try:
            html_content = html_filepath.read_text(encoding="utf-8")
            article_title, article_body = parse_html_article(html_content)

            if not article_title and not article_body:
                log.warning(f"Could not parse title or body from {html_filepath.name}. Skipping image generation.")
                error_count +=1
                continue

            # Use title for image gen, fallback to a snippet of body if title is missing
            prompt_title = article_title if article_title else "Untitled Article"
            prompt_text_snippet = (article_body if article_body else "")[:500] # Use a snippet of body for context

            log.info(f"Attempting to generate image for '{prompt_title}' (from {html_filepath.name})")

            image_bytes: bytes | None = None
            try:
                image_bytes = generate_featured_image_llm(
                    article_title=prompt_title,
                    article_text_snippet=prompt_text_snippet
                )
            except Exception as e_gen:
                log.error(f"Unexpected error during image generation call for {html_filepath.name}: {e_gen}", exc_info=True)
                error_count += 1
                continue # Skip this article if generation itself had an issue
            finally:
                # Apply delay only if there are more files to process potentially
                is_last_file_to_attempt = (html_files.index(html_filepath) == len(html_files) - 1)
                if not is_last_file_to_attempt:
                     log.debug(f"API call delay of {api_delay}s...")
                     time.sleep(api_delay)

            if image_bytes:
                try:
                    with open(target_image_filepath, "wb") as f:
                        f.write(image_bytes)
                    log.info(f"Saved generated image to: {target_image_filepath}")
                    if target_image_filepath.exists():
                        log.info(f"Verified: Image file now exists at {target_image_filepath}")
                        generated_count += 1
                    else:
                        log.error(f"File write seemed to succeed but image file NOT FOUND at {target_image_filepath} after write attempt.")
                        error_count += 1 # Count as error if file not found after write
                except Exception as e_save:
                    log.error(f"Error saving image for {html_filepath.name} to {target_image_filepath}: {e_save}", exc_info=True)
                    error_count += 1
            else:
                log.warning(f"LLM did not return image data for {html_filepath.name}. No image saved.")
                # This could be due to API error, safety settings, or no image part in response.

        except Exception as e_read_parse:
            log.error(f"Error reading or parsing HTML file {html_filepath.name}: {e_read_parse}", exc_info=True)
            error_count += 1
            continue


    log.info(f"Image generation process finished. "
             f"Generated: {generated_count}, Skipped (already exist): {skipped_count}, Errors: {error_count}.")

if __name__ == "__main__":
    log.info(f"Executing image_generator.py directly. Project root: {config.PROJECT_ROOT}")
    run_image_generation()
