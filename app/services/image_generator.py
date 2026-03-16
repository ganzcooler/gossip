import time
import logging
from typing import Tuple
from google import genai
from google.genai import types

from app.core import config
from app.core import prompts
from app.core.models import SingleArticle

logger = logging.getLogger(__name__)


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
                        aspect_ratio="4:5"
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

    image_bytes = generate_image(prompt)
    return prompt, image_bytes
