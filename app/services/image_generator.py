import time
import logging
from typing import Tuple
from google import genai
from google.genai import types

from app.core import config
from app.core import prompts
from app.core.models import SingleArticle

logger = logging.getLogger(__name__)


def validate_image_prompt(prompt: str, client: genai.Client) -> Tuple[bool, str]:
    """Validates if an image prompt requests a realistic style (not comic/animation).
    
    Returns:
        Tuple of (is_realistic: bool, prompt: str)
    """
    try:
        logger.debug(f"Validating image prompt: {prompt[:50]}...")
        response = client.models.generate_content(
            model=config.GENAI_CLASSIFICATION_MODEL,
            contents=prompts.GENAI_IMAGE_PROMPT_VALIDATION_PROMPT.format(image_prompt=prompt),
            config=types.GenerateContentConfig(
                temperature=0.0
            )
        )
        
        if response.text:
            answer = response.text.strip().upper()
            is_realistic = answer == "YES"
            logger.debug(f"Prompt validation result: {answer} (realistic: {is_realistic})")
            return is_realistic, prompt
        
        logger.warning("Prompt validation returned empty response, treating as not realistic")
        return False, prompt
        
    except Exception as e:
        logger.error(f"Error validating image prompt: {e}", exc_info=True)
        return False, prompt


def make_prompt_realistic(prompt: str, client: genai.Client) -> str:
    """Rewrites a non-realistic prompt to request realistic image style."""
    try:
        response = client.models.generate_content(
            model=config.GENAI_CLASSIFICATION_MODEL,
            contents=prompts.GENAI_IMAGE_PROMPT_REALISTIC_REWRITE_PROMPT.format(image_prompt=prompt),
            config=types.GenerateContentConfig(
                temperature=0.2
            )
        )
        
        if response.text:
            rewritten_prompt = response.text.strip()
            logger.debug(f"Rewrote prompt to realistic style. Original: {prompt[:50]}... New: {rewritten_prompt[:50]}...")
            return rewritten_prompt
        
        logger.warning("Prompt rewrite returned empty response, keeping original")
        return prompt
        
    except Exception as e:
        logger.error(f"Error making prompt realistic: {e}", exc_info=True)
        return prompt


def generate_image_prompt(article: SingleArticle) -> str:
    """Generates an image prompt for an article using a direct Google GenAI API call with retries."""
    logger.debug(f"Generating image prompt for article: '{article.ueberschrift}'")
    max_retries = 5
    for attempt in range(max_retries):
        try:
            full_article = f"{article.ueberschrift} {article.inhalt}"
            client = genai.Client(api_key=config.load_google_api_key())
            response = client.models.generate_content(
                model=config.GENAI_IMAGE_PROMPT_MODEL,
                contents=prompts.GENAI_IMAGE_PROMPT_GENERATOR_PROMPT.format(
                    complete_article=full_article
                ),
                config=types.GenerateContentConfig(
                    temperature=0.2
                )
            )

            if response.text:
                logger.debug(f"Successfully generated image prompt for article: '{article.ueberschrift}' on attempt {attempt + 1}.")
                logger.debug(f"Image Prompt: {response.text}")
                return response.text

            logger.warning(f"Image prompt generation returned empty data on attempt {attempt + 1}/{max_retries}.")

        except Exception as e:
            logger.error(f"Error generating image prompt for article '{article.ueberschrift}' on attempt {attempt + 1}/{max_retries}: {e}", exc_info=True)

        if attempt < max_retries - 1:
            time.sleep(config.API_CALL_DELAY_SECONDS)

    logger.error(f"Failed to generate image prompt for article '{article.ueberschrift}' after multiple retries.")
    return ""


def generate_image(prompt: str) -> bytes:
    """Generates an image from a prompt using a direct Google GenAI API call with retries."""
    logger.debug("Generating image...")
    max_retries = 5
    for attempt in range(max_retries):
        try:
            client = genai.Client(api_key=config.load_google_api_key())
            response = client.models.generate_content(
                model=config.GENAI_IMAGE_GENERATION_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    image_config=types.ImageConfig(
                        aspect_ratio="9:16"
                    )
                )
            )

            for part in response.parts:
                if part.inline_data:
                    logger.debug(f"Successfully generated image on attempt {attempt + 1}.")
                    return part.inline_data.data

            logger.warning(f"No image data found in response on attempt {attempt + 1}/{max_retries}.")

        except Exception as e:
            logger.error(f"Error generating image on attempt {attempt + 1}/{max_retries}: {e}", exc_info=True)

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
    client = genai.Client(api_key=config.load_google_api_key())
    max_validation_attempts = 3
    
    for attempt in range(max_validation_attempts):
        is_realistic, prompt = validate_image_prompt(prompt, client)
        if is_realistic:
            logger.debug(f"Prompt validated as realistic on attempt {attempt + 1}")
            break
        
        if attempt < max_validation_attempts - 1:
            logger.debug(f"Prompt not realistic, rewriting (attempt {attempt + 1}/{max_validation_attempts})")
            prompt = make_prompt_realistic(prompt, client)
        else:
            logger.warning(f"Prompt still not realistic after {max_validation_attempts} attempts, using last version anyway")

    image_bytes = generate_image(prompt)
    return prompt, image_bytes
