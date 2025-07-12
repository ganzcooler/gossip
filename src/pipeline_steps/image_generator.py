# src/pipeline_steps/image_generator.py
import logging
import pathlib
import sys
import time
import google.generativeai as genai
from google.generativeai import types

# Ensure src directory is in sys.path for config import
project_root_for_import = pathlib.Path(__file__).resolve().parent.parent.parent
if str(project_root_for_import) not in sys.path:
    sys.path.insert(0, str(project_root_for_import))

try:
    from src import config
    from src.config import (
        load_google_api_key,
        GENAI_IMAGE_GENERATION_MODEL,
        load_api_call_delay
    )
except ImportError as e:
    temp_log_image_generator = logging.getLogger("image_generator_bootstrap_error")
    temp_log_image_generator.error(f"Error importing modules/config in image_generator.py: {e}")
    print(f"CRITICAL: Error importing modules/config in image_generator.py: {e}. Check sys.path and config.py.", file=sys.stderr)
    raise

log = config.get_logger(__name__, config.IMAGE_GENERATOR_LOG_FILENAME)

genai_client_instance = None

def _initialize_genai_client() -> genai.GenerativeModel | None:
    """Initializes and returns a GenAI client using the API key from config."""
    global genai_client_instance
    if genai_client_instance is None:
        try:
            api_key = load_google_api_key()
            if not api_key:
                log.critical("API key not found in config. Cannot initialize GenAI client.")
                return None
            genai.configure(api_key=api_key)
            genai_client_instance = genai.GenerativeModel(config.GENAI_IMAGE_GENERATION_MODEL)
            log.info("Google GenAI Client initialized successfully for image generation.")
        except Exception as e:
            log.critical(f"Failed to initialize Google GenAI Client: {e}", exc_info=True)
            return None
    return genai_client_instance

def generate_featured_image_llm(
    client: genai.GenerativeModel,
    model_name: str,
    prompt: str,
    prompt_filename: str,
) -> bytes | None:
    """
    Generates a featured image using the Gemini API (via genai.Client)
    based on the given prompt.
    """
    if client is None:
        log.error("GenAI client not initialized. Cannot generate image.")
        return None

    log.info(f"Generating image with prompt from '{prompt_filename}' (first 150 chars): {prompt[:150]}...")

    try:
        response = client.generate_content(
            contents=[prompt],
            generation_config=types.GenerationConfig(
                response_modalities=['TEXT', 'IMAGE']
            )
        )

        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if part.inline_data and part.inline_data.data:
                    log.info(f"Successfully generated image for prompt: '{prompt_filename}'.")
                    return part.inline_data.data

        log.warning(f"No image data found in response for prompt: '{prompt_filename}'. Response: {response}")
        return None

    except Exception as e:
        log.error(f"Unexpected error during image generation for '{prompt_filename}': {e}", exc_info=True)
        return None

def get_image_filepath(prompt_filepath: pathlib.Path, images_output_dir: pathlib.Path) -> pathlib.Path:
    """Determines the corresponding image filepath based on the prompt filepath."""
    image_filename_stem = prompt_filepath.stem
    image_filename = f"{image_filename_stem}.png"
    return images_output_dir / image_filename

def run_image_generation():
    """
    Scans the prompts directory for text files, generates a featured image for each
    (if one doesn't already exist), and saves it to the images directory.
    """
    log.info("Starting image generation process...")

    client = _initialize_genai_client()
    if not client:
        log.error("Failed to initialize GenAI client. Halting image generation.")
        return

    image_model_name = config.GENAI_IMAGE_GENERATION_MODEL
    if not image_model_name:
        log.critical("GENAI_IMAGE_GENERATION_MODEL not set in config. Cannot generate images.")
        return
    log.info(f"Using image generation model: {image_model_name}")

    api_delay = load_api_call_delay()
    log.info(f"Using API call delay of {api_delay} seconds between image generation calls.")

    prompts_input_dir = config.PROJECT_ROOT / config.PROMPTS_DIR_NAME
    images_output_dir = config.PROJECT_ROOT / config.IMAGES_DIR_NAME

    try:
        prompts_input_dir.mkdir(parents=True, exist_ok=True)
        images_output_dir.mkdir(parents=True, exist_ok=True)
        log.info(f"Prompts input directory: {prompts_input_dir}")
        log.info(f"Image output directory: {images_output_dir}")
    except OSError as e:
        log.error(f"Error creating directories: {e}", exc_info=True)
        return

    prompt_files = list(prompts_input_dir.glob('*.txt'))
    if not prompt_files:
        log.info(f"No prompt files found in {prompts_input_dir}. Nothing to process.")
        return

    log.info(f"Found {len(prompt_files)} prompt files to check for image generation.")

    generated_count = 0
    skipped_count = 0
    error_count = 0

    for prompt_filepath in prompt_files:
        log.info(f"Processing prompt: {prompt_filepath.name}")

        target_image_filepath = get_image_filepath(prompt_filepath, images_output_dir)

        check_image_path = pathlib.Path(target_image_filepath)

        if check_image_path.exists():
            log.info(f"Image already exists for {prompt_filepath.name} at {check_image_path}. Skipping.")
            skipped_count += 1
            continue

        try:
            prompt_content = prompt_filepath.read_text(encoding="utf-8")

            if not prompt_content:
                log.warning(f"Prompt file is empty {prompt_filepath.name}. Skipping image generation.")
                error_count +=1
                continue

            log.info(f"Attempting to generate image for '{prompt_filepath.name}'")

            image_bytes: bytes | None = None
            try:
                image_bytes = generate_featured_image_llm(
                    client=client,
                    model_name=image_model_name,
                    prompt=prompt_content,
                    prompt_filename=prompt_filepath.name,
                )
            except Exception as e_gen:
                log.error(f"Unexpected error during image generation call for {prompt_filepath.name}: {e_gen}", exc_info=True)
                error_count += 1
                continue
            finally:
                is_last_file_to_attempt = (prompt_files.index(prompt_filepath) == len(prompt_files) - 1)
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
                        error_count += 1
                except Exception as e_save:
                    log.error(f"Error saving image for {prompt_filepath.name} to {target_image_filepath}: {e_save}", exc_info=True)
                    error_count += 1
            else:
                log.warning(f"LLM did not return image data for {prompt_filepath.name}. No image saved.")

        except Exception as e_read_parse:
            log.error(f"Error reading or parsing prompt file {prompt_filepath.name}: {e_read_parse}", exc_info=True)
            error_count += 1
            continue

    log.info(f"Image generation process finished. "
             f"Generated: {generated_count}, Skipped (already exist): {skipped_count}, Errors: {error_count}.")

if __name__ == "__main__":
    log.info(f"Executing image_generator.py directly. Project root: {config.PROJECT_ROOT}")
    run_image_generation()
