import pathlib
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from src import config
import logging
from bs4 import BeautifulSoup, Tag
import textwrap
from src.models import ArticleContent, ContentBlock
import re
from src.tags import TAGS

MAX_PARAGRAPH_LENGTH = 450

# --- Logging Configuration ---
logger = logging.getLogger("pipeline")


def find_tag(article_stem: str) -> str | None:
    """Finds a tag for the article based on its filename."""
    lower_stem = article_stem.lower()
    for key, value in TAGS.items():
        if key.lower() in lower_stem:
            return value.upper()
    return None


def split_text_into_chunks(text: str, max_length: int) -> list[str]:
    """Splits a text into chunks of a maximum length, trying to split at sentence endings."""
    if not text:
        return []

    chunks = []
    text = text.strip()
    
    # Initial chunking logic
    while len(text) > max_length:
        split_pos = -1
        for delimiter in ['.', '?', '!']:
            pos = text.rfind(delimiter, 0, max_length)
            if pos > split_pos:
                split_pos = pos
        
        if split_pos == -1:
            split_pos = text.rfind(' ', 0, max_length)
        
        if split_pos == -1:
            split_pos = max_length - 1
        
        chunk = text[:split_pos+1].strip()
        chunks.append(chunk)
        text = text[split_pos+1:].strip()

    if text:
        chunks.append(text)
        
    # Post-processing to avoid widows
    if len(chunks) > 1:
        while len(chunks[-1]) < 160 and len(chunks) > 1:
            # Take the previous chunk
            previous_chunk = chunks[-2]
            
            # Split previous chunk into sentences
            sentences = re.split(r'(?<=[.!?])\s+', previous_chunk)
            
            # Filter out empty strings that can result from re.split
            sentences = [s for s in sentences if s]

            if len(sentences) > 1:
                # Move the last sentence
                last_sentence = sentences.pop(-1)
                
                # Re-assemble the previous chunk
                chunks[-2] = " ".join(sentences)
                
                # Prepend sentence to the last chunk
                chunks[-1] = last_sentence + " " + chunks[-1]
            else:
                # The previous chunk has only one sentence or cannot be split.
                # Stop to avoid moving the whole chunk.
                break
    
    return chunks


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
    Long paragraphs are split into multiple images.
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
                    final_img = create_main_image(cropped_img, article_content.h1, image_path.stem)
                    final_img.convert('RGB').save(main_dest_path, 'jpeg', quality=90)
                    logger.info(f"Successfully processed and saved main image: {main_dest_path}")
            except Exception as e:
                logger.error(f"Failed to create main image for {image_path.name}: {e}", exc_info=True)
                continue

        # --- Create Additional Images for Content Blocks ---
        raw_blocks = article_content.content_blocks
        processed_blocks = []
        i = 0
        while i < len(raw_blocks):
            current_block = raw_blocks[i]
            next_block = raw_blocks[i+1] if (i + 1) < len(raw_blocks) else None

            # --- MERGE 1: H2+P followed by P ---
            if (current_block.headline is not None and current_block.paragraph is not None and
                next_block and next_block.headline is None and next_block.paragraph is not None and
                len(current_block.paragraph) + len(next_block.paragraph) <= MAX_PARAGRAPH_LENGTH):

                merged_paragraph = current_block.paragraph + "\n\n" + next_block.paragraph
                merged_block = ContentBlock(headline=current_block.headline, paragraph=merged_paragraph)
                processed_blocks.append(merged_block)
                i += 2

            # --- MERGE 2: Two consecutive P's ---
            elif (current_block.headline is None and current_block.paragraph is not None and
                  next_block and next_block.headline is None and next_block.paragraph is not None and
                  len(current_block.paragraph) + len(next_block.paragraph) <= MAX_PARAGRAPH_LENGTH):

                merged_paragraph = current_block.paragraph + "\n\n" + next_block.paragraph
                merged_block = ContentBlock(paragraph=merged_paragraph)
                processed_blocks.append(merged_block)
                i += 2

            # --- SPLIT: Handle splitting long paragraphs ---
            elif current_block.paragraph is not None and len(current_block.paragraph) > MAX_PARAGRAPH_LENGTH:
                chunks = split_text_into_chunks(current_block.paragraph, MAX_PARAGRAPH_LENGTH)
                
                first_chunk_block = ContentBlock(headline=current_block.headline, paragraph=chunks[0])
                processed_blocks.append(first_chunk_block)
                
                for chunk in chunks[1:]:
                    processed_blocks.append(ContentBlock(paragraph=chunk))
                i += 1
            
            # --- DEFAULT: Keep block as is ---
            else:
                processed_blocks.append(current_block)
                i += 1

        for i, block_to_render in enumerate(processed_blocks):
            part_dest_path = dest_dir / f"{image_path.stem}_part{i+1}.jpg"
            if part_dest_path.exists():
                logger.info(f"Part image already exists, skipping: {part_dest_path}")
                continue
            
            try:
                # Ensure we have the cropped image to blur
                if cropped_img is None:
                    with Image.open(image_path) as img:
                        cropped_img = crop_image_to_aspect(img, 4 / 5)

                blurred_img = cropped_img.filter(ImageFilter.GaussianBlur(radius=3))
                final_part_img = create_content_image(blurred_img, block_to_render)
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


