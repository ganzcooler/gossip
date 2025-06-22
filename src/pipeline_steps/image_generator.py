# src/pipeline_steps/image_generator.py
import logging
import pathlib
import sys
import time
import random # For mock image generation
import os # For path joining

# Ensure src directory is in sys.path for config import
project_root_for_import = pathlib.Path(__file__).resolve().parent.parent.parent
if str(project_root_for_import) not in sys.path:
    sys.path.insert(0, str(project_root_for_import))

try:
    from src import config
    from src.pipeline_steps import db_loader
    # Assuming similar setup for Google API key if needed for actual image model
    from src.config import (
        load_google_api_key,
        GENAI_IMAGE_GENERATION_MODEL, # Will be used if we had a real model
        load_api_call_delay
    )
    # from src.prompts import IMAGE_GENERATION_PROMPT # If we had a specific prompt template
except ImportError as e:
    temp_log_image_generator = logging.getLogger("image_generator_bootstrap_error")
    temp_log_image_generator.error(f"Error importing modules/config in image_generator.py: {e}")
    print(f"CRITICAL: Error importing modules/config in image_generator.py: {e}. Check sys.path and config.py.", file=sys.stderr)
    raise

log = config.get_logger(__name__, config.IMAGE_GENERATOR_LOG_FILENAME)

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

def sanitize_filename_for_image(name: str, top_id: str) -> str:
    """Sanitizes a string to be a valid filename for an image, incorporating TOP ID."""
    name = str(name) # Ensure name is a string
    sanitized_title = "".join(c if c.isalnum() or c in (' ', '-') else '_' for c in name).strip()
    sanitized_title = "_".join(sanitized_title.split()) # Replace spaces with underscores
    if not sanitized_title: # Handle empty or fully sanitized titles
        sanitized_title = "untitled"

    # Truncate title part if too long to keep filenames manageable
    max_title_len = 50
    return f"IMG_{top_id}_{sanitized_title[:max_title_len]}.png"


