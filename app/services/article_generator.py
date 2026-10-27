import logging
import re
import time
from typing import List

from app.core import config
from app.core import prompts
from app.core.models import LLMGeneratedArticles, SingleArticle
from app.services import AuthenticationError, ArticleGenerationError
from app.services import openrouter_client

logger = logging.getLogger(__name__)


def _is_auth_error(exception: Exception) -> bool:
    """Check whether an error is an authentication or account-level failure.

    OpenRouter uses HTTP 401/403 for auth problems and 402 for missing credits.
    None of these should be retried: retrying cannot fix an invalid key or an
    empty account balance.
    """
    status = getattr(exception, "status_code", None)
    if status is None:
        status = getattr(exception, "status", None)
    if status is None:
        status = getattr(exception, "code", None)

    if status in (401, 402, 403):
        return True

    error_str = str(exception).lower()
    auth_keywords = [
        "unauthorized",
        "forbidden",
        "api key",
        "authentication",
        "permission denied",
        "payment required",
        "insufficient credit",
        "credits depleted",
    ]
    return any(keyword in error_str for keyword in auth_keywords)


def _strip_code_fences(text: str) -> str:
    """Remove optional Markdown fences around a JSON response."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _parse_articles(raw: str) -> LLMGeneratedArticles:
    cleaned = _strip_code_fences(raw)
    return LLMGeneratedArticles.model_validate_json(cleaned)


def generate_articles(text: str) -> List[SingleArticle]:
    """Generate articles from text using OpenRouter with retries."""
    logger.debug("Generating articles via OpenRouter...")
    max_retries = 3
    last_error = None
    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "llm_generated_articles",
            "strict": True,
            "schema": LLMGeneratedArticles.model_json_schema(),
        },
    }

    for attempt in range(max_retries):
        try:
            raw = openrouter_client.chat_completion(
                model=config.OPENROUTER_TEXT_MODEL,
                prompt=prompts.JOURNALISTIC_ARTICLE_PROMPT.replace(
                    "{PROTOCOL_TEXT}", text
                ),
                response_format=response_format,
                max_tokens=8192,
                extra_body={
                    "reasoning": {"effort": config.OPENROUTER_REASONING_EFFORT}
                },
            )

            if not raw:
                logger.warning(
                    f"Article generation returned an empty response on "
                    f"attempt {attempt + 1}/{max_retries}."
                )
                if attempt < max_retries - 1:
                    time.sleep(config.API_CALL_DELAY_SECONDS)
                continue

            articles = _parse_articles(raw)
            if articles.artikel:
                logger.debug(
                    f"Successfully generated and validated {len(articles.artikel)} "
                    f"articles on attempt {attempt + 1}."
                )
                return articles.artikel

            logger.warning(
                f"Article generation returned no articles on "
                f"attempt {attempt + 1}/{max_retries}."
            )

        except Exception as e:
            logger.error(
                f"Error generating articles on attempt {attempt + 1}/{max_retries}: {e}",
                exc_info=True,
            )

            if _is_auth_error(e):
                logger.critical(
                    f"Authentication or account error detected: {e}. Stopping immediately."
                )
                raise AuthenticationError(f"Authentication failed: {e}") from e

            last_error = e

        if attempt < max_retries - 1:
            time.sleep(config.API_CALL_DELAY_SECONDS)

    logger.error(
        f"Failed to generate articles after {max_retries} retries. Last error: {last_error}"
    )
    if last_error is not None:
        raise ArticleGenerationError(
            f"Article generation failed after {max_retries} retries: {last_error}"
        )

    logger.warning(
        f"Article generation returned empty results after {max_retries} attempts."
    )
    return []