def create_main_image(base_img: Image.Image, text: str, article_stem: str) -> Image.Image:
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

    # --- Logo ---
    draw_logo(overlay, base_img.height, base_img.width, top_gradient_height, scale=1.0)

    # --- Tag ---
    tag_text = find_tag(article_stem)
    if tag_text:
        try:
            tag_font_path = str(config.PROJECT_ROOT / "res" / "Oswald-Bold.ttf")
            tag_font_size = int(base_img.height * 0.03)
            tag_font = ImageFont.truetype(tag_font_path, size=tag_font_size)
        except IOError:
            logger.warning("Oswald-Bold.ttf not found for tag. Using default font.")
            tag_font = ImageFont.load_default()

        tag_text_bbox = draw.textbbox((0, 0), tag_text, font=tag_font)
        tag_text_width = tag_text_bbox[2] - tag_text_bbox[0]
        tag_text_height = tag_text_bbox[3] - tag_text_bbox[1]

        rect_padding_x = int(tag_font_size * 0.8)
        rect_padding_y = int(tag_font_size * 0.4)
        
        rect_width = tag_text_width + 2 * rect_padding_x
        rect_height = tag_text_height + 2 * rect_padding_y

        # Position below logo
        logo_side = int(base_img.height * 0.13 * 1.0)
        logo_bg_padding = int(logo_side * 0.05)
        logo_bg_side = logo_side + 2 * logo_bg_padding
        top_gradient_center_y = top_gradient_height // 2
        logo_bg_y = top_gradient_center_y - (logo_bg_side // 2)
        logo_bottom_y = logo_bg_y + logo_bg_side
        
        tag_margin_top = int(base_img.height * 0.02)

        rect_x0 = (base_img.width - rect_width) / 2
        rect_y0 = logo_bottom_y + tag_margin_top
        rect_x1 = rect_x0 + rect_width
        rect_y1 = rect_y0 + rect_height

        radius = int(rect_height * 0.2)
        draw.rounded_rectangle([(rect_x0, rect_y0), (rect_x1, rect_y1)], radius=radius, fill="#137bb5")

        text_anchor_x = rect_x0 + (rect_width / 2)
        text_anchor_y = rect_y0 + (rect_height / 2)
        draw.text((text_anchor_x, text_anchor_y), tag_text, font=tag_font, fill="white", anchor="mm")

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
        font_path_regular = str(config.PROJECT_ROOT / "res" / "RobotoCondensed-Regular.ttf")
        h2_font_size = int(img_height * 0.04)
        p_font_size = int(img_height * 0.04)
        h2_font = ImageFont.truetype(font_path_bold, size=h2_font_size)
        p_font = ImageFont.truetype(font_path_regular, size=p_font_size)
    except IOError:
        logger.warning("A font file was not found for the content image, using default font.")
        h2_font = ImageFont.load_default()
        p_font = ImageFont.load_default()

    # --- Text Wrapping ---
    padding_x = img_width * 0.05
    available_text_width = img_width - (2 * padding_x)
    
    # Heuristic for character wrapping based on available width and font size
    h2_chars_per_line = int(available_text_width / (h2_font_size * 0.6)) if h2_font_size > 0 else 30
    p_chars_per_line = int(available_text_width / (p_font_size * 0.5)) if p_font_size > 0 else 40

    wrapped_h2 = ""
    if block.headline:
        wrapped_h2 = "\n".join(textwrap.wrap(block.headline.upper(), width=h2_chars_per_line))

    wrapped_p = ""
    if block.paragraph:
        # Handle potentially merged paragraphs
        sub_paragraphs = block.paragraph.split('\n\n')
        wrapped_parts = []
        for sub_p in sub_paragraphs:
            wrapped_parts.append("\n".join(textwrap.wrap(sub_p, width=p_chars_per_line)))
        wrapped_p = "\n\n".join(wrapped_parts)

    # --- Calculate total text block height and width ---
    h2_height, p_height = 0, 0
    h2_width, p_width = 0, 0
    fixed_h2_p_spacing = int(img_height * 0.04)

    if wrapped_h2:
        h2_bbox = draw.multiline_textbbox((0, 0), wrapped_h2, font=h2_font, align="left")
        h2_width = h2_bbox[2] - h2_bbox[0]
        h2_height = h2_bbox[3] - h2_bbox[1]

    if wrapped_p:
        p_bbox = draw.multiline_textbbox((0, 0), wrapped_p, font=p_font, align="left")
        p_width = p_bbox[2] - p_bbox[0]
        p_height = p_bbox[3] - p_bbox[1]

    max_text_width = max(h2_width, p_width)

    # Calculate total height of the combined block
    total_combined_block_height = 0
    if wrapped_h2 and wrapped_p:
        total_combined_block_height = h2_height + fixed_h2_p_spacing + p_height
    elif wrapped_h2:
        total_combined_block_height = h2_height
    elif wrapped_p:
        total_combined_block_height = p_height

    # --- Positioning and Drawing ---
    block_y_start = (img_height - total_combined_block_height) / 2
    block_x_start = padding_x # Align to the left with padding

    # Draw a blurred, transparent background rectangle for the text
    if wrapped_h2 or wrapped_p:
        rect_padding_y = int(img_height * 0.04)
        rect_padding_x = int(img_width * 0.04)

        rect_x0 = block_x_start - rect_padding_x
        rect_y0 = block_y_start - rect_padding_y
        rect_x1 = block_x_start + max_text_width + rect_padding_x # Adjust rect_x1 to align with left-aligned text
        rect_y1 = block_y_start + total_combined_block_height + rect_padding_y

        # Create a new layer for the rectangle
        rect_layer = Image.new('RGBA', base_img.size, (0, 0, 0, 0))
        rect_draw = ImageDraw.Draw(rect_layer)

        # Draw the rectangle with transparency
        rect_color = (0, 0, 0, 100)  # #137bb5 with opacity
        rect_draw.rectangle(
            [(rect_x0, rect_y0), (rect_x1, rect_y1)],
            fill=rect_color
        )

        # Blur the rectangle layer
        blurred_rect_layer = rect_layer.filter(ImageFilter.GaussianBlur(radius=30))

        # Composite the blurred rectangle onto the main overlay
        overlay = Image.alpha_composite(overlay, blurred_rect_layer)
        draw = ImageDraw.Draw(overlay)  # Update draw object for the new overlay

    # Position and draw the text itself, left-aligned within the centered block
    if wrapped_h2 and wrapped_p:
        # Both h2 and p are present
        draw.multiline_text((block_x_start, block_y_start), wrapped_h2, font=h2_font, fill="white", align="left")
        
        p_y = block_y_start + h2_height + fixed_h2_p_spacing
        draw.multiline_text((block_x_start, p_y), wrapped_p, font=p_font, fill="white", align="left")

    elif wrapped_h2:
        # Only h2 is present
        draw.multiline_text((block_x_start, block_y_start), wrapped_h2, font=h2_font, fill="white", align="left")

    elif wrapped_p:
        # Only p is present
        draw.multiline_text((block_x_start, block_y_start), wrapped_p, font=p_font, fill="white", align="left")

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