def run_image_generation():
    """
    Fetches articles from the 'generated_articles' collection,
    generates a featured image for each using a (simulated) LLM,
    saves the image, and updates the article's metadata in ChromaDB.
    """
    log.info("Starting image generation process...")

    # Initialize Google API (if a real Google model were used for images)
    # try:
    #     google_api_key = load_google_api_key()
    #     if not google_api_key:
    #         log.critical("Google API key not found. Image generation (if using Google model) disabled.")
    #         # Depending on whether the placeholder always runs, this might not be a fatal error
    #     # genai.configure(api_key=google_api_key) # If using genai for images
    #     log.info("Google API key loaded (relevant if using a Google image model).")
    # except Exception as e:
    #     log.warning(f"Could not load Google API key: {e}. This might affect real image generation.")

    # Placeholder for image model name from config
    image_model_name = config.GENAI_IMAGE_GENERATION_MODEL
    log.info(f"Using (simulated) image generation model: {image_model_name}")

    api_delay = load_api_call_delay()
    log.info(f"Using API call delay of {api_delay} seconds between (simulated) image generation calls.")

    # Create generated_images directory
    images_output_dir = config.PROJECT_ROOT / config.IMAGES_DIR_NAME
    try:
        images_output_dir.mkdir(parents=True, exist_ok=True)
        log.info(f"Ensured '{config.IMAGES_DIR_NAME}' directory exists at: {images_output_dir}")
    except OSError as e:
        log.error(f"Error creating directory {images_output_dir}: {e}", exc_info=True)
        return # Cannot proceed if images can't be saved

    # Initialize ChromaDB
    try:
        articles_collection = db_loader.initialize_chroma_collection(
            db_path_name=config.CHROMA_DB_DIR_NAME,
            collection_name=config.CHROMA_ARTICLES_COLLECTION_NAME,
            project_root=config.PROJECT_ROOT
        )
        log.info(f"ChromaDB Articles collection '{config.CHROMA_ARTICLES_COLLECTION_NAME}' initialized.")
    except Exception as e:
        log.critical(f"CRITICAL: Initialization error (ChromaDB articles collection): {e}", exc_info=True)
        return

    # Fetch all articles that don't have an image filename yet
    try:
        # Query for articles where 'image_filename' metadata does NOT exist or is null.
        # ChromaDB's filtering for non-existence of a key can be tricky.
        # A common way is to fetch all and filter in Python, or use a specific value like "NOT_SET".
        # For simplicity, we'll fetch articles and check metadata.
        # A more optimized query would be `where={"image_filename": {"$exists": False}}` if supported
        # or query for a placeholder value you ensure is not set otherwise.
        # As a workaround, one might need to fetch all and filter, or ensure `image_filename` is always present, possibly as `None`.

        articles_results = articles_collection.get(include=['ids', 'metadatas', 'documents'])

        articles_to_process = []
        if articles_results and articles_results['ids']:
            for i in range(len(articles_results['ids'])):
                meta = articles_results['metadatas'][i]
                if meta is None or 'image_filename' not in meta or meta['image_filename'] is None:
                    articles_to_process.append({
                        "id": articles_results['ids'][i],
                        "metadata": meta if meta is not None else {}, # Ensure metadata is a dict
                        "document": articles_results['documents'][i]
                    })
            log.info(f"Retrieved {len(articles_results.get('ids', []))} total articles. "
                       f"Found {len(articles_to_process)} articles needing image generation.")
        else:
            log.info("No articles found in the collection.")
            return

    except Exception as e:
        log.error(f"Error querying ChromaDB for articles: {e}", exc_info=True)
        return

    if not articles_to_process:
        log.info("No articles found that require image generation.")
        return

    generated_count = 0
    error_count = 0

    for article_data in articles_to_process:
        article_id = article_data['id']
        article_metadata = article_data['metadata']
        article_text = article_data['document']

        # Fallback for title if not present in metadata for some reason
        article_title = article_metadata.get('article_title', 'Untitled Article')
        original_top_id = article_metadata.get('original_top_id', 'UNKNOWN_TOP_ID')

        log.info(f"Processing article ID {article_id} (Title: '{article_title}') for image generation.")

        image_bytes: bytes | None = None
        try {
            image_bytes = generate_featured_image_llm(
                article_text=article_text,
                article_title=article_title,
                model_name=image_model_name
            )
        } except Exception as e:
            log.error(f"Unexpected error during (simulated) image generation for article {article_id}: {e}", exc_info=True)
        finally:
            log.debug(f"Image generation attempt for article {article_id} concluded. Sleeping for {api_delay}s.")
            time.sleep(api_delay)

        if image_bytes:
            try:
                image_filename = sanitize_filename_for_image(article_title, original_top_id)
                image_filepath = images_output_dir / image_filename

                with open(image_filepath, "wb") as f:
                    f.write(image_bytes)
                log.info(f"Saved (simulated) generated image to: {image_filepath}")

                # Update metadata in ChromaDB for this article
                update_success = db_loader.update_article_metadata_field(
                    article_id=article_id,
                    field_name="image_filename",
                    field_value=image_filename,
                    collection=articles_collection
                )
                if update_success:
                    log.info(f"Successfully updated article {article_id} with image_filename: {image_filename}")
                    generated_count += 1
                else:
                    log.error(f"Failed to update article {article_id} metadata with image_filename.")
                    error_count += 1 # Count as error if DB update fails
            except Exception as e:
                log.error(f"Error saving image or updating DB for article {article_id}: {e}", exc_info=True)
                error_count += 1
        else:
            log.warning(f"(Simulated) LLM failed to generate image for article {article_id}. Skipping file save and DB update.")
            # Not necessarily an error_count increment here unless we expect 100% success
            # For now, let's count it as a miss but not a processing error.

    log.info(f"Image generation process finished. "
             f"Successfully generated and saved {generated_count} images. "
             f"Encountered {error_count} errors during saving or DB update.")

if __name__ == "__main__":
    log.info(f"Executing image_generator.py directly. Project root: {config.PROJECT_ROOT}")
    run_image_generation()
