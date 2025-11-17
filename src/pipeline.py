import time
import pathlib
from bs4 import BeautifulSoup

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
from src.pipeline_steps.generate_insta_caption import generate_insta_caption
from src import config
from src.models import SingleArticle
from src.utils import sanitize_filename

def load_articles_from_disk(pdf_filepath: pathlib.Path, logger) -> list[SingleArticle]:
    """Loads articles from disk if they already exist."""
    articles_dir = config.PROJECT_ROOT / config.ARTICLES_DIR_NAME
    sane_pdf_name = sanitize_filename(pdf_filepath.stem)
    existing_articles_paths = list(articles_dir.glob(f"{sane_pdf_name}*.html"))
    
    articles = []
    for article_path in existing_articles_paths:
        try:
            with open(article_path, "r", encoding="utf-8") as f:
                soup = BeautifulSoup(f, "html.parser")
                headline_tag = soup.find("h1")
                if headline_tag:
                    headline = headline_tag.get_text(strip=True)
                    # Remove the headline from the content
                    headline_tag.decompose()
                    content = str(soup)
                    articles.append(SingleArticle(ueberschrift=headline, inhalt=content))
                else:
                    logger.warning(f"Could not find a headline in {article_path}, skipping.")
        except Exception as e:
            logger.error(f"Error loading article from {article_path}: {e}", exc_info=True)
            
    return articles

def run_pipeline(selected_steps: list[str] | None = None):
    """The main pipeline function."""
    logger = setup_logger()
    
    # --- Step selection ---
    run_all = selected_steps is None
    if run_all:
        run_generate_articles = True
        run_generate_image_prompt = True
        run_generate_image = True
        run_create_insta_images = True
        run_generate_insta_caption = True
    else:
        assert selected_steps is not None
        # Determine which parts of the main pipeline to run based on selection
        run_generate_articles = any(s in selected_steps for s in ["Generate articles", "Generate image prompt", "Generate image"])
        run_generate_image_prompt = any(s in selected_steps for s in ["Generate image prompt", "Generate image"])
        run_generate_image = "Generate image" in selected_steps
        run_create_insta_images = "Create Instagram images" in selected_steps
        run_generate_insta_caption = "Generate Instagram captions" in selected_steps

    try:
        # --- Main pipeline ---
        if run_generate_articles:
            pdf_files = find_pdf_files(logger)
            if not pdf_files:
                logger.info("No PDF files found.")
                # Still need to check if we should run other steps
                if not run_create_insta_images and not run_generate_insta_caption:
                    return

            for pdf_filepath in pdf_files:
                logger.info(f"--- Starting pipeline for {pdf_filepath.name} ---")

                articles_exist, images_exist = check_existing_articles(pdf_filepath, logger)

                if articles_exist and images_exist:
                    continue

                articles = []
                if articles_exist and not images_exist:
                    logger.info(f"Articles for '{pdf_filepath.name}' exist, but images are missing. Generating only images.")
                    articles = load_articles_from_disk(pdf_filepath, logger)
                    if not articles:
                        logger.error(f"Failed to load articles for '{pdf_filepath.name}'. Skipping.")
                        continue
                else:
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
                    # Check which articles need images
                    images_dir = config.PROJECT_ROOT / config.IMAGES_DIR_NAME
                    articles_dir = config.PROJECT_ROOT / config.ARTICLES_DIR_NAME
                    articles_to_process = []
                    for article in articles:
                        sane_pdf_name = sanitize_filename(pdf_filepath.stem)
                        sane_headline = sanitize_filename(article.ueberschrift)
                        short_headline = "_".join(sane_headline.split('-')[:5])
                        if not short_headline: short_headline = "article"
                        base_filename = f"{sane_pdf_name}_{short_headline}"
                        
                        # This logic needs to be kept in sync with save_article to correctly find the html file
                        html_filepath = articles_dir / f"{base_filename}.html"
                        counter = 1
                        while not html_filepath.exists() and counter < 100: # Safety break
                            html_filepath = articles_dir / f"{base_filename}_{counter}.html"
                            counter += 1
                        
                        image_filepath_png = images_dir / f"{html_filepath.stem}.png"
                        image_filepath_jpg = images_dir / f"{html_filepath.stem}.jpg"

                        if not image_filepath_png.exists() and not image_filepath_jpg.exists():
                            articles_to_process.append(article)
                        else:
                            logger.info(f"Image for article '{article.ueberschrift}' already exists. Skipping image generation.")


                    for article in articles_to_process:
                        image_prompt = generate_image_prompt(article, logger)
                        if not image_prompt:
                            logger.warning(f"Image prompt generation failed for article: '{article.ueberschrift}'.")
                        elif run_generate_image:
                            image_bytes = generate_image(image_prompt, logger)
                            if image_bytes:
                                save_image(image_bytes, article, pdf_filepath.name, logger)
                        
                        time.sleep(config.API_CALL_DELAY_SECONDS)

                logger.info(f"--- Finished pipeline for {pdf_filepath.name} ---")

        # --- Instagram specific steps ---
        if run_create_insta_images:
            logger.info("--- Starting Instagram image generation ---")
            create_insta_images()
            logger.info("--- Finished Instagram image generation ---")

        if run_generate_insta_caption:
            logger.info("--- Starting Instagram caption generation ---")
            articles_dir = config.PROJECT_ROOT / config.ARTICLES_DIR_NAME
            article_files = list(articles_dir.glob('*.html'))

            if not article_files:
                logger.warning("No article files found to generate captions for.")
            else:
                for article_path in article_files:
                    try:
                        with open(article_path, "r", encoding="utf-8") as f:
                            # Use BeautifulSoup to get the full text content
                            soup = BeautifulSoup(f, "html.parser")
                            article_content = soup.get_text(separator=" ", strip=True)
                        
                        generate_insta_caption(article_content, article_path.stem, logger)
                        time.sleep(config.API_CALL_DELAY_SECONDS) # Be respectful to the API

                    except Exception as e:
                        logger.error(f"Failed to process article {article_path.name} for caption generation: {e}", exc_info=True)
            logger.info("--- Finished Instagram caption generation ---")

    except Exception as e:
        logger.error(f"An unexpected error occurred in the pipeline: {e}", exc_info=True)

