import pathlib
from PIL import Image, ImageDraw, ImageFont
from src import config
import logging

# --- Logging Configuration ---
logger = logging.getLogger(__name__)

def create_insta_images():
    """
    Iterates through images in the source directory, crops them to a 1:1 aspect ratio,
    adds a gradient and a text overlay, and saves them to the destination directory.
    """
    source_dir = config.PROJECT_ROOT / config.IMAGES_DIR_NAME
    dest_dir = config.PROJECT_ROOT / config.INSTA_IMAGES_DIR_NAME

    if not source_dir.is_dir():
        logger.error(f"Source directory not found: {source_dir}")
        return

    dest_dir.mkdir(parents=True, exist_ok=True)

    image_files = list(source_dir.glob('*.png'))
    if not image_files:
        logger.warning(f"No PNG images found in {source_dir}")
        return

    for image_path in image_files:
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

                # --- Create a transparent overlay for the text ---
                overlay = Image.new('RGBA', cropped_img.size, (0, 0, 0, 0))
                draw = ImageDraw.Draw(overlay)

                # --- Add Text ---
                text = "Hier steht eine Überschrift"
                font_color = "#0284c7"
                stroke_color = "white"
                stroke_width = 2  # A thin stroke

                try:
                    font = ImageFont.truetype("Oswald-Regular.ttf", size=40)
                except IOError:
                    logger.warning("Oswald font not found. Using default font.")
                    font = ImageFont.load_default()

                # Calculate text size including the stroke
                text_bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
                text_width = text_bbox[2] - text_bbox[0]
                text_height = text_bbox[3] - text_bbox[1]

                # Center the text horizontally
                text_x = (cropped_img.width - text_width) / 2

                # Position the text at the bottom with a margin
                margin = 20
                text_y = cropped_img.height - text_height - margin

                # Draw the text with an outline
                draw.text(
                    (text_x, text_y),
                    text,
                    font=font,
                    fill=font_color,
                    stroke_width=stroke_width,
                    stroke_fill=stroke_color
                )

                # --- Combine Image and Overlay ---
                final_img = Image.alpha_composite(cropped_img.convert('RGBA'), overlay)

                # --- Save as JPG ---
                dest_path = dest_dir / f"{image_path.stem}.jpg"
                final_img.convert('RGB').save(dest_path, 'jpeg', quality=95)
                logger.info(f"Successfully processed and saved: {dest_path}")

        except Exception as e:
            logger.error(f"Failed to process {image_path.name}: {e}", exc_info=True)
