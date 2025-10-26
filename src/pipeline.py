import time
import logging
import sys

from src import config
from src.insta_images import create_insta_images
from src.utils import sanitize_filename
from src.pipeline_steps.extract_text import extract_text_from_pdf
from src.pipeline_steps.generate_articles import generate_articles
from src.pipeline_steps.save_article import save_article
from src.pipeline_steps.generate_image_prompt import generate_image_prompt
from src.pipeline_steps.generate_image import generate_image
from src.pipeline_steps.save_image import save_image

def run_pipeline(insta_only=False):
    """The main pipeline function."""
    log_dir = config.PROJECT_ROOT / config.LOG_DIR_NAME
    log_dir.mkdir(parents=True, exist_ok=True)
    log_filepath = log_dir / config.get_log_filename()

    # Set up a logger for the entire run
    logger = logging.getLogger("pipeline")
    logger.setLevel(logging.INFO)

    # Remove existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Add a file handler
    fh = logging.FileHandler(log_filepath, encoding="utf-8")
    fh.setFormatter(logging.Formatter(config.LOG_FORMAT))
    logger.addHandler(fh)

    # Also add a stream handler to see logs in the console
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(logging.Formatter(config.LOG_FORMAT))
    logger.addHandler(sh)

    if insta_only:
        logger.info("--- Starting Instagram image generation only ---")
        create_insta_images()
        logger.info("--- Finished Instagram image generation ---")
        return

    try:
        pdf_dir = config.PROJECT_ROOT / config.PDF_DIR_NAME
        if not pdf_dir.is_dir():
            logger.error(f"PDF directory not found: {pdf_dir}")
            return

        pdf_files = list(pdf_dir.glob('*.pdf'))
        if not pdf_files:
            logger.warning(f"No PDF files found in {pdf_dir}")
            return

        for pdf_filepath in pdf_files:
            logger.info(f"--- Starting pipeline for {pdf_filepath.name} ---")

            # Check if articles for this PDF already exist
            articles_dir = config.PROJECT_ROOT / config.ARTICLES_DIR_NAME
            sane_pdf_name = sanitize_filename(pdf_filepath.stem)
            existing_articles = list(articles_dir.glob(f"{sane_pdf_name}*.html"))

            if existing_articles:
                logger.info(f"Articles for '{pdf_filepath.name}' already exist. Checking for images.")
                # Check if images for all articles exist
                images_dir = config.PROJECT_ROOT / config.IMAGES_DIR_NAME
                all_images_exist = True
                for article_html in existing_articles:
                    image_filepath = images_dir / f"{article_html.stem}.png"
                    if not image_filepath.exists():
                        all_images_exist = False
                        break

                if all_images_exist:
                    logger.info(f"All articles and images for '{pdf_filepath.name}' already exist. Skipping.")
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