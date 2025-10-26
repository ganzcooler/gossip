import logging
import pathlib
from src import config
from src.utils import sanitize_filename

def check_existing_articles(pdf_filepath: pathlib.Path, logger: logging.Logger) -> bool:
    """Checks if articles and images for a given PDF already exist. Returns True if they exist, False otherwise."""
    articles_dir = config.PROJECT_ROOT / config.ARTICLES_DIR_NAME
    sane_pdf_name = sanitize_filename(pdf_filepath.stem)
    existing_articles = list(articles_dir.glob(f"{sane_pdf_name}*.html"))

    if not existing_articles:
        return False

    logger.info(f"Articles for '{pdf_filepath.name}' already exist. Checking for corresponding images.")
    
    images_dir = config.PROJECT_ROOT / config.IMAGES_DIR_NAME
    all_images_exist = True
    for article_html in existing_articles:
        # The image can be .png or .jpg, so we check for both
        image_filepath_png = images_dir / f"{article_html.stem}.png"
        image_filepath_jpg = images_dir / f"{article_html.stem}.jpg"
        if not image_filepath_png.exists() and not image_filepath_jpg.exists():
            all_images_exist = False
            logger.info(f"Missing image for article: {article_html.name}. The pipeline will regenerate content for this PDF.")
            break

    if all_images_exist:
        logger.info(f"All articles and images for '{pdf_filepath.name}' already exist. Skipping.")
        return True
        
    return False
