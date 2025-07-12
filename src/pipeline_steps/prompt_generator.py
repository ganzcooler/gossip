# src/pipeline_steps/prompt_generator.py
import logging
import pathlib
import sys
import re
import google.generativeai as genai

# Ensure src directory is in sys.path for config import
project_root_for_import = pathlib.Path(__file__).resolve().parent.parent.parent
if str(project_root_for_import) not in sys.path:
    sys.path.insert(0, str(project_root_for_import))

try:
    from src import config
    from src.config import (
        load_google_api_key,
    )
except ImportError as e:
    temp_log_prompt_generator = logging.getLogger("prompt_generator_bootstrap_error")
    temp_log_prompt_generator.error(f"Error importing modules/config in prompt_generator.py: {e}")
    print(f"CRITICAL: Error importing modules/config in prompt_generator.py: {e}. Check sys.path and config.py.", file=sys.stderr)
    raise

log = config.get_logger(__name__, "logs/prompt-generator.log")

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
            genai_client_instance = genai.GenerativeModel(config.GENAI_ARTICLE_GENERATION_MODEL)
            log.info("Google GenAI Client initialized successfully for prompt generation.")
        except Exception as e:
            log.critical(f"Failed to initialize Google GenAI Client: {e}", exc_info=True)
            return None
    return genai_client_instance

def parse_html_article(html_content: str) -> tuple[str | None, str | None]:
    """
    Parses HTML content to extract title (from <h1>) and body (from <pre>).
    """
    title = None
    body = None
    title_match = re.search(r"<h1[^>]*>(.*?)</h1>", html_content, re.IGNORECASE | re.DOTALL)
    if title_match:
        title = title_match.group(1).strip()
    body_match = re.search(r"<pre[^>]*>(.*?)</pre>", html_content, re.IGNORECASE | re.DOTALL)
    if body_match:
        body = body_match.group(1).strip()
    if not title:
        log.warning("Could not parse title from HTML.")
    if not body:
        log.warning("Could not parse body from HTML.")
    return title, body

def generate_prompt_for_image(
    client: genai.GenerativeModel,
    model_name: str,
    article_title: str,
    article_text_snippet: str
) -> str | None:
    """
    Generates a prompt for an image generation AI.
    """
    if client is None:
        log.error("GenAI client not initialized. Cannot generate prompt.")
        return None

    prompt = f"Erstelle einen Prompt für eine Bildgenerator-KI, die ein Beitragsbild passend zu einem Artikel mit dem Titel '{article_title}' und folgendem Inhalt erstellen soll: {article_text_snippet}"
    log.info(f"Generating prompt for image with prompt (first 150 chars): {prompt[:150]}...")

    try:
        response = client.generate_content(
            contents=[prompt]
        )

        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            generated_prompt = "".join(part.text for part in response.candidates[0].content.parts)
            log.info(f"Successfully generated prompt for article: '{article_title}'.")
            return generated_prompt

        log.warning(f"No prompt data found in response for article: '{article_title}'. Response: {response}")
        return None

    except Exception as e:
        log.error(f"Unexpected error during prompt generation for '{article_title}': {e}", exc_info=True)
        return None

def run_prompt_generation():
    """
    Scans the articles directory for HTML files, generates a prompt for each,
    and saves it to the prompts directory.
    """
    log.info("Starting prompt generation process...")

    client = _initialize_genai_client()
    if not client:
        log.error("Failed to initialize GenAI client. Halting prompt generation.")
        return

    prompt_model_name = config.GENAI_ARTICLE_GENERATION_MODEL # Using the article generation model for prompt generation
    if not prompt_model_name:
        log.critical("GENAI_ARTICLE_GENERATION_MODEL not set in config. Cannot generate prompts.")
        return
    log.info(f"Using prompt generation model: {prompt_model_name}")

    articles_input_dir = config.PROJECT_ROOT / config.ARTICLES_DIR_NAME
    prompts_output_dir = config.PROJECT_ROOT / config.PROMPTS_DIR_NAME

    try:
        articles_input_dir.mkdir(parents=True, exist_ok=True)
        prompts_output_dir.mkdir(parents=True, exist_ok=True)
        log.info(f"Article input directory: {articles_input_dir}")
        log.info(f"Prompts output directory: {prompts_output_dir}")
    except OSError as e:
        log.error(f"Error creating directories: {e}", exc_info=True)
        return

    html_files = list(articles_input_dir.glob('*.html'))
    if not html_files:
        log.info(f"No HTML articles found in {articles_input_dir}. Nothing to process.")
        return

    log.info(f"Found {len(html_files)} HTML articles to check for prompt generation.")

    generated_count = 0
    skipped_count = 0
    error_count = 0

    for html_filepath in html_files:
        log.info(f"Processing article: {html_filepath.name}")

        prompt_filename_stem = html_filepath.stem
        prompt_filename = f"{prompt_filename_stem}.txt"
        target_prompt_filepath = prompts_output_dir / prompt_filename

        check_prompt_path = pathlib.Path(target_prompt_filepath)

        if check_prompt_path.exists():
            log.info(f"Prompt already exists for {html_filepath.name} at {check_prompt_path}. Skipping.")
            skipped_count += 1
            continue

        try:
            html_content = html_filepath.read_text(encoding="utf-8")
            article_title, article_body = parse_html_article(html_content)

            if not article_title and not article_body:
                log.warning(f"Could not parse title or body from {html_filepath.name}. Skipping prompt generation.")
                error_count +=1
                continue

            prompt_title = article_title if article_title else "Untitled Article"
            prompt_text_snippet = (article_body if article_body else "")[:500]

            log.info(f"Attempting to generate prompt for '{prompt_title}' (from {html_filepath.name})")

            generated_prompt: str | None = None
            try:
                generated_prompt = generate_prompt_for_image(
                    client=client,
                    model_name=prompt_model_name,
                    article_title=prompt_title,
                    article_text_snippet=prompt_text_snippet
                )
            except Exception as e_gen:
                log.error(f"Unexpected error during prompt generation call for {html_filepath.name}: {e_gen}", exc_info=True)
                error_count += 1
                continue

            if generated_prompt:
                try:
                    with open(target_prompt_filepath, "w", encoding="utf-8") as f:
                        f.write(generated_prompt)
                    log.info(f"Saved generated prompt to: {target_prompt_filepath}")
                    if target_prompt_filepath.exists():
                        log.info(f"Verified: Prompt file now exists at {target_prompt_filepath}")
                        generated_count += 1
                    else:
                        log.error(f"File write seemed to succeed but prompt file NOT FOUND at {target_prompt_filepath} after write attempt.")
                        error_count += 1
                except Exception as e_save:
                    log.error(f"Error saving prompt for {html_filepath.name} to {target_prompt_filepath}: {e_save}", exc_info=True)
                    error_count += 1
            else:
                log.warning(f"LLM did not return prompt data for {html_filepath.name}. No prompt saved.")

        except Exception as e_read_parse:
            log.error(f"Error reading or parsing HTML file {html_filepath.name}: {e_read_parse}", exc_info=True)
            error_count += 1
            continue

    log.info(f"Prompt generation process finished. "
             f"Generated: {generated_count}, Skipped (already exist): {skipped_count}, Errors: {error_count}.")

if __name__ == "__main__":
    log.info(f"Executing prompt_generator.py directly. Project root: {config.PROJECT_ROOT}")
    run_prompt_generation()
