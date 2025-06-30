# src/pipeline_steps/image_generator.py
import logging
import pathlib
import sys
import time
import random # For mock image generation
import os # For path joining
import re # For parsing HTML

# Ensure src directory is in sys.path for config import
project_root_for_import = pathlib.Path(__file__).resolve().parent.parent.parent
if str(project_root_for_import) not in sys.path:
    sys.path.insert(0, str(project_root_for_import))

try:
    from src import config
    # from src.pipeline_steps import db_loader # Removed ChromaDB dependency
    # Assuming similar setup for Google API key if needed for actual image model
    from src.config import (
        # load_google_api_key, # Not strictly needed for placeholder
        GENAI_IMAGE_GENERATION_MODEL,
        load_api_call_delay
    )
    # from src.prompts import IMAGE_GENERATION_PROMPT # If we had a specific prompt template
except ImportError as e:
    temp_log_image_generator = logging.getLogger("image_generator_bootstrap_error")
    temp_log_image_generator.error(f"Error importing modules/config in image_generator.py: {e}")
    print(f"CRITICAL: Error importing modules/config in image_generator.py: {e}. Check sys.path and config.py.", file=sys.stderr)
    raise

log = config.get_logger(__name__, config.IMAGE_GENERATOR_LOG_FILENAME)

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


# --- Placeholder LLM Image Generation ---
def generate_featured_image_llm(article_text: str, article_title: str, model_name: str) -> bytes | None:
    """
    Placeholder function to simulate LLM-based image generation.
    In a real scenario, this would call an image generation API (e.g., Imagen, DALL-E).
    """
    log.info(f"Simulating LLM image generation for article: '{article_title}' using model '{model_name}'...")
    # prompt = f"Generate a compelling featured image for an article titled '{article_title}' with the following content: {article_text[:500]}..."
    # log.debug(f"Generated prompt for image LLM (first 100 chars): {prompt[:100]}")

    # Simulate API call
    time.sleep(random.uniform(1, 3)) # Simulate network latency and processing time

    # Simulate a successful image generation (e.g., a simple PNG)
    # This creates a tiny, valid, transparent PNG image as bytes
    # (Source: https://stackoverflow.com/a/3969448/14993403 - slightly modified)
    # In a real case, this would be the byte content from the API response.
    if random.random() > 0.1: # Simulate occasional failure
        log.info(f"Successfully simulated image generation for '{article_title}'.")
        # A minimal 1x1 transparent PNG.
        return b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\xfa\x0f\x00\x01\x05\x01\x02\xcf\x00\x01\x00\x00\x00\x00IEND\xaeB`\x82'
    else:
        log.error(f"Simulated LLM image generation failed for '{article_title}'.")
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

    image_model_name = config.GENAI_IMAGE_GENERATION_MODEL
    log.info(f"Using (simulated) image generation model: {image_model_name}")

    api_delay = load_api_call_delay()
    log.info(f"Using API call delay of {api_delay} seconds between (simulated) image generation calls.")

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

        target_image_filepath = get_image_filepath(html_filepath, images_output_dir)

        if target_image_filepath.exists():
            log.info(f"Image already exists for {html_filepath.name} at {target_image_filepath}. Skipping.")
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
                    article_text=prompt_text_snippet, # Pass snippet of body
                    article_title=prompt_title,    # Pass parsed or default title
                    model_name=image_model_name
                )
            except Exception as e_gen:
                log.error(f"Unexpected error during (simulated) image generation for {html_filepath.name}: {e_gen}", exc_info=True)
                error_count += 1
                continue # Skip this article if generation itself had an issue
            finally:
                if len(html_files) > 1 and (generated_count + skipped_count + error_count) < len(html_files) -1 : # Avoid sleep after last item
                     log.debug(f"Simulated API call delay of {api_delay}s...")
                     time.sleep(api_delay)


            if image_bytes:
                try:
                    with open(target_image_filepath, "wb") as f:
                        f.write(image_bytes)
                    log.info(f"Saved (simulated) generated image to: {target_image_filepath}")
                    generated_count += 1
                except Exception as e_save:
                    log.error(f"Error saving image for {html_filepath.name} to {target_image_filepath}: {e_save}", exc_info=True)
                    error_count += 1
            else:
                log.warning(f"(Simulated) LLM failed to generate image for {html_filepath.name}. No image saved.")
                # This might not be an "error" if the LLM can legitimately return no image.
                # For placeholder, we count it as a non-generation.

        except Exception as e_read_parse:
            log.error(f"Error reading or parsing HTML file {html_filepath.name}: {e_read_parse}", exc_info=True)
            error_count += 1
            continue


    log.info(f"Image generation process finished. "
             f"Generated: {generated_count}, Skipped (already exist): {skipped_count}, Errors: {error_count}.")

if __name__ == "__main__":
    log.info(f"Executing image_generator.py directly. Project root: {config.PROJECT_ROOT}")
    run_image_generation()
