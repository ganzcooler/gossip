import re
import time
import logging
from google import genai
from google.genai import types

from app.core import config
from app.core import prompts

logger = logging.getLogger(__name__)

# Maximum allowed length for short articles (without HTML tags)
MAX_SHORT_ARTICLE_LENGTH = 530


def _strip_html_tags(html_text: str) -> str:
    """Remove HTML tags from text.

    Args:
        html_text: Text containing HTML tags.

    Returns:
        Text with HTML tags removed.
    """
    return re.sub(r'<[^>]+>', '', html_text)


def _get_text_length_without_html(html_text: str) -> int:
    """Get the length of text excluding HTML tags.

    Args:
        html_text: Text containing HTML tags.

    Returns:
        Character count without HTML tags.
    """
    return len(_strip_html_tags(html_text))


def _shorten_article(client: genai.Client, short_article: str, article_title: str) -> str | None:
    """Attempt to shorten an article that is too long.

    Args:
        client: The GenAI client instance.
        short_article: The article that needs to be shortened.
        article_title: The title of the article (for logging).

    Returns:
        The shortened article string if successful, None otherwise.
    """
    logger.debug(f"Attempting to shorten article: '{article_title}'")
    max_shorten_retries = 3
    for attempt in range(max_shorten_retries):
        try:
            response = client.models.generate_content(
                model=config.GENAI_IMAGE_PROMPT_MODEL,
                contents=prompts.SHORT_ARTICLE_RETRY_PROMPT.format(
                    short_article=short_article
                ),
                config=types.GenerateContentConfig(
                    temperature=0.7,
                )
            )

            if response.text:
                shortened_article = response.text.strip()
                text_length = _get_text_length_without_html(shortened_article)
                if text_length <= MAX_SHORT_ARTICLE_LENGTH:
                    logger.debug(f"Successfully shortened article for: '{article_title[:20]}'")
                    return shortened_article
                else:
                    logger.warning(f"Shortened article still too long ({text_length} chars). Retry {attempt + 1}/{max_shorten_retries}.")
                    short_article = shortened_article  # Use this as input for next attempt
            else:
                logger.warning(f"Shortening attempt {attempt + 1}/{max_shorten_retries} returned empty data.")

        except Exception as e:
            logger.error(f"Error shortening article '{article_title}' on attempt {attempt + 1}/{max_shorten_retries}: {e}", exc_info=True)

        if attempt < max_shorten_retries - 1:
            time.sleep(config.API_CALL_DELAY_SECONDS)

    logger.error(f"Failed to shorten article '{article_title}' after multiple retries.")
    return None


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
    # Temperature starts at 1.0 and decreases with each retry to encourage shorter, more focused output
    base_temperature = 1.0
    temperature_decay = 0.15

    for attempt in range(max_retries):
        try:
            client = genai.Client(api_key=config.load_google_api_key())
            # Reduce temperature on retries to get more deterministic (typically shorter) output
            current_temperature = max(0.1, base_temperature - (attempt * temperature_decay))

            response = client.models.generate_content(
                model=config.GENAI_IMAGE_PROMPT_MODEL,
                contents=prompts.SHORT_ARTICLE_PROMPT.format(
                    complete_article=article_content
                ),
                config=types.GenerateContentConfig(
                    temperature=current_temperature,
                )
            )

            if response.text:
                short_article = response.text.strip()

                # Validate length (without HTML tags)
                text_length = _get_text_length_without_html(short_article)
                if text_length <= MAX_SHORT_ARTICLE_LENGTH:
                    preview = short_article[:50] + "..." if len(short_article) > 50 else short_article
                    logger.debug(f"Successfully generated short article for article: '{article_title}' - Short Article: {preview}")
                    return short_article
                else:
                    logger.warning(f"Short article too long ({text_length} chars without HTML, max {MAX_SHORT_ARTICLE_LENGTH}). Attempting to shorten.")
                    # Try to shorten the article
                    shortened_article = _shorten_article(client, short_article, article_title)
                    if shortened_article:
                        return shortened_article
                    # If shortening failed, log and continue to retry with lower temperature
                    logger.warning(f"Shortening failed on attempt {attempt + 1}/{max_retries}, retrying with temperature={current_temperature - temperature_decay:.2f}")

            logger.warning(f"Short article generation returned empty data on attempt {attempt + 1}/{max_retries}.")

        except Exception as e:
            logger.error(f"Error generating short article for article '{article_title}' on attempt {attempt + 1}/{max_retries}: {e}", exc_info=True)

        if attempt < max_retries - 1:
            time.sleep(config.API_CALL_DELAY_SECONDS)

    logger.error(f"Failed to generate short article for article '{article_title}' after multiple retries.")
    return None
