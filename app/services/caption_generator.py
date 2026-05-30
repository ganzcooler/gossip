import time
import logging
from google import genai
from google.genai import types

from app.core import config
from app.core import prompts

logger = logging.getLogger(__name__)


def generate_insta_caption(article_title: str, article_content: str) -> str | None:
    """Generates an Instagram caption for an article.

    Args:
        article_title: The title of the article.
        article_content: The content of the article.

    Returns:
        The generated caption string if successful, None otherwise.
    """
    logger.debug(f"Generating Instagram caption for article: '{article_title}'")
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
                    temperature=1.0,
                )
            )

            if response.text:
                caption = response.text.strip()
                preview = caption[:50] + "..." if len(caption) > 50 else caption
                logger.debug(f"Successfully generated Instagram caption for article: '{article_title}' - Caption: {preview}")
                return caption

            logger.warning(f"Instagram caption generation returned empty data on attempt {attempt + 1}/{max_retries}.")

        except Exception as e:
            logger.error(f"Error generating Instagram caption for article '{article_title}' on attempt {attempt + 1}/{max_retries}: {e}", exc_info=True)

        if attempt < max_retries - 1:
            time.sleep(config.API_CALL_DELAY_SECONDS)

    logger.error(f"Failed to generate Instagram caption for article '{article_title}' after multiple retries.")
    return None
