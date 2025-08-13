import pathlib
import time
from google import genai
from google.genai import types
from src import config, prompts
import logging
import re
import html
from typing import List
import sys
import fitz  # PyMuPDF
from pydantic import BaseModel


class SingleArticle(BaseModel):
    ueberschrift: str
    inhalt: str
    tags: List[str] = []

class LLMGeneratedArticles(BaseModel):
    artikel: List[SingleArticle]

def sanitize_filename(name: str) -> str:
    """Sanitizes a string to be a valid filename."""
    name = re.sub(r'[^\w\s-]', '', name)
    name = re.sub(r'[-\s]+', '-', name).strip('-_')
    return name if name else "untitled"

def extract_text_from_pdf(pdf_filepath: pathlib.Path, logger) -> str:
    """Extracts all text content from a PDF file using PyMuPDF."""
    try:
        doc = fitz.open(pdf_filepath)
        full_text = ""
        for page in doc:
            full_text += page.get_text()
        logger.info(f"Successfully extracted text from {pdf_filepath.name} using PyMuPDF.")
        return full_text
    except Exception as e:
        logger.error(f"Error extracting text from {pdf_filepath.name} using PyMuPDF: {e}", exc_info=True)
        return ""

def generate_articles(text: str, logger) -> List[SingleArticle]:
    """Generates articles from text using a direct Google GenAI API call with retries."""
    logger.info("Generating articles...")
    max_retries = 5
    for attempt in range(max_retries):
        try:
            client = genai.Client(api_key=config.load_google_api_key())
            response = client.models.generate_content(
                model=config.GENAI_ARTICLE_GENERATION_MODEL,
                contents=prompts.GENAI_JOURNALISTIC_ARTICLE_PROMPT.replace("{PROTOCOL_TEXT}", text),
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    response_mime_type='application/json',
                    response_schema=LLMGeneratedArticles
                )
            )

            articles = response.parsed

            if articles and isinstance(articles, LLMGeneratedArticles):
                logger.info(f"Successfully generated and validated {len(articles.artikel)} articles on attempt {attempt + 1}.")
                return articles.artikel

            logger.warning(f"Article generation returned empty or invalid data on attempt {attempt + 1}/{max_retries}.")

        except Exception as e:
            logger.error(f"Error generating articles on attempt {attempt + 1}/{max_retries}: {e}", exc_info=True)

        if attempt < max_retries - 1:
            time.sleep(config.API_CALL_DELAY_SECONDS) # Wait before next retry

    logger.error("Failed to generate articles after multiple retries.")
    return []

def generate_image_prompt(article: SingleArticle, logger) -> str:
    """Generates an image prompt for an article using a direct Google GenAI API call with retries."""
    logger.info(f"Generating image prompt for article: '{article.ueberschrift}'")
    max_retries = 5
    for attempt in range(max_retries):
        try:
            full_article = f"{article.ueberschrift} {article.inhalt}"
            client = genai.Client(api_key=config.load_google_api_key())
            response = client.models.generate_content(
                model=config.GENAI_IMAGE_PROMPT_MODEL,
                contents=prompts.GENAI_IMAGE_PROMPT_GENERATOR_PROMPT.format(
                    complete_article=full_article
                ),
                config={
                    "temperature": 0.2
                }
            )

            if response.text:
                logger.info(f"Successfully generated image prompt for article: '{article.ueberschrift}' on attempt {attempt + 1}.")
                return response.text

            logger.warning(f"Image prompt generation returned empty data on attempt {attempt + 1}/{max_retries}.")
            try:
                if response.prompt_feedback.block_reason:
                    logger.error(f"Image prompt generation blocked. Reason: {response.prompt_feedback.block_reason}")
                    logger.error(f"Safety ratings: {response.prompt_feedback.safety_ratings}")
                    # If blocked, no point in retrying
                    break
            except AttributeError:
                pass

        except Exception as e:
            logger.error(f"Error generating image prompt for article '{article.ueberschrift}' on attempt {attempt + 1}/{max_retries}: {e}", exc_info=True)

        if attempt < max_retries - 1:
            time.sleep(config.API_CALL_DELAY_SECONDS)

    logger.error(f"Failed to generate image prompt for article '{article.ueberschrift}' after multiple retries.")
    return ""

def generate_image(prompt: str, logger) -> bytes:
    """Generates an image from a prompt using a direct Google GenAI API call with retries."""
    logger.info("Generating image...")
    max_retries = 5
    for attempt in range(max_retries):
        try:
            client = genai.Client(api_key=config.load_google_api_key())
            response = client.models.generate_images(
                model=config.GENAI_IMAGE_GENERATION_MODEL,
                prompt=prompt,
                config=types.GenerateImagesConfig(
                    number_of_images=1,
                    aspectRatio="16:9"
                )
            )

            if response.generated_images:
                # Assuming we only want the first image
                logger.info(f"Successfully generated image on attempt {attempt + 1}.")
                return response.generated_images[0].image.image_bytes

            logger.warning(f"No image data found in response on attempt {attempt + 1}/{max_retries}.")
            # Optional: Check for feedback if available
            try:
                if response.prompt_feedback.block_reason:
                    logger.error(f"Image generation blocked. Reason: {response.prompt_feedback.block_reason}")
                    logger.error(f"Safety ratings: {response.prompt_feedback.safety_ratings}")
                    # If blocked, no point in retrying
                    break
            except AttributeError:
                pass # No feedback available

        except Exception as e:
            logger.error(f"Error generating image on attempt {attempt + 1}/{max_retries}: {e}", exc_info=True)

        if attempt < max_retries - 1:
            time.sleep(config.API_CALL_DELAY_SECONDS) # Wait before next retry

    logger.error("Failed to generate image after multiple retries.")
    return b""

