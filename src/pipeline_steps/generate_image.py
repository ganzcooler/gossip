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
            response = client.models.generate_images(
                model=config.GENAI_IMAGE_GENERATION_MODEL,
                prompt=prompt,
                config=types.GenerateImagesConfig(
                    number_of_images=1,
                    aspectRatio="16:9"
                )
            )

            if response.generated_images:
                # Assuming we only want the first image
                logger.info(f"Successfully generated image on attempt {attempt + 1}.")
                return response.generated_images[0].image.image_bytes

            logger.warning(f"No image data found in response on attempt {attempt + 1}/{max_retries}.")

        except Exception as e:
            logger.error(f"Error generating image on attempt {attempt + 1}/{max_retries}: {e}", exc_info=True)

        if attempt < max_retries - 1:
            time.sleep(config.API_CALL_DELAY_SECONDS) # Wait before next retry

    logger.error("Failed to generate image after multiple retries.")
    return b""
