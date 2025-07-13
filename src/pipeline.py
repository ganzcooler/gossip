import pathlib
import time
import fitz  # PyMuPDF
import google.generativeai as genai
from langchain_google_genai import GoogleGenerativeAI
from langchain.prompts import PromptTemplate
from langchain.schema import StrOutputParser
from src import config, prompts
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

def extract_text_from_pdf(pdf_filepath: pathlib.Path) -> str:
    """Extracts all text content from a PDF file using PyMuPDF."""
    full_text = ""
    try:
        doc = fitz.open(pdf_filepath)
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            full_text += page.get_text()
        doc.close()
        print(f"Successfully extracted text from {pdf_filepath.name} using PyMuPDF.")
        return full_text
    except Exception as e:
        print(f"Error extracting text from {pdf_filepath.name} using PyMuPDF: {e}", file=sys.stderr)
        return ""

def generate_articles(text: str) -> List[SingleArticle]:
    """Generates articles from text using a Langchain chain."""
    print("Generating articles...")
    try:
        llm = GoogleGenerativeAI(model="gemini-1.5-flash", google_api_key=config.load_google_api_key())
        prompt = PromptTemplate(
            template=prompts.GENAI_JOURNALISTIC_ARTICLE_PROMPT,
            input_variables=["PROTOCOL_TEXT"],
        )
        chain = prompt | llm | StrOutputParser()

        response_text = chain.invoke({"PROTOCOL_TEXT": text})

        # Clean the response to be valid JSON
        response_text = response_text.strip()
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]

        response_json = json.loads(response_text)

        validated_data = LLMGeneratedArticles(**response_json)
        print(f"Successfully generated and validated {len(validated_data.artikel)} articles.")
        return validated_data.artikel
    except Exception as e:
        print(f"Error generating articles: {e}", file=sys.stderr)
        return []

def generate_image_prompt(article: SingleArticle) -> str:
    """Generates an image prompt for an article using a Langchain chain."""
    print(f"Generating image prompt for article: '{article.ueberschrift}'")
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

        print(f"Successfully generated image prompt for article: '{article.ueberschrift}'")
        return image_prompt
    except Exception as e:
        print(f"Error generating image prompt for article '{article.ueberschrift}': {e}", file=sys.stderr)
        return ""

def generate_image(prompt: str) -> bytes:
    """Generates an image from a prompt using the Google Generative AI API."""
    print("Generating image...")
    try:
        genai.configure(api_key=config.load_google_api_key())
        img_model = genai.GenerativeModel("imagen-3-flash-001") # Using Imagen 3 as requested
        response = img_model.generate_content(prompt)

        # Check if the response has image data
        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if part.inline_data and part.inline_data.data:
                    print("Successfully generated image.")
                    return part.inline_data.data

        print("No image data found in response.", file=sys.stderr)
        return b""
    except Exception as e:
        print(f"Error generating image: {e}", file=sys.stderr)
        return b""

def save_article_and_image(article: SingleArticle, image_bytes: bytes, pdf_filename: str):
    """Saves the article as an HTML file and the image as a PNG file."""
    sane_pdf_name = sanitize_filename(pathlib.Path(pdf_filename).stem)
    sane_headline = sanitize_filename(article.ueberschrift)

    # Create a unique filename for each article
    short_headline = "_".join(sane_headline.split('-')[:5])
    if not short_headline: short_headline = "article"

    base_filename = f"{sane_pdf_name}_{short_headline}"

    # Save article
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
        print(f"Saved HTML article to: {html_filepath}")
    except IOError as e:
        print(f"Error saving HTML article to {html_filepath}: {e}", file=sys.stderr)

    # Save image
    if image_bytes:
        images_dir = config.PROJECT_ROOT / config.IMAGES_DIR_NAME
        images_dir.mkdir(parents=True, exist_ok=True)
        image_filepath = images_dir / f"{html_filepath.stem}.png"

        try:
            with open(image_filepath, "wb") as f:
                f.write(image_bytes)
            print(f"Saved image to: {image_filepath}")
        except IOError as e:
            print(f"Error saving image to {image_filepath}: {e}", file=sys.stderr)

def run_pipeline():
    """The main pipeline function."""
    try:
        pdf_dir = config.PROJECT_ROOT / config.PDF_DIR_NAME
        if not pdf_dir.is_dir():
            print(f"PDF directory not found: {pdf_dir}", file=sys.stderr)
            return

        pdf_files = list(pdf_dir.glob('*.pdf'))
        if not pdf_files:
            print(f"No PDF files found in {pdf_dir}", file=sys.stderr)
            return

        for pdf_filepath in pdf_files:
            print(f"--- Starting pipeline for {pdf_filepath.name} ---")

            # Check if articles for this PDF already exist
            articles_dir = config.PROJECT_ROOT / config.ARTICLES_DIR_NAME
            sane_pdf_name = sanitize_filename(pdf_filepath.stem)
            existing_articles = list(articles_dir.glob(f"{sane_pdf_name}*.html"))

            if existing_articles:
                print(f"Articles for '{pdf_filepath.name}' already exist. Checking for images.")
                # Check if images for all articles exist
                images_dir = config.PROJECT_ROOT / config.IMAGES_DIR_NAME
                all_images_exist = True
                for article_html in existing_articles:
                    image_filepath = images_dir / f"{article_html.stem}.png"
                    if not image_filepath.exists():
                        all_images_exist = False
                        break

                if all_images_exist:
                    print(f"All articles and images for '{pdf_filepath.name}' already exist. Skipping.")
                    continue


            # 1. Extract text
            extracted_text = extract_text_from_pdf(pdf_filepath)
            if not extracted_text:
                print("Text extraction failed. Skipping rest of the pipeline for this file.", file=sys.stderr)
                continue

            # 2. Generate articles
            articles = generate_articles(extracted_text)
            if not articles:
                print("Article generation failed. Skipping rest of the pipeline for this file.", file=sys.stderr)
                continue

            # Process each article
            for article in articles:
                # 3. Generate image prompt
                image_prompt = generate_image_prompt(article)
                if not image_prompt:
                    print(f"Image prompt generation failed for article: '{article.ueberschrift}'. Skipping image generation.", file=sys.stderr)
                    image_bytes = b""
                else:
                    # 4. Generate image
                    image_bytes = generate_image(image_prompt)

                # 5. Save article and image
                save_article_and_image(article, image_bytes, pdf_filepath.name)

                # API call delay
                time.sleep(config.load_api_call_delay())

            print(f"--- Finished pipeline for {pdf_filepath.name} ---")
    except Exception as e:
        print(f"An unexpected error occurred in the pipeline: {e}", file=sys.stderr)
