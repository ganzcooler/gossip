import pathlib
import logging
from src import config
from src.models import SingleArticle
from src.utils import sanitize_filename

def save_image(image_bytes: bytes, article: SingleArticle, pdf_filename: str, logger: logging.Logger):
    """Saves the image as a JPG file."""
    sane_pdf_name = sanitize_filename(pathlib.Path(pdf_filename).stem)
    sane_headline = sanitize_filename(article.ueberschrift)

    # Create a unique filename for each article
    short_headline = "_".join(sane_headline.split('-')[:5])
    if not short_headline: short_headline = "article"

    base_filename = f"{sane_pdf_name}_{short_headline}"

    images_dir = config.PROJECT_ROOT / config.IMAGES_DIR_NAME
    images_dir.mkdir(parents=True, exist_ok=True)

    image_filepath = images_dir / f"{base_filename}.jpg"
    counter = 1
    while image_filepath.exists():
        image_filepath = images_dir / f"{base_filename}_{counter}.jpg"
        counter += 1

    try:
        with open(image_filepath, "wb") as f:
            f.write(image_bytes)
        logger.info(f"Saved image to: {image_filepath}")
    except IOError as e:
        logger.error(f"Error saving image to {image_filepath}: {e}", exc_info=True)
