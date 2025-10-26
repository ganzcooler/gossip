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

def run_pipeline(selected_steps=None):
    """The main pipeline function."""
    logger = setup_logger()

    run_all = selected_steps is None

    # Determine which parts of the main pipeline to run based on selection
    run_generate_articles = run_all or any(s in selected_steps for s in ["Generate articles", "Generate image prompt", "Generate image"])
    run_generate_image_prompt = run_all or any(s in selected_steps for s in ["Generate image prompt", "Generate image"])
    run_generate_image = run_all or "Generate image" in selected_steps
    run_create_insta_images = run_all or "Create Instagram images" in selected_steps

    try:
        if run_generate_articles:
            pdf_files = find_pdf_files(logger)
            if not pdf_files:
                logger.info("No PDF files found.")
                # Still need to check if we should run insta_images
                if not run_create_insta_images:
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

                # 2. Generate and save articles
                articles = generate_articles(extracted_text, logger)
                if not articles:
                    logger.error("Article generation failed. Skipping rest of the pipeline for this file.")
                    continue
                
                for article in articles:
                    save_article(article, pdf_filepath.name, logger)

                # 3. Generate and save images
                if run_generate_image_prompt:
                    for article in articles:
                        image_prompt = generate_image_prompt(article, logger)
                        if not image_prompt:
                            logger.warning(f"Image prompt generation failed for article: '{article.ueberschrift}'.")
                        elif run_generate_image:
                            image_bytes = generate_image(image_prompt, logger)
                            if image_bytes:
                                save_image(image_bytes, article, pdf_filepath.name, logger)
                        
                        time.sleep(config.API_CALL_DELAY_SECONDS)

                logger.info(f"--- Finished pipeline for {pdf_filepath.name} ---")

        if run_create_insta_images:
            logger.info("--- Starting Instagram image generation ---")
            create_insta_images()
            logger.info("--- Finished Instagram image generation ---")
            
    except Exception as e:
        logger.error(f"An unexpected error occurred in the pipeline: {e}", exc_info=True)
