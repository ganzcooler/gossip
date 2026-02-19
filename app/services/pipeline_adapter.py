"""
Adapter module to integrate existing src/ pipeline steps with the new async app structure.
This wraps the synchronous pipeline functions to work with async/await patterns.
"""

import asyncio
import logging
from pathlib import Path
from typing import List
import html

from app.config import GOOGLE_API_KEY
from app.models import Protocol
from src.pipeline_steps.generate_articles import generate_articles
from src.pipeline_steps.generate_image_prompt import generate_image_prompt
from src.pipeline_steps.generate_image import generate_image
from src.pipeline_steps.generate_insta_caption import generate_insta_caption
from src.models import SingleArticle

logger = logging.getLogger(__name__)


async def generate_articles_async(pdf_text: str) -> List[SingleArticle]:
    """
    Async wrapper for article generation.
    Runs the synchronous generate_articles in a thread pool.
    """
    loop = asyncio.get_event_loop()

    # Create a logger for the pipeline step
    step_logger = logging.getLogger("pipeline.generate_articles")

    try:
        articles = await loop.run_in_executor(
            None,  # Uses default executor
            generate_articles,
            pdf_text,
            step_logger
        )
        return articles
    except Exception as e:
        logger.error(f"Error generating articles: {e}")
        return []


async def generate_image_prompt_async(article: SingleArticle) -> str:
    """
    Async wrapper for image prompt generation.
    """
    loop = asyncio.get_event_loop()
    step_logger = logging.getLogger("pipeline.generate_image_prompt")

    try:
        prompt = await loop.run_in_executor(
            None,
            generate_image_prompt,
            article,
            step_logger
        )
        return prompt
    except Exception as e:
        logger.error(f"Error generating image prompt: {e}")
        return ""


async def generate_image_async(prompt: str) -> bytes:
    """
    Async wrapper for image generation.
    """
    loop = asyncio.get_event_loop()
    step_logger = logging.getLogger("pipeline.generate_image")

    try:
        image_bytes = await loop.run_in_executor(
            None,
            generate_image,
            prompt,
            step_logger
        )
        return image_bytes
    except Exception as e:
        logger.error(f"Error generating image: {e}")
        return b""


async def generate_insta_caption_async(article_content: str, article_stem: str, protocol_folder: Path):
    """
    Async wrapper for Instagram caption generation.
    """
    loop = asyncio.get_event_loop()
    step_logger = logging.getLogger("pipeline.generate_insta_caption")

    try:
        await loop.run_in_executor(
            None,
            generate_insta_caption,
            article_content,
            article_stem,
            step_logger
        )
    except Exception as e:
        logger.error(f"Error generating Instagram caption: {e}")


def save_article_to_file(article: SingleArticle, protocol_folder: Path, index: int) -> Path:
    """
    Save an article as an HTML file in the protocol folder.
    Returns the path to the saved file.
    """
    # Sanitize filename components
    safe_headline = sanitize_filename(article.ueberschrift)[:50]
    filename = f"article_{index:02d}_{safe_headline}.html"
    filepath = protocol_folder / filename

    # Create HTML content
    html_content = f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(article.ueberschrift)}</title>
    <style>
        body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }}
        h1 {{ color: #333; }}
        h2 {{ color: #666; }}
    </style>
</head>
<body>
    <h1>{html.escape(article.ueberschrift)}</h1>
    {article.inhalt}
</body>
</html>"""

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html_content)
        logger.info(f"Saved article to: {filepath}")
        return filepath
    except IOError as e:
        logger.error(f"Error saving article to {filepath}: {e}")
        raise


def save_image_to_file(image_bytes: bytes, protocol_folder: Path, article_index: int, suffix: str = "") -> Path:
    """
    Save an image as a PNG file in the protocol folder.
    Returns the path to the saved file.
    """
    filename = f"image_{article_index:02d}{suffix}.png"
    filepath = protocol_folder / filename

    try:
        with open(filepath, "wb") as f:
            f.write(image_bytes)
        logger.info(f"Saved image to: {filepath}")
        return filepath
    except IOError as e:
        logger.error(f"Error saving image to {filepath}: {e}")
        raise


def sanitize_filename(name: str) -> str:
    """
    Sanitize a string to be safe for use in filenames.
    Replaces spaces with underscores and removes special characters.
    """
    import re
    # Replace spaces with underscores
    name = name.replace(" ", "_")
    # Remove special characters
    name = re.sub(r'[^\w\-_.]', '', name)
    # Remove multiple underscores
    name = re.sub(r'_+', '_', name)
    return name.strip("_.-")


def create_insta_images_for_protocol(protocol_folder: Path):
    """
    Create Instagram-formatted images for all articles in a protocol folder.
    This uses the existing src/insta_images.py logic.
    """
    import sys
    from pathlib import Path

    # Add src to path if needed
    src_path = Path(__file__).resolve().parent.parent.parent / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))

    from src.insta_images import create_main_image, create_content_image, extract_article_content
    from src.insta_images import ContentBlock
    from PIL import Image, ImageFilter
    import logging

    logger_inst = logging.getLogger("pipeline.insta_images")

    # Find all generated images in the protocol folder
    image_files = list(protocol_folder.glob("image_*.png"))

    for image_path in image_files:
        # Find corresponding article
        article_index = image_path.stem.split("_")[1]
        article_path = protocol_folder / f"article_{article_index}_*.html"
        article_files = list(protocol_folder.glob(f"article_{article_index}_*.html"))

        if not article_files:
            logger_inst.warning(f"No article found for image: {image_path}")
            continue

        article_path = article_files[0]
        article_content = extract_article_content(article_path)

        if not article_content or not article_content.h1:
            logger_inst.warning(f"Could not extract content from: {article_path}")
            continue

        # Create main Instagram image
        insta_main_path = protocol_folder / f"insta_{article_index}_main.png"
        if not insta_main_path.exists():
            try:
                with Image.open(image_path) as img:
                    base_img = img.copy()
                    final_img = create_main_image(base_img, article_content.h1, article_path.stem)
                    final_img.save(insta_main_path, 'PNG', compress_level=9)
                    logger_inst.info(f"Created Instagram main image: {insta_main_path}")
            except Exception as e:
                logger_inst.error(f"Failed to create main Instagram image: {e}")

        # Create content images for each block
        for i, block in enumerate(article_content.content_blocks):
            insta_part_path = protocol_folder / f"insta_{article_index}_part{i+1}.png"
            if insta_part_path.exists():
                continue

            try:
                with Image.open(image_path) as img:
                    base_img = img.copy()
                    blurred_img = base_img.filter(ImageFilter.GaussianBlur(radius=3))
                    final_part_img = create_content_image(blurred_img, block)
                    final_part_img.save(insta_part_path, 'PNG', compress_level=9)
                    logger_inst.info(f"Created Instagram part image: {insta_part_path}")
            except Exception as e:
                logger_inst.error(f"Failed to create part Instagram image: {e}")