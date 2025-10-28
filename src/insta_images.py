import pathlib
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from src import config
import logging
from bs4 import BeautifulSoup, Tag
import textwrap
from src.models import ArticleContent, ContentBlock

# --- Logging Configuration ---
logger = logging.getLogger("pipeline")


def extract_article_content(article_path: pathlib.Path) -> ArticleContent | None:
    """Extracts H1 and content blocks (H2/P combinations) from an HTML article file."""
    if not article_path.is_file():
        logger.warning(f"Article file not found: {article_path}")
        return None

    try:
        with open(article_path, "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f, "html.parser")

        h1_tag = soup.find("h1")
        h1_text = h1_tag.get_text(strip=True) if h1_tag else None

        content_blocks = []
        if h1_tag:
            # Get all direct siblings after h1 that are tags
            siblings = [tag for tag in h1_tag.find_next_siblings() if isinstance(tag, Tag)]
            
            i = 0
            while i < len(siblings):
                element = siblings[i]

                # Rule: h2 is directly followed by p
                if element.name == 'h2' and (i + 1) < len(siblings) and siblings[i+1].name == 'p':
                    h2_tag = element
                    p_tag = siblings[i+1]
                    content_blocks.append(ContentBlock(
                        headline=h2_tag.get_text(strip=True),
                        paragraph=p_tag.get_text(strip=True)
                    ))
                    i += 2 # Move past both h2 and p
                
                # Rule: Standalone p
                elif element.name == 'p':
                    content_blocks.append(ContentBlock(
                        paragraph=element.get_text(strip=True)
                    ))
                    i += 1
                
                # Rule: Standalone h2 (without a directly following p)
                elif element.name == 'h2':
                    content_blocks.append(ContentBlock(
                        headline=element.get_text(strip=True)
                    ))
                    i += 1
                
                # Ignore other tags
                else:
                    i += 1

        return ArticleContent(h1=h1_text, content_blocks=content_blocks)

    except Exception as e:
        logger.error(f"Error reading or parsing article file {article_path}: {e}", exc_info=True)
        return None


def create_insta_images():
    """
    Iterates through images, creates a primary image with headline, and then
    creates additional blurred images for each content block in the article.
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

        # --- Create Additional Images for Content Blocks ---
        for i, block in enumerate(article_content.content_blocks):
            part_dest_path = dest_dir / f"{image_path.stem}_part{i+1}.jpg"
            if part_dest_path.exists():
                logger.info(f"Part image already exists, skipping: {part_dest_path}")
                continue
            
            try:
                # Ensure we have the cropped image to blur
                if cropped_img is None:
                    with Image.open(image_path) as img:
                        cropped_img = crop_image_to_aspect(img, 4 / 5)

                blurred_img = cropped_img.filter(ImageFilter.GaussianBlur(radius=2))
                final_part_img = create_content_image(blurred_img, block)
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


def create_content_image(base_img: Image.Image, block: ContentBlock) -> Image.Image:
    """Creates a blurred content image with a smaller logo and text from a ContentBlock."""
    overlay = Image.new('RGBA', base_img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    img_width, img_height = base_img.size

    # --- Logo (smaller) ---
    top_gradient_height = int(img_height * 0.2) # Estimate for positioning
    draw_logo(overlay, img_height, img_width, top_gradient_height, scale=0.5)

    # --- Fonts ---
    try:
        font_path_bold = str(config.PROJECT_ROOT / "res" / "Oswald-Bold.ttf")
        h2_font_size = int(img_height * 0.04)
        p_font_size = int(img_height * 0.03)
        h2_font = ImageFont.truetype(font_path_bold, size=h2_font_size)
        p_font = ImageFont.truetype(font_path_bold, size=p_font_size)
    except IOError:
        logger.warning("Oswald-Bold.ttf not found for content image. Using default font.")
        h2_font = ImageFont.load_default()
        p_font = ImageFont.load_default()

    # --- Text Wrapping ---
    padding_x = img_width * 0.05
    available_text_width = img_width - (2 * padding_x)
    
    # Heuristic for character wrapping based on available width and font size
    h2_chars_per_line = int(available_text_width / (h2_font_size * 0.6)) if h2_font_size > 0 else 30
    p_chars_per_line = int(available_text_width / (p_font_size * 0.6)) if p_font_size > 0 else 40

    wrapped_h2 = ""
    if block.headline:
        wrapped_h2 = "\n".join(textwrap.wrap(block.headline.upper(), width=h2_chars_per_line))

    wrapped_p = ""
    if block.paragraph:
        wrapped_p = "\n".join(textwrap.wrap(block.paragraph, width=p_chars_per_line))

    # --- Calculate total text block height ---
    h2_height = 0
    p_height = 0
    fixed_h2_p_spacing = int(img_height * 0.04) # Fixed distance between h2 and p

    if wrapped_h2:
        h2_bbox = draw.multiline_textbbox((0, 0), wrapped_h2, font=h2_font, align="left")
        h2_height = h2_bbox[3] - h2_bbox[1]

    if wrapped_p:
        p_bbox = draw.multiline_textbbox((0, 0), wrapped_p, font=p_font, align="left")
        p_height = p_bbox[3] - p_bbox[1]

    # Calculate total height of the combined block (h2 + spacing + p)
    total_combined_block_height = 0
    if wrapped_h2 and wrapped_p:
        total_combined_block_height = h2_height + fixed_h2_p_spacing + p_height
    elif wrapped_h2: # Only h2
        total_combined_block_height = h2_height
    elif wrapped_p: # Only p
        total_combined_block_height = p_height

    # --- Positioning and Drawing ---
    if wrapped_h2 and wrapped_p:
        # Both h2 and p are present, treat as one block and center it.
        current_y_start_of_block = (img_height - total_combined_block_height) / 2
        
        # Position h2 at the top of this block
        current_y_h2 = current_y_start_of_block
        draw.multiline_text((padding_x, current_y_h2), wrapped_h2, font=h2_font, fill="white", align="left")
        
        # Position p below h2 with fixed spacing
        current_y_p = current_y_h2 + h2_height + fixed_h2_p_spacing
        draw.multiline_text((padding_x, current_y_p), wrapped_p, font=p_font, fill="white", align="left")

    elif wrapped_h2: # Only h2 is present, center it vertically
        current_y_h2 = (img_height - h2_height) / 2
        draw.multiline_text((padding_x, current_y_h2), wrapped_h2, font=h2_font, fill="white", align="left")

    elif wrapped_p: # Only p is present, center it vertically
        current_y_p = (img_height - p_height) / 2
        draw.multiline_text((padding_x, current_y_p), wrapped_p, font=p_font, fill="white", align="left")

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

            # For content images (smaller scale), position the logo at 2% from the top.
            if scale < 1.0: # This condition identifies content images
                bg_y = int(img_height * 0.03) # Fixed realtive from top
                top_gradient_center_y = bg_y + (bg_side // 2) # Calculate center_y from bg_y
            else: # Main image, use existing logic
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