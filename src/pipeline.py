import time

from src.insta_images import create_insta_images
from src.pipeline_steps.setup_logger import setup_logger
from src.pipeline_steps.find_pdf_files import find_pdf_files
from src.pipeline_steps.check_existing_articles import check_existing_articles
from src.pipeline_steps.extract_text import extract_text_from_pdf
from src.pipeline_steps.generate_articles import generate_articles
from src.pipeline_steps.save_article import save_article
from src.pipeline_steps.generate_image_prompt import generate_image_prompt
from src.pipeline_steps.generate_image import generate_image
from src.pipeline_steps.save_image import save_image
from src import config

def run_pipeline():
    """The main pipeline function."""
    logger = setup_logger()

    try:
        pdf_files = find_pdf_files(logger)
        if not pdf_files:
            return

        for pdf_filepath in pdf_files:
            logger.info(f"--- Starting pipeline for {pdf_filepath.name} ---")

            if check_existing_articles(pdf_filepath, logger):
                continue

            # 1. Extract text
            extracted_text = extract_text_from_pdf(pdf_filepath, logger)
            if not extracted_text:
                logger.error("Text extraction failed. Skipping rest of the pipeline for this file.")
                continue

            # 2. Generate articles
            articles = generate_articles(extracted_text, logger)
            if not articles:
                logger.error("Article generation failed. Skipping rest of the pipeline for this file.")
                continue

            # Save all articles first
            for article in articles:
                save_article(article, pdf_filepath.name, logger)

            # Then, generate images for all articles
            for article in articles:
                # 4. Generate image prompt
                image_prompt = generate_image_prompt(article, logger)
                if not image_prompt:
                    logger.warning(f"Image prompt generation failed for article: '{article.ueberschrift}'. Skipping image generation.")
                else:
                    # 5. Generate and save image
                    image_bytes = generate_image(image_prompt, logger)
                    if image_bytes:
                        save_image(image_bytes, article, pdf_filepath.name, logger)

                # API call delay
                time.sleep(config.API_CALL_DELAY_SECONDS)

            logger.info(f"--- Finished pipeline for {pdf_filepath.name} ---")

        # After processing all PDFs, create Instagram images
        logger.info("--- Starting Instagram image generation ---")
        create_insta_images()
        logger.info("--- Finished Instagram image generation ---")
    except Exception as e:
        logger.error(f"An unexpected error occurred in the pipeline: {e}", exc_info=True)
