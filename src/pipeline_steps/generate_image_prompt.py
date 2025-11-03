import time
import logging
from google import genai
from google.genai import types
from src import config, prompts
from src.models import SingleArticle

def generate_image_prompt(article: SingleArticle, logger: logging.Logger) -> str:
    """Generates an image prompt for an article using a direct Google GenAI API call with retries."""
    logger.info(f"Generating image prompt for article: '{article.ueberschrift}'")
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
                logger.info(f"Successfully generated image prompt for article: '{article.ueberschrift}' on attempt {attempt + 1}.")
                logger.info(f"Image Prompt: {response.text}")
                return response.text

            logger.warning(f"Image prompt generation returned empty data on attempt {attempt + 1}/{max_retries}.")

        except Exception as e:
            logger.error(f"Error generating image prompt for article '{article.ueberschrift}' on attempt {attempt + 1}/{max_retries}: {e}", exc_info=True)

        if attempt < max_retries - 1:
            time.sleep(config.API_CALL_DELAY_SECONDS)

    logger.error(f"Failed to generate image prompt for article '{article.ueberschrift}' after multiple retries.")
    return ""
