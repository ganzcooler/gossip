import time
import logging
from typing import List
from google import genai
from google.genai import types

from app.core import config
from app.core import prompts
from app.core.models import SingleArticle, LLMGeneratedArticles
from app.services import AuthenticationError, ArticleGenerationError

logger = logging.getLogger(__name__)


def _is_auth_error(exception: Exception) -> bool:
    """Check if an exception is an authentication error (401/403).

    The google-genai library throws exceptions with `code` and `status` attributes.
    HTTP 401 = UNAUTHORIZED, HTTP 403 = FORBIDDEN
    """
    # Check for common auth error indicators in the exception
    error_code = getattr(exception, 'code', None)
    status = getattr(exception, 'status', None)

    # Check for 401/403 status codes
    if status in (401, 403):
        return True
    if error_code in (401, 403):
        return True

    # Also check error message for auth-related keywords
    error_str = str(exception).lower()
    auth_keywords = ['unauthorized', 'forbidden', 'api key', 'authentication', 'permission denied']
    if any(keyword in error_str for keyword in auth_keywords):
        return True

    return False


def generate_articles(text: str) -> List[SingleArticle]:
    """Generates articles from text using a direct Google GenAI API call with retries."""
    logger.info("Generating articles...")
    max_retries = 5
    last_error = None
    for attempt in range(max_retries):
        try:
            client = genai.Client(api_key=config.load_google_api_key())
            response = client.models.generate_content(
                model=config.GENAI_ARTICLE_GENERATION_MODEL,
                contents=prompts.GENAI_JOURNALISTIC_ARTICLE_PROMPT.replace("{PROTOCOL_TEXT}", text),
                config=types.GenerateContentConfig(
                    response_mime_type='application/json',
                    response_schema=LLMGeneratedArticles
                )
            )

            articles = response.parsed

            if articles and isinstance(articles, LLMGeneratedArticles):
                logger.info(f"Successfully generated and validated {len(articles.artikel)} articles on attempt {attempt + 1}.")
                return articles.artikel

            logger.warning(f"Article generation returned empty or invalid data on attempt {attempt + 1}/{max_retries}.")

        except Exception as e:
            logger.error(f"Error generating articles on attempt {attempt + 1}/{max_retries}: {e}", exc_info=True)

            # Check for authentication errors - these should NOT be retried
            if _is_auth_error(e):
                logger.critical(f"Authentication error detected: {e}. Stopping immediately.")
                raise AuthenticationError(f"Authentication failed: {e}") from e

            last_error = e

        if attempt < max_retries - 1:
            time.sleep(config.API_CALL_DELAY_SECONDS)

    logger.error(f"Failed to generate articles after {max_retries} retries. Last error: {last_error}")
    # Distinguish between actual errors and empty responses
    if last_error is not None:
        # An actual exception occurred - raise to signal serious failure
        raise ArticleGenerationError(f"Article generation failed after {max_retries} retries: {last_error}")
    else:
        # All attempts returned empty but no exceptions - return empty list
        # This allows protocol_processor to handle it gracefully
        logger.warning(f"Article generation returned empty results after {max_retries} attempts.")
        return []