def save_article(article: SingleArticle, pdf_filename: str, logger):
    """Saves the article as an HTML file."""
    sane_pdf_name = sanitize_filename(pathlib.Path(pdf_filename).stem)
    sane_headline = sanitize_filename(article.ueberschrift)

    # Create a unique filename for each article
    short_headline = "_".join(sane_headline.split('-')[:5])
    if not short_headline: short_headline = "article"

    base_filename = f"{sane_pdf_name}_{short_headline}"

    articles_dir = config.PROJECT_ROOT / config.ARTICLES_DIR_NAME
    articles_dir.mkdir(parents=True, exist_ok=True)

    html_filepath = articles_dir / f"{base_filename}.html"
    counter = 1
    while html_filepath.exists():
        html_filepath = articles_dir / f"{base_filename}_{counter}.html"
        counter += 1

    html_content = f"<h1>{html.escape(article.ueberschrift)}</h1>\n{article.inhalt}"
    try:
        with open(html_filepath, "w", encoding="utf-8") as f:
            f.write(html_content)
        logger.info(f"Saved HTML article to: {html_filepath}")
    except IOError as e:
        logger.error(f"Error saving HTML article to {html_filepath}: {e}", exc_info=True)

def save_image(image_bytes: bytes, article: SingleArticle, pdf_filename: str, logger):
    """Saves the image as a PNG file."""
    sane_pdf_name = sanitize_filename(pathlib.Path(pdf_filename).stem)
    sane_headline = sanitize_filename(article.ueberschrift)

    # Create a unique filename for each article
    short_headline = "_".join(sane_headline.split('-')[:5])
    if not short_headline: short_headline = "article"

    base_filename = f"{sane_pdf_name}_{short_headline}"

    images_dir = config.PROJECT_ROOT / config.IMAGES_DIR_NAME
    images_dir.mkdir(parents=True, exist_ok=True)

    image_filepath = images_dir / f"{base_filename}.png"
    counter = 1
    while image_filepath.exists():
        image_filepath = images_dir / f"{base_filename}_{counter}.png"
        counter += 1

    try:
        with open(image_filepath, "wb") as f:
            f.write(image_bytes)
        logger.info(f"Saved image to: {image_filepath}")
    except IOError as e:
        logger.error(f"Error saving image to {image_filepath}: {e}", exc_info=True)

def run_pipeline():
    """The main pipeline function."""
    log_dir = config.PROJECT_ROOT / config.LOG_DIR_NAME
    log_dir.mkdir(parents=True, exist_ok=True)
    log_filepath = log_dir / config.get_log_filename()

    # Set up a logger for the entire run
    logger = logging.getLogger("pipeline")
    logger.setLevel(logging.INFO)

    # Remove existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Add a file handler
    fh = logging.FileHandler(log_filepath, encoding="utf-8")
    fh.setFormatter(logging.Formatter(config.LOG_FORMAT))
    logger.addHandler(fh)

    # Also add a stream handler to see logs in the console
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(logging.Formatter(config.LOG_FORMAT))
    logger.addHandler(sh)

    try:
        pdf_dir = config.PROJECT_ROOT / config.PDF_DIR_NAME
        if not pdf_dir.is_dir():
            logger.error(f"PDF directory not found: {pdf_dir}")
            return

        pdf_files = list(pdf_dir.glob('*.pdf'))
        if not pdf_files:
            logger.warning(f"No PDF files found in {pdf_dir}")
            return

        for pdf_filepath in pdf_files:
            logger.info(f"--- Starting pipeline for {pdf_filepath.name} ---")

            # Check if articles for this PDF already exist
            articles_dir = config.PROJECT_ROOT / config.ARTICLES_DIR_NAME
            sane_pdf_name = sanitize_filename(pdf_filepath.stem)
            existing_articles = list(articles_dir.glob(f"{sane_pdf_name}*.html"))

            if existing_articles:
                logger.info(f"Articles for '{pdf_filepath.name}' already exist. Checking for images.")
                # Check if images for all articles exist
                images_dir = config.PROJECT_ROOT / config.IMAGES_DIR_NAME
                all_images_exist = True
                for article_html in existing_articles:
                    image_filepath = images_dir / f"{article_html.stem}.png"
                    if not image_filepath.exists():
                        all_images_exist = False
                        break

                if all_images_exist:
                    logger.info(f"All articles and images for '{pdf_filepath.name}' already exist. Skipping.")
                    continue


            # 1. Extract text
            extracted_text = extract_text_from_pdf(pdf_filepath, logger)
            if not extracted_text:
                logger.error("Text extraction failed. Skipping rest of the pipeline for this file.")
                continue

            # 2. Generate articles
            articles = generate_articles(extracted_text, logger)
            if not articles:
                logger.error("Article generation failed. Skipping rest of the pipeline for this file.")
                continue

            # Save all articles first
            for article in articles:
                save_article(article, pdf_filepath.name, logger)

            # Then, generate images for all articles
            for article in articles:
                # 4. Generate image prompt
                image_prompt = generate_image_prompt(article, logger)
                if not image_prompt:
                    logger.warning(f"Image prompt generation failed for article: '{article.ueberschrift}'. Skipping image generation.")
                else:
                    # 5. Generate and save image
                    image_bytes = generate_image(image_prompt, logger)
                    if image_bytes:
                        save_image(image_bytes, article, pdf_filepath.name, logger)

                # API call delay
                time.sleep(config.API_CALL_DELAY_SECONDS)

            logger.info(f"--- Finished pipeline for {pdf_filepath.name} ---")
    except Exception as e:
        logger.error(f"An unexpected error occurred in the pipeline: {e}", exc_info=True)
