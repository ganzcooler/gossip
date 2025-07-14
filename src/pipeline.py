import pathlib
import time
from google import genai
from src import config, prompts
import logging
import re
import html
from typing import List
import sys
import fitz  # PyMuPDF
from pydantic import BaseModel, Field


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
    """Generates articles from text using a direct Google GenAI API call."""
    logger.info("Generating articles...")
    try:
        client = genai.Client(api_key=config.load_google_api_key())
        response = client.models.generate_content(
            model=config.GENAI_ARTICLE_GENERATION_MODEL,
            contents=prompts.GENAI_JOURNALISTIC_ARTICLE_PROMPT.format(PROTOCOL_TEXT=text),
            config={
                "response_mime_type": "application/json",
                "response_schema": LLMGeneratedArticles,
            },
        )

        articles = response.parsed
        logger.info(f"Successfully generated and validated {len(articles.artikel)} articles.")
        return articles.artikel
    except Exception as e:
        logger.error(f"Error generating articles: {e}", exc_info=True)
        return []

def generate_image_prompt(article: SingleArticle, logger) -> str:
    """Generates an image prompt for an article using a direct Google GenAI API call."""
    logger.info(f"Generating image prompt for article: '{article.ueberschrift}'")
    try:
        client = genai.Client(api_key=config.load_google_api_key())
        response = client.models.generate_content(
            model=config.GENAI_ARTICLE_GENERATION_MODEL,
            contents=prompts.GENAI_IMAGE_PROMPT_GENERATOR_PROMPT.format(
                article_title=article.ueberschrift,
                article_text_snippet=article.inhalt[:500]
            ),
        )
        logger.info(f"Successfully generated image prompt for article: '{article.ueberschrift}'")
        return response.text
    except Exception as e:
        logger.error(f"Error generating image prompt for article '{article.ueberschrift}': {e}", exc_info=True)
        return ""

def generate_image(prompt: str, logger) -> bytes:
    """Generates an image from a prompt using a direct Google GenAI API call."""
    logger.info("Generating image...")
    try:
        client = genai.Client(api_key=config.load_google_api_key())
        response = client.models.generate_images(
            model=config.GENAI_IMAGE_GENERATION_MODEL,
            prompt=prompt,
        )

        if response.generated_images:
            # Assuming we only want the first image
            return response.generated_images[0].image.image_bytes

        logger.error("No image data found in response.")
        return b""
    except Exception as e:
        logger.error(f"Error generating image: {e}", exc_info=True)
        return b""

def save_article_and_image(article: SingleArticle, image_bytes: bytes, pdf_filename: str, logger):
    """Saves the article as an HTML file and the image as a PNG file."""
    sane_pdf_name = sanitize_filename(pathlib.Path(pdf_filename).stem)
    sane_headline = sanitize_filename(article.ueberschrift)

    # Create a unique filename for each article
    short_headline = "_".join(sane_headline.split('-')[:5])
    if not short_headline: short_headline = "article"

    base_filename = f"{sane_pdf_name}_{short_headline}"

    articles_dir = config.PROJECT_ROOT / config.ARTICLES_DIR_NAME
    images_dir = config.PROJECT_ROOT / config.IMAGES_DIR_NAME
    articles_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)

    html_filepath = articles_dir / f"{base_filename}.html"
    counter = 1
    while html_filepath.exists():
        html_filepath = articles_dir / f"{base_filename}_{counter}.html"
        counter += 1

    image_filepath = images_dir / f"{html_filepath.stem}.png"

    tags_html = ""
    if article.tags:
        escaped_tags = [html.escape(tag) for tag in article.tags]
        tags_html = f'<div class="tags"><strong>Tags:</strong> {", ".join(escaped_tags)}</div>'

    image_html = ""
    if image_bytes:
        try:
            with open(image_filepath, "wb") as f:
                f.write(image_bytes)
            logger.info(f"Saved image to: {image_filepath}")
            image_html = f'<img src="../{config.IMAGES_DIR_NAME}/{image_filepath.name}" alt="{html.escape(article.ueberschrift)}">'
        except IOError as e:
            logger.error(f"Error saving image to {image_filepath}: {e}", exc_info=True)

    html_content = f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(article.ueberschrift)}</title>
</head>
<body>
    <h1>{html.escape(article.ueberschrift)}</h1>
    {image_html}
    <pre>{html.escape(article.inhalt)}</pre>
    {tags_html}
</body>
</html>
"""
    try:
        with open(html_filepath, "w", encoding="utf-8") as f:
            f.write(html_content)
        logger.info(f"Saved HTML article to: {html_filepath}")
    except IOError as e:
        logger.error(f"Error saving HTML article to {html_filepath}: {e}", exc_info=True)

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

            # 3. Save articles to JSON
            articles_dir = config.PROJECT_ROOT / config.ARTICLES_DIR_NAME
            articles_dir.mkdir(parents=True, exist_ok=True)
            json_filepath = articles_dir / f"{sane_pdf_name}.json"

            # Use Pydantic's json() method to dump the list of articles
            with open(json_filepath, "w", encoding="utf-8") as f:
                # Create a list of dicts from the list of SingleArticle objects
                articles_dict = [article.dict() for article in articles]
                import json
                json.dump(articles_dict, f, ensure_ascii=False, indent=4)
            logger.info(f"Saved articles to: {json_filepath}")

            # 4. Process each article for image generation
            for article in articles:
                # Generate image prompt
                image_prompt = generate_image_prompt(article, logger)
                if not image_prompt:
                    logger.warning(f"Image prompt generation failed for article: '{article.ueberschrift}'. Skipping image generation.")
                    # Save article without image
                    save_article_and_image(article, b"", pdf_filepath.name, logger)
                else:
                    # Generate and save image
                    image_bytes = generate_image(image_prompt, logger)
                    save_article_and_image(article, image_bytes, pdf_filepath.name, logger)

                # API call delay
                time.sleep(config.API_CALL_DELAY_SECONDS)

            logger.info(f"--- Finished pipeline for {pdf_filepath.name} ---")
    except Exception as e:
        logger.error(f"An unexpected error occurred in the pipeline: {e}", exc_info=True)
