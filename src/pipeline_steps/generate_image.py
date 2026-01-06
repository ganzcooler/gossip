import time
import logging
from google import genai
from google.genai import types
from src import config

def generate_image(prompt: str, logger: logging.Logger) -> bytes:
    """Generates an image from a prompt using a direct Google GenAI API call with retries."""
    logger.info("Generating image...")
    max_retries = 5
    for attempt in range(max_retries):
        try:
            client = genai.Client(api_key=config.load_google_api_key())
            response = client.models.generate_content(
                model=config.GENAI_IMAGE_GENERATION_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    image_config=types.ImageConfig( # type: ignore
                        aspect_ratio="16:9"
                    )
                )
            )

            for part in response.parts: # type: ignore
                if part.inline_data:
                    logger.info(f"Successfully generated image on attempt {attempt + 1}.")
                    return part.inline_data.data # type: ignore

            logger.warning(f"No image data found in response on attempt {attempt + 1}/{max_retries}.")

        except Exception as e:
            logger.error(f"Error generating image on attempt {attempt + 1}/{max_retries}: {e}", exc_info=True)

        if attempt < max_retries - 1:
            time.sleep(config.API_CALL_DELAY_SECONDS) # Wait before next retry

    logger.error("Failed to generate image after multiple retries.")
    return b""
