import logging
import time

from app.core import config
from app.core import prompts
from app.services import AuthenticationError
from app.services import openrouter_client

logger = logging.getLogger(__name__)


def _is_fatal_error(exception: Exception) -> bool:
    """Return True for provider/account errors that must not be retried."""
    status = getattr(exception, "status_code", None)
    if status in (401, 402, 403):
        return True

    error_str = str(exception).lower()
    return any(
        keyword in error_str
        for keyword in (
            "unauthorized",
            "forbidden",
            "api key",
            "authentication",
            "permission denied",
            "payment required",
            "insufficient credit",
            "credits depleted",
        )
    )


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
            response = openrouter_client.chat_completion(
                model=config.OPENROUTER_TEXT_MODEL,
                prompt=prompts.INSTA_CAPTION_PROMPT.format(
                    complete_article=article_content
                ),
                temperature=1.0,
                extra_body={
                    "reasoning": {"effort": config.OPENROUTER_REASONING_EFFORT}
                },
            )

            if response:
                caption = response.strip()
                preview = caption[:50] + "..." if len(caption) > 50 else caption
                logger.debug(
                    f"Successfully generated Instagram caption for article: "
                    f"'{article_title}' - Caption: {preview}"
                )
                return caption

            logger.warning(
                f"Instagram caption generation returned empty data on "
                f"attempt {attempt + 1}/{max_retries}."
            )

        except Exception as e:
            logger.error(
                f"Error generating Instagram caption for article '{article_title}' "
                f"on attempt {attempt + 1}/{max_retries}: {e}",
                exc_info=True,
            )
            if _is_fatal_error(e):
                raise AuthenticationError(f"Authentication failed: {e}") from e

        if attempt < max_retries - 1:
            time.sleep(config.API_CALL_DELAY_SECONDS)

    logger.error(
        f"Failed to generate Instagram caption for article '{article_title}' "
        "after multiple retries."
    )
    return None
