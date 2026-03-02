import time
import logging
from pathlib import Path
from google import genai
from google.genai import types

from app.core import config
from app.core import prompts

logger = logging.getLogger(__name__)


def generate_insta_caption(article_content: str, article_stem: str, caption_dir: Path):
    """Generates and saves an Instagram caption for an article."""
    caption_path = caption_dir / f"{article_stem}_caption.txt"

    if caption_path.is_file():
        logger.info(f"Caption file already exists for article '{article_stem}', skipping generation.")
        return

    logger.info(f"Generating Instagram caption for article: '{article_stem}'")
    max_retries = 5
    for attempt in range(max_retries):
        try:
            client = genai.Client(api_key=config.load_google_api_key())
            response = client.models.generate_content(
                model=config.GENAI_IMAGE_PROMPT_MODEL,
                contents=prompts.INSTA_CAPTION_PROMPT.format(
                    complete_article=article_content
                ),
                config=types.GenerateContentConfig(
                    temperature=1,
                )
            )

            if response.text:
                caption = response.text.strip()
                preview = caption[:50] + "..." if len(caption) > 50 else caption
                logger.info(f"Successfully generated Instagram caption for article: '{article_stem}' - Caption: {preview}")

                # Save the caption to a file
                caption_dir.mkdir(parents=True, exist_ok=True)

                with open(caption_path, "w", encoding="utf-8") as f:
                    f.write(caption)

                logger.info(f"Successfully saved caption to {caption_path}")
                return

            logger.warning(f"Instagram caption generation returned empty data on attempt {attempt + 1}/{max_retries}.")

        except Exception as e:
            logger.error(f"Error generating Instagram caption for article '{article_stem}' on attempt {attempt + 1}/{max_retries}: {e}", exc_info=True)

        if attempt < max_retries - 1:
            time.sleep(config.API_CALL_DELAY_SECONDS)

    logger.error(f"Failed to generate Instagram caption for article '{article_stem}' after multiple retries.")
