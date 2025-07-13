import pathlib
import time
from langchain_community.document_loaders import PyPDFLoader
import asyncio
import google.generativeai as genai
from langchain_google_genai import GoogleGenerativeAI
from langchain.prompts import PromptTemplate
from langchain.schema import StrOutputParser
from langchain_core.pydantic_v1 import BaseModel, Field
from src import config, prompts
import logging
import re
import html
from pydantic import BaseModel
from typing import List
import json
import sys


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

async def extract_text_from_pdf(pdf_filepath: pathlib.Path, logger) -> str:
    """Extracts all text content from a PDF file using PyPDFLoader."""
    try:
        loader = PyPDFLoader(str(pdf_filepath))
        pages = []
        async for page in loader.alazy_load():
            pages.append(page)

        full_text = "\n".join([page.page_content for page in pages])
        logger.info(f"Successfully extracted text from {pdf_filepath.name} using PyPDFLoader.")
        return full_text
    except Exception as e:
        logger.error(f"Error extracting text from {pdf_filepath.name} using PyPDFLoader: {e}", exc_info=True)
        return ""

def generate_articles(text: str, logger) -> List[SingleArticle]:
    """Generates articles from text using a Langchain chain."""
    logger.info("Generating articles...")
    try:
        llm = GoogleGenerativeAI(model="gemini-1.5-flash", google_api_key=config.load_google_api_key())

        class Articles(BaseModel):
            """A list of articles."""
            artikel: List[SingleArticle] = Field(description="A list of articles, each with a headline, content, and tags.")

        structured_llm = llm.with_structured_output(Articles)

        prompt = PromptTemplate(
            template=prompts.GENAI_JOURNALISTIC_ARTICLE_PROMPT,
            input_variables=["PROTOCOL_TEXT"],
        )

        chain = prompt | structured_llm

        response = chain.invoke({"PROTOCOL_TEXT": text})

        logger.info(f"Successfully generated and validated {len(response.artikel)} articles.")
        return response.artikel
    except Exception as e:
        logger.error(f"Error generating articles: {e}", exc_info=True)
        return []

def generate_image_prompt(article: SingleArticle, logger) -> str:
    """Generates an image prompt for an article using a Langchain chain."""
    logger.info(f"Generating image prompt for article: '{article.ueberschrift}'")
    try:
        llm = GoogleGenerativeAI(model="gemini-1.5-flash", google_api_key=config.load_google_api_key())
        prompt = PromptTemplate(
            template=prompts.GENAI_IMAGE_PROMPT_GENERATOR_PROMPT,
            input_variables=["article_title", "article_text_snippet"],
        )
        chain = prompt | llm | StrOutputParser()

        image_prompt = chain.invoke({
            "article_title": article.ueberschrift,
            "article_text_snippet": article.inhalt[:500]
        })

        logger.info(f"Successfully generated image prompt for article: '{article.ueberschrift}'")
        return image_prompt
    except Exception as e:
        logger.error(f"Error generating image prompt for article '{article.ueberschrift}': {e}", exc_info=True)
        return ""

import requests

def generate_image(prompt: str, logger) -> bytes:
    """Generates an image from a prompt using Langchain."""
    logger.info("Generating image...")
    try:
        llm = GoogleGenerativeAI(model="gemini-1.5-flash", google_api_key=config.load_google_api_key())

        # The image generation model returns a URL to the image.
        image_url = llm.invoke(prompt)

        if image_url and image_url.startswith("http"):
            response = requests.get(image_url, stream=True)
            response.raise_for_status()
            logger.info("Successfully generated image.")
            return response.content

        logger.error("No image URL found in response.")
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

    # Save article
    if not image_bytes:
        articles_dir = config.PROJECT_ROOT / config.ARTICLES_DIR_NAME
        articles_dir.mkdir(parents=True, exist_ok=True)
        html_filepath = articles_dir / f"{base_filename}.html"

        # Ensure unique filenames
        counter = 1
        while html_filepath.exists():
            html_filepath = articles_dir / f"{base_filename}_{counter}.html"
            counter += 1

        tags_html = ""
        if article.tags:
            escaped_tags = [html.escape(tag) for tag in article.tags]
            tags_html = f'<div class="tags"><strong>Tags:</strong> {", ".join(escaped_tags)}</div>'

        html_content = f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(article.ueberschrift)}</title>
</head>
<body>
    <h1>{html.escape(article.ueberschrift)}</h1>
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

    # Save image
    if image_bytes:
        images_dir = config.PROJECT_ROOT / config.IMAGES_DIR_NAME
        images_dir.mkdir(parents=True, exist_ok=True)

        # Find the corresponding html file
        articles_dir = config.PROJECT_ROOT / config.ARTICLES_DIR_NAME
        html_filepath = None
        for f in articles_dir.glob(f"{base_filename}*.html"):
            html_filepath = f
            break

        if html_filepath:
            image_filepath = images_dir / f"{html_filepath.stem}.png"

            try:
                with open(image_filepath, "wb") as f:
                    f.write(image_bytes)
                logger.info(f"Saved image to: {image_filepath}")
            except IOError as e:
                logger.error(f"Error saving image to {image_filepath}: {e}", exc_info=True)
        else:
            logger.error(f"Could not find corresponding HTML file for image for PDF '{pdf_filename}' and article '{article.ueberschrift}'")

async def run_pipeline():
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
            extracted_text = await extract_text_from_pdf(pdf_filepath, logger)
            if not extracted_text:
                logger.error("Text extraction failed. Skipping rest of the pipeline for this file.")
                continue

            # 2. Generate articles
            articles = generate_articles(extracted_text, logger)
            if not articles:
                logger.error("Article generation failed. Skipping rest of the pipeline for this file.")
                continue

            # Process each article
            for article in articles:
                # 3. Save article
                save_article_and_image(article, b"", pdf_filepath.name, logger)

                # 4. Generate image prompt
                image_prompt = generate_image_prompt(article, logger)
                if not image_prompt:
                    logger.warning(f"Image prompt generation failed for article: '{article.ueberschrift}'. Skipping image generation.")
                else:
                    # 5. Generate and save image
                    image_bytes = generate_image(image_prompt, logger)
                    if image_bytes:
                        save_article_and_image(article, image_bytes, pdf_filepath.name, logger)

                # API call delay
                time.sleep(config.API_CALL_DELAY_SECONDS)

            logger.info(f"--- Finished pipeline for {pdf_filepath.name} ---")
    except Exception as e:
        logger.error(f"An unexpected error occurred in the pipeline: {e}", exc_info=True)
