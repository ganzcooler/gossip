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
                # --- Crop to 4:5 ---
                width, height = img.size
                target_aspect = 4 / 5

                if width / height > target_aspect:
                    # Image is wider than target, crop width
                    new_width = int(height * target_aspect)
                    new_height = height
                    left = (width - new_width) / 2
                    top = 0
                    right = left + new_width
                    bottom = new_height
                else:
                    # Image is taller or same aspect ratio, crop height
                    new_width = width
                    new_height = int(width / target_aspect)
                    left = 0
                    top = (height - new_height) / 2
                    right = new_width
                    bottom = top + new_height

                cropped_img = img.crop((left, top, right, bottom))

                overlay = Image.new('RGBA', cropped_img.size, (0, 0, 0, 0))
                draw = ImageDraw.Draw(overlay)

                # --- Add Gradients ---
                gradient_width, gradient_height = cropped_img.size

                # Bottom gradient (30%)
                bottom_gradient_height = int(gradient_height * 0.3)
                for y in range(bottom_gradient_height):
                    alpha = int(200 * (y / bottom_gradient_height))
                    draw.line([(0, gradient_height - bottom_gradient_height + y), (gradient_width, gradient_height - bottom_gradient_height + y)], fill=(0, 0, 0, alpha))

                # Top gradient (20%)
                top_gradient_height = int(gradient_height * 0.2)
                for y in range(top_gradient_height):
                    alpha = int(200 * (1 - (y / top_gradient_height)))
                    draw.line([(0, y), (gradient_width, y)], fill=(0, 0, 0, alpha))

                # --- Text Styling ---
                font_color = "white"

                try:
                    font_path = config.PROJECT_ROOT / "res" / "Oswald-Regular.ttf"
                    font = ImageFont.truetype(str(font_path), size=60)
                except IOError:
                    logger.warning(f"Oswald font not found at {font_path}. Using default font.")
                    font = ImageFont.load_default()

                # --- Text Wrapping ---
                avg_char_width = font.getbbox("x")[2] if hasattr(font, 'getbbox') else font.getsize("x")[0]
                max_chars_per_line = int((cropped_img.width * 0.9) / avg_char_width)
                wrapped_text = "\n".join(textwrap.wrap(text, width=max_chars_per_line))

                # --- Text Positioning and Drawing ---
                text_bbox = draw.multiline_textbbox(
                    (0, 0), wrapped_text, font=font, align="center"
                )
                text_width = text_bbox[2] - text_bbox[0]
                text_height = text_bbox[3] - text_bbox[1]

                x = (cropped_img.width - text_width) / 2
                # Center text in the bottom gradient
                bottom_gradient_center_y = cropped_img.height - (bottom_gradient_height / 2)
                y = bottom_gradient_center_y - (text_height / 2)


                draw.multiline_text(
                    (x, y),
                    wrapped_text,
                    font=font,
                    fill=font_color,
                    align="center"
                )

                # --- Load, Scale, and Paste Logo ---
                try:
                    logo_path = config.PROJECT_ROOT / "res" / "logo-gossip.png"
                    with Image.open(logo_path).convert("RGBA") as logo_img:
                        logo_side = int(cropped_img.height * 0.05)
                        logo_img_resized = logo_img.resize((logo_side, logo_side), Image.Resampling.LANCZOS)

                        logo_x = (cropped_img.width - logo_img_resized.width) // 2
                        top_gradient_center_y = top_gradient_height // 2
                        logo_y = top_gradient_center_y - (logo_img_resized.height // 2)

                        overlay.paste(logo_img_resized, (logo_x, logo_y), logo_img_resized)
                except FileNotFoundError:
                    logger.warning(f"Logo file not found at {logo_path}, skipping logo.")

                # --- Combine and Save ---
                final_img = Image.alpha_composite(cropped_img.convert('RGBA'), overlay)
                dest_path = dest_dir / f"{image_path.stem}.jpg"
                final_img.convert('RGB').save(dest_path, 'jpeg', quality=90)
                logger.info(f"Successfully processed and saved: {dest_path}")

        except Exception as e:
            logger.error(f"Failed to process {image_path.name}: {e}", exc_info=True)
