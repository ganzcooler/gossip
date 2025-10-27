import pathlib
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from src import config
import logging
from bs4 import BeautifulSoup
import textwrap
from src.models import ArticleContent, H2Section

# --- Logging Configuration ---
logger = logging.getLogger("pipeline")


def extract_article_content(article_path: pathlib.Path) -> ArticleContent | None:
    """Extracts H1 and H2 sections from an HTML article file."""
    if not article_path.is_file():
        logger.warning(f"Article file not found: {article_path}")
        return None

    try:
        with open(article_path, "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f, "html.parser")

        h1_tag = soup.find("h1")
        h1_text = h1_tag.get_text(strip=True) if h1_tag else None

        h2_sections = []
        for h2_tag in soup.find_all("h2"):
            paragraphs = []
            for sibling in h2_tag.find_next_siblings():
                if sibling.name == "h2":
                    break
                if sibling.name == "p":
                    paragraphs.append(sibling.get_text(strip=True))
            
            if paragraphs:
                h2_sections.append(H2Section(headline=h2_tag.get_text(strip=True), paragraphs=paragraphs))

        return ArticleContent(h1=h1_text, h2_sections=h2_sections)

    except Exception as e:
        logger.error(f"Error reading or parsing article file {article_path}: {e}", exc_info=True)
        return None


def create_insta_images():
    """
    Iterates through images, creates a primary image with headline, and then
    creates additional blurred images for each H2 section in the article.
    """
    source_dir = config.PROJECT_ROOT / config.IMAGES_DIR_NAME
    dest_dir = config.PROJECT_ROOT / config.INSTA_IMAGES_DIR_NAME
    articles_dir = config.PROJECT_ROOT / config.ARTICLES_DIR_NAME

    if not source_dir.is_dir():
        logger.error(f"Source directory not found: {source_dir}")
        return

    dest_dir.mkdir(parents=True, exist_ok=True)

    image_files = list(source_dir.glob('*.jpg')) + list(source_dir.glob('*.png'))
    if not image_files:
        logger.warning(f"No JPG or PNG images found in {source_dir}")
        return

    for image_path in image_files:
        article_path = articles_dir / f"{image_path.stem}.html"
        article_content = extract_article_content(article_path)

        if not article_content or not article_content.h1:
            logger.warning(f"Skipping image {image_path.name} due to missing article or H1 headline.")
            continue

        # --- Create First (Main) Image ---
        main_dest_path = dest_dir / f"{image_path.stem}.jpg"
        cropped_img = None
        if main_dest_path.exists():
            logger.info(f"Main image already exists, skipping creation: {main_dest_path}")
        else:
            try:
                with Image.open(image_path) as img:
                    cropped_img = crop_image_to_aspect(img, 4 / 5)
                    final_img = create_main_image(cropped_img, article_content.h1)
                    final_img.convert('RGB').save(main_dest_path, 'jpeg', quality=90)
                    logger.info(f"Successfully processed and saved main image: {main_dest_path}")
            except Exception as e:
                logger.error(f"Failed to create main image for {image_path.name}: {e}", exc_info=True)
                continue

        # --- Create Additional Images for H2 Sections ---
        for i, section in enumerate(article_content.h2_sections):
            part_dest_path = dest_dir / f"{image_path.stem}_part{i+1}.jpg"
            if part_dest_path.exists():
                logger.info(f"Part image already exists, skipping: {part_dest_path}")
                continue
            
            try:
                # Ensure we have the cropped image to blur
                if cropped_img is None:
                    with Image.open(image_path) as img:
                        cropped_img = crop_image_to_aspect(img, 4 / 5)

                blurred_img = cropped_img.filter(ImageFilter.GaussianBlur(radius=20))
                final_part_img = create_part_image(blurred_img, section)
                final_part_img.convert('RGB').save(part_dest_path, 'jpeg', quality=90)
                logger.info(f"Successfully processed and saved part image: {part_dest_path}")
            except Exception as e:
                logger.error(f"Failed to create part image for {image_path.name}: {e}", exc_info=True)


def crop_image_to_aspect(img: Image.Image, target_aspect: float) -> Image.Image:
    """Crops an image to a target aspect ratio from the center."""
    width, height = img.size
    if width / height > target_aspect:
        new_width = int(height * target_aspect)
        left = (width - new_width) / 2
        right = left + new_width
        return img.crop((left, 0, right, height))
    else:
        new_height = int(width / target_aspect)
        top = (height - new_height) / 2
        bottom = top + new_height
        return img.crop((0, top, width, bottom))


def create_main_image(base_img: Image.Image, text: str) -> Image.Image:
    """Creates the main, non-blurred image with gradients, logo, and headline."""
    overlay = Image.new('RGBA', base_img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    
    gradient_width, gradient_height = base_img.size
    
    # --- Gradients ---
    bottom_gradient_height = int(gradient_height * 0.4)
    for y in range(bottom_gradient_height):
        alpha = int(220 * (y / bottom_gradient_height))
        draw.line([(0, gradient_height - bottom_gradient_height + y), (gradient_width, gradient_height - bottom_gradient_height + y)], fill=(0, 0, 0, alpha))

    top_gradient_height = int(gradient_height * 0.2)
    for y in range(top_gradient_height):
        alpha = int(50 * (1 - (y / top_gradient_height)))
        draw.line([(0, y), (gradient_width, y)], fill=(0, 0, 0, alpha))

    # --- Text ---
    try:
        font_path = str(config.PROJECT_ROOT / "res" / "Oswald-Bold.ttf")
        font_size = int(base_img.height * 0.05)
        font = ImageFont.truetype(font_path, size=font_size)
    except IOError:
        logger.warning("Oswald-Bold.ttf not found for main image. Using default font.")
        font = ImageFont.load_default()

    avg_char_width = font.getlength("x") if hasattr(font, 'getlength') else font.getsize("x")[0] # type: ignore
    max_chars_per_line = int((base_img.width * 0.9) / avg_char_width) if avg_char_width > 0 else 20
    wrapped_text = "\n".join(textwrap.wrap(text.upper(), width=max_chars_per_line))

    text_bbox = draw.multiline_textbbox((0, 0), wrapped_text, font=font, align="center")
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    x = (base_img.width - text_width) / 2
    y = base_img.height - (base_img.height * 0.05) - text_height
    draw.multiline_text((x, y), wrapped_text, font=font, fill="white", align="center")

    # --- Logo ---
    draw_logo(overlay, base_img.height, base_img.width, top_gradient_height, scale=1.0)

    return Image.alpha_composite(base_img.convert('RGBA'), overlay)


def create_part_image(base_img: Image.Image, section: H2Section) -> Image.Image:
    """Creates a blurred part image with a smaller logo and H2 section text."""
    overlay = Image.new('RGBA', base_img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # --- Logo (smaller) ---
    top_gradient_height = int(base_img.height * 0.2) # Estimate for positioning
    draw_logo(overlay, base_img.height, base_img.width, top_gradient_height, scale=0.5)

    # --- Text (H2 + paragraphs) ---
    try:
        font_path_bold = str(config.PROJECT_ROOT / "res" / "Oswald-Bold.ttf")
        h2_font = ImageFont.truetype(font_path_bold, size=18)
        p_font = ImageFont.truetype(font_path_bold, size=14) # Fallback to bold
    except IOError:
        logger.warning("Oswald-Bold.ttf not found for part image. Using default font.")
        h2_font = ImageFont.load_default()
        p_font = ImageFont.load_default()

    # --- Text Wrapping ---
    avg_char_width_p = p_font.getlength("x") if hasattr(p_font, 'getlength') else p_font.getsize("x")[0] # type: ignore
    max_chars_per_line = int((base_img.width * 0.85) / avg_char_width_p) if avg_char_width_p > 0 else 30

    wrapped_h2 = "\n".join(textwrap.wrap(section.headline.upper(), width=max_chars_per_line))
    wrapped_paragraphs = "\n".join(
        ["\n".join(textwrap.wrap(p, width=max_chars_per_line)) for p in section.paragraphs]
    )

    # --- Calculate total text block height ---
    h2_bbox = draw.multiline_textbbox((0, 0), wrapped_h2, font=h2_font, align="center")
    p_bbox = draw.multiline_textbbox((0, 0), wrapped_paragraphs, font=p_font, align="center")
    
    h2_height = h2_bbox[3] - h2_bbox[1]
    p_height = p_bbox[3] - p_bbox[1]
    line_spacing = 10 # pixels
    total_height = h2_height + line_spacing + p_height

    # --- Positioning and Drawing ---
    current_y = (base_img.height - total_height) / 2

    # Draw H2
    h2_width = h2_bbox[2] - h2_bbox[0]
    h2_x = (base_img.width - h2_width) / 2
    draw.multiline_text((h2_x, current_y), wrapped_h2, font=h2_font, fill="white", align="center")

    current_y += h2_height + line_spacing

    # Draw Paragraphs
    p_width = p_bbox[2] - p_bbox[0]
    p_x = (base_img.width - p_width) / 2
    draw.multiline_text((p_x, current_y), wrapped_paragraphs, font=p_font, fill="white", align="center")

    return Image.alpha_composite(base_img.convert('RGBA'), overlay)


def draw_logo(overlay: Image.Image, img_height: int, img_width: int, top_gradient_height: int, scale: float):
    """Draws the project logo onto the overlay image."""
    try:
        logo_path = config.PROJECT_ROOT / "res" / "logo-gossip.png"
        with Image.open(logo_path).convert("RGBA") as logo_img:
            logo_side = int(img_height * 0.13 * scale)
            if logo_side == 0: return # Avoid error with zero size
            logo_img_resized = logo_img.resize((logo_side, logo_side), Image.Resampling.LANCZOS)

            padding = int(logo_side * 0.05)
            bg_side = logo_side + 2 * padding
            radius = int(bg_side * 0.2)

            bg_x = (img_width - bg_side) // 2
            top_gradient_center_y = top_gradient_height // 2
            bg_y = top_gradient_center_y - (bg_side // 2)

            draw = ImageDraw.Draw(overlay)
            draw.rounded_rectangle(
                (bg_x, bg_y, bg_x + bg_side, bg_y + bg_side),
                radius=radius,
                fill="white"
            )

            logo_x = (img_width - logo_img_resized.width) // 2
            logo_y = top_gradient_center_y - (logo_img_resized.height // 2)
            overlay.paste(logo_img_resized, (logo_x, logo_y), logo_img_resized)
    except FileNotFoundError:
        logger.warning(f"Logo file not found at {config.PROJECT_ROOT / 'res' / 'logo-gossip.png'}, skipping logo.")