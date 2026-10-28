import logging
import time
from typing import Tuple

from app.core import config
from app.core import prompts
from app.core.models import SingleArticle
from app.services import AuthenticationError
from app.services import openrouter_client

logger = logging.getLogger(__name__)


def _is_fatal_error(exception: Exception) -> bool:
    """Return True for errors that cannot be fixed by retrying."""
    status = getattr(exception, "status_code", None)
    if status in (401, 402, 403):
        return True

    error_str = str(exception).lower()
    fatal_keywords = [
        "unauthorized",
        "forbidden",
        "api key",
        "authentication",
        "permission denied",
        "payment required",
        "insufficient credit",
        "credits depleted",
    ]
    return any(keyword in error_str for keyword in fatal_keywords)


def validate_image_prompt(prompt: str) -> Tuple[bool, str]:
    """Validates if an image prompt requests a realistic style (not comic/animation).

    Returns:
        Tuple of (is_realistic: bool, prompt: str)
    """
    try:
        logger.debug(f"Validating image prompt: {prompt[:50]}...")
        response = openrouter_client.chat_completion(
            model=config.OPENROUTER_TEXT_MODEL,
            prompt=prompts.IMAGE_PROMPT_VALIDATION_PROMPT.format(
                image_prompt=prompt
            ),
            temperature=1.0,
            extra_body={
                "reasoning": {"effort": config.OPENROUTER_REASONING_EFFORT}
            },
        )

        if response:
            answer = response.strip().upper()
            is_realistic = answer == "YES"
            logger.debug(
                f"Prompt validation result: {answer} (realistic: {is_realistic})"
            )
            return is_realistic, prompt

        logger.warning(
            "Prompt validation returned empty response, treating as not realistic"
        )
        return False, prompt

    except Exception as e:
        logger.error(f"Error validating image prompt: {e}", exc_info=True)
        if _is_fatal_error(e):
            raise AuthenticationError(f"Authentication failed: {e}") from e
        return False, prompt


def make_prompt_realistic(prompt: str) -> str:
    """Rewrites a non-realistic prompt to request realistic image style."""
    try:
        response = openrouter_client.chat_completion(
            model=config.OPENROUTER_TEXT_MODEL,
            prompt=prompts.IMAGE_PROMPT_REALISTIC_REWRITE_PROMPT.format(
                image_prompt=prompt
            ),
            temperature=1.0,
            extra_body={
                "reasoning": {"effort": config.OPENROUTER_REASONING_EFFORT}
            },
        )

        if response:
            rewritten_prompt = response.strip()
            logger.debug(
                f"Rewrote prompt to realistic style. Original: {prompt[:50]}... "
                f"New: {rewritten_prompt[:50]}..."
            )
            return rewritten_prompt

        logger.warning("Prompt rewrite returned empty response, keeping original")
        return prompt

    except Exception as e:
        logger.error(f"Error making prompt realistic: {e}", exc_info=True)
        if _is_fatal_error(e):
            raise AuthenticationError(f"Authentication failed: {e}") from e
        return prompt


def generate_image_prompt(article: SingleArticle) -> str:
    """Generates an image prompt for an article using OpenRouter with retries."""
    logger.debug(f"Generating image prompt for article: '{article.ueberschrift}'")
    max_retries = 5
    for attempt in range(max_retries):
        try:
            full_article = f"{article.ueberschrift} {article.inhalt}"
            response = openrouter_client.chat_completion(
                model=config.OPENROUTER_TEXT_MODEL,
                prompt=prompts.IMAGE_PROMPT_GENERATOR_PROMPT.format(
                    complete_article=full_article
                ),
                temperature=1.0,
                extra_body={
                    "reasoning": {"effort": config.OPENROUTER_REASONING_EFFORT}
                },
            )

            if response:
                logger.debug(
                    f"Successfully generated image prompt for article: "
                    f"'{article.ueberschrift}' on attempt {attempt + 1}."
                )
                logger.debug(f"Image Prompt: {response}")
                return response

            logger.warning(
                f"Image prompt generation returned empty data on "
                f"attempt {attempt + 1}/{max_retries}."
            )

        except Exception as e:
            logger.error(
                f"Error generating image prompt for article "
                f"'{article.ueberschrift}' on attempt {attempt + 1}/{max_retries}: {e}",
                exc_info=True,
            )
            if _is_fatal_error(e):
                raise AuthenticationError(f"Authentication failed: {e}") from e

        if attempt < max_retries - 1:
            time.sleep(config.API_CALL_DELAY_SECONDS)

    logger.error(
        f"Failed to generate image prompt for article '{article.ueberschrift}' "
        "after multiple retries."
    )
    return ""


def generate_image(prompt: str) -> bytes:
    """Generates an image from a prompt using OpenRouter with retries."""
    logger.debug("Generating image...")
    max_retries = 5
    for attempt in range(max_retries):
        try:
            image_bytes = openrouter_client.generate_image(
                model=config.OPENROUTER_IMAGE_MODEL,
                prompt=prompt,
                aspect_ratio="9:16",
            )

            if image_bytes:
                logger.debug(
                    f"Successfully generated image on attempt {attempt + 1}."
                )
                return image_bytes

            logger.warning(
                f"No image data found in response on attempt "
                f"{attempt + 1}/{max_retries}."
            )

        except Exception as e:
            logger.error(
                f"Error generating image on attempt {attempt + 1}/{max_retries}: {e}",
                exc_info=True,
            )
            if _is_fatal_error(e):
                raise AuthenticationError(f"Authentication failed: {e}") from e

        if attempt < max_retries - 1:
            time.sleep(config.API_CALL_DELAY_SECONDS)

    logger.error("Failed to generate image after multiple retries.")
    return b""


def generate_image_for_article(article: SingleArticle) -> Tuple[str, bytes]:
    """Generate both prompt and image for an article."""
    prompt = generate_image_prompt(article)
    if not prompt:
        return "", b""

    # Validate and potentially rewrite prompt to be realistic (max 3 iterations)
    max_validation_attempts = 3

    for attempt in range(max_validation_attempts):
        is_realistic, prompt = validate_image_prompt(prompt)
        if is_realistic:
            logger.debug(f"Prompt validated as realistic on attempt {attempt + 1}")
            break

        if attempt < max_validation_attempts - 1:
            logger.debug(
                f"Prompt not realistic, rewriting "
                f"(attempt {attempt + 1}/{max_validation_attempts})"
            )
            prompt = make_prompt_realistic(prompt)
        else:
            logger.warning(
                f"Prompt still not realistic after {max_validation_attempts} "
                "attempts, using last version anyway"
            )

    image_bytes = generate_image(prompt)
    return prompt, image_bytes
