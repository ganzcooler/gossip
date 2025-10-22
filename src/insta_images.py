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

    jpg_files = list(source_dir.glob('*.jpg'))
    png_files = list(source_dir.glob('*.png'))
    image_files = jpg_files + png_files
    if not image_files:
        logger.warning(f"No JPG or PNG images found in {source_dir}")
        return

    for image_path in image_files:
        # --- Check if image already exists ---
        dest_path = dest_dir / f"{image_path.stem}.jpg"
        if dest_path.exists():
            logger.info(f"Image already exists, skipping: {dest_path}")
            continue

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

                # Bottom gradient
                bottom_gradient_height = int(gradient_height * 0.4)
                for y in range(bottom_gradient_height):
                    alpha = int(220 * (y / bottom_gradient_height))
                    draw.line([(0, gradient_height - bottom_gradient_height + y), (gradient_width, gradient_height - bottom_gradient_height + y)], fill=(0, 0, 0, alpha))

                # Top gradient
                top_gradient_height = int(gradient_height * 0.2)
                for y in range(top_gradient_height):
                    alpha = int(50 * (1 - (y / top_gradient_height)))
                    draw.line([(0, y), (gradient_width, y)], fill=(0, 0, 0, alpha))

                # --- Text Styling ---
                font_color = "white"

                try:
                    font_path = config.PROJECT_ROOT / "res" / "Oswald-Bold.ttf"
                    font_size = int(cropped_img.height * 0.05)  # relative to image height
                    font = ImageFont.truetype(str(font_path), size=font_size)
                except IOError:
                    logger.warning(f"Desired font not found at {font_path}. Using default font.")
                    font = ImageFont.load_default()

                # --- Text Wrapping ---
                avg_char_width = font.getbbox("x")[2] if hasattr(font, 'getbbox') else font.getsize("x")[0]
                max_chars_per_line = int((cropped_img.width * 0.9) / avg_char_width)
                wrapped_text = "\n".join(textwrap.wrap(text.upper(), width=max_chars_per_line))

                # --- Text Positioning and Drawing ---
                text_bbox = draw.multiline_textbbox(
                    (0, 0), wrapped_text, font=font, align="center"
                )
                text_width = text_bbox[2] - text_bbox[0]
                text_height = text_bbox[3] - text_bbox[1]

                x = (cropped_img.width - text_width) / 2

                # Position text from bottom of image
                y = cropped_img.height - (cropped_img.height * 0.05) - text_height


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
                        logo_side = int(cropped_img.height * 0.13)
                        logo_img_resized = logo_img.resize((logo_side, logo_side), Image.Resampling.LANCZOS)

                        # --- Create Rounded White Background for Logo ---
                        padding = int(logo_side * 0.05) # Make padding a bit larger
                        bg_side = logo_side + 2 * padding
                        radius = int(bg_side * 0.2) # For a rounded square

                        # Calculate position for the background
                        bg_x = (cropped_img.width - bg_side) // 2
                        top_gradient_center_y = top_gradient_height // 2
                        bg_y = top_gradient_center_y - (bg_side // 2)

                        # Draw the white background on the overlay
                        draw.rounded_rectangle(
                            (bg_x, bg_y, bg_x + bg_side, bg_y + bg_side),
                            radius=radius,
                            fill="white"
                        )

                        # --- Paste Logo on top of the background ---
                        logo_x = (cropped_img.width - logo_img_resized.width) // 2
                        logo_y = top_gradient_center_y - (logo_img_resized.height // 2)

                        overlay.paste(logo_img_resized, (logo_x, logo_y), logo_img_resized)
                except FileNotFoundError:
                    logger.warning(f"Logo file not found at {logo_path}, skipping logo.")

                # --- Combine and Save ---
                final_img = Image.alpha_composite(cropped_img.convert('RGBA'), overlay)
                final_img.convert('RGB').save(dest_path, 'jpeg', quality=90)
                logger.info(f"Successfully processed and saved: {dest_path}")

        except Exception as e:
            logger.error(f"Failed to process {image_path.name}: {e}", exc_info=True)
