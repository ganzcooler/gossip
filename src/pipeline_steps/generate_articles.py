import time
import logging
from typing import List
from google import genai
from google.genai import types
from src import config, prompts
from src.models import SingleArticle, LLMGeneratedArticles

def generate_articles(text: str, logger: logging.Logger) -> List[SingleArticle]:
    """Generates articles from text using a direct Google GenAI API call with retries."""
    logger.info("Generating articles...")
    max_retries = 5
    for attempt in range(max_retries):
        try:
            client = genai.Client(api_key=config.load_google_api_key())
            response = client.models.generate_content(
                model=config.GENAI_ARTICLE_GENERATION_MODEL,
                contents=prompts.GENAI_JOURNALISTIC_ARTICLE_PROMPT.replace("{PROTOCOL_TEXT}", text),
                config=types.GenerateContentConfig(
                    temperature=0.2,
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

        if attempt < max_retries - 1:
            time.sleep(config.API_CALL_DELAY_SECONDS) # Wait before next retry

    logger.error("Failed to generate articles after multiple retries.")
    return []
