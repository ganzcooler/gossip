import pathlib
from PIL import Image, ImageDraw, ImageFont
from src import config
import logging
from bs4 import BeautifulSoup
import textwrap

# --- Logging Configuration ---
logger = logging.getLogger(__name__)

def get_headline_from_article(article_path: pathlib.Path) -> str:
    """Extracts the H1 headline from an HTML article file."""
    if not article_path.is_file():
        logger.warning(f"Article file not found: {article_path}")
        return None

    try:
        with open(article_path, "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f, "html.parser")

        h1_tag = soup.find("h1")
        if not h1_tag:
            logger.warning(f"No h1 tag found in: {article_path}")
            return None

        return h1_tag.get_text(strip=True)
    except Exception as e:
        logger.error(f"Error reading or parsing article file {article_path}: {e}", exc_info=True)
        return None

def create_insta_images():
    """
    Iterates through images, crops them, adds a text overlay with the headline
    from the corresponding article, and saves them.
    """
    source_dir = config.PROJECT_ROOT / config.IMAGES_DIR_NAME
    dest_dir = config.PROJECT_ROOT / config.INSTA_IMAGES_DIR_NAME
    articles_dir = config.PROJECT_ROOT / config.ARTICLES_DIR_NAME

    if not source_dir.is_dir():
        logger.error(f"Source directory not found: {source_dir}")
        return

    dest_dir.mkdir(parents=True, exist_ok=True)

    image_files = list(source_dir.glob('*.jpg'))
    if not image_files:
        logger.warning(f"No JPG images found in {source_dir}")
        return

    for image_path in image_files:
        # --- Get Headline ---
        article_path = articles_dir / f"{image_path.stem}.html"
        text = get_headline_from_article(article_path)
        if not text:
            # Warning is logged in the helper function, just skip the image
            continue

        try:
            with Image.open(image_path) as img:
                # --- Crop to 1:1 ---
                width, height = img.size
                short_side = min(width, height)
                left = (width - short_side) / 2
                top = (height - short_side) / 2
                right = (width + short_side) / 2
                bottom = (height + short_side) / 2
                cropped_img = img.crop((left, top, right, bottom))

                overlay = Image.new('RGBA', cropped_img.size, (0, 0, 0, 0))
                draw = ImageDraw.Draw(overlay)

                # --- Text Styling ---
                font_color = "#0284c7"
                stroke_color = "white"
                stroke_width = 2

                try:
                    font_path = config.PROJECT_ROOT / "res" / "Oswald-Regular.ttf"
                    font = ImageFont.truetype(str(font_path), size=40)
                except IOError:
                    logger.warning(f"Oswald font not found at {font_path}. Using default font.")
                    font = ImageFont.load_default()

                # --- Text Wrapping ---
                avg_char_width = font.getbbox("x")[2]
                max_chars_per_line = int((cropped_img.width * 0.9) / avg_char_width)
                wrapped_text = "\n".join(textwrap.wrap(text, width=max_chars_per_line))

                # --- Text Positioning and Drawing ---
                text_bbox = draw.multiline_textbbox(
                    (0, 0), wrapped_text, font=font, stroke_width=stroke_width, align="center"
                )
                text_width = text_bbox[2] - text_bbox[0]
                text_height = text_bbox[3] - text_bbox[1]

                x = (cropped_img.width - text_width) / 2
                y = cropped_img.height - text_height - 20 # 20px margin from bottom

                draw.multiline_text(
                    (x, y),
                    wrapped_text,
                    font=font,
                    fill=font_color,
                    stroke_width=stroke_width,
                    stroke_fill=stroke_color,
                    align="center"
                )

                # --- Combine and Save ---
                final_img = Image.alpha_composite(cropped_img.convert('RGBA'), overlay)
                dest_path = dest_dir / f"{image_path.stem}.jpg"
                final_img.convert('RGB').save(dest_path, 'jpeg', quality=95)
                logger.info(f"Successfully processed and saved: {dest_path}")

        except Exception as e:
            logger.error(f"Failed to process {image_path.name}: {e}", exc_info=True)
