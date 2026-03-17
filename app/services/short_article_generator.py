import time
import logging
from google import genai
from google.genai import types

from app.core import config
from app.core import prompts

logger = logging.getLogger(__name__)


def generate_short_article(article_title: str, article_content: str) -> str | None:
    """Generates a short article for an article.

    Args:
        article_title: The title of the article.
        article_content: The content of the article.

    Returns:
        The generated short article string if successful, None otherwise.
    """
    logger.debug(f"Generating short article for article: '{article_title}'")
    max_retries = 5
    for attempt in range(max_retries):
        try:
            client = genai.Client(api_key=config.load_google_api_key())
            response = client.models.generate_content(
                model=config.GENAI_IMAGE_PROMPT_MODEL,
                contents=prompts.SHORT_ARTICLE_PROMPT.format(
                    complete_article=article_content
                ),
                config=types.GenerateContentConfig(
                    temperature=1,
                )
            )

            if response.text:
                short_article = response.text.strip()
                preview = short_article[:50] + "..." if len(short_article) > 50 else short_article
                logger.debug(f"Successfully generated short article for article: '{article_title}' - Short Article: {preview}")
                return short_article

            logger.warning(f"Short article generation returned empty data on attempt {attempt + 1}/{max_retries}.")

        except Exception as e:
            logger.error(f"Error generating short article for article '{article_title}' on attempt {attempt + 1}/{max_retries}: {e}", exc_info=True)

        if attempt < max_retries - 1:
            time.sleep(config.API_CALL_DELAY_SECONDS)

    logger.error(f"Failed to generate short article for article '{article_title}' after multiple retries.")
    return None
