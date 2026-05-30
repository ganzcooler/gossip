import pathlib
import re
import textwrap
import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter
from bs4 import BeautifulSoup, Tag

from app.core import tags as tags_module
from app.core.models import ArticleContent, ContentBlock

logger = logging.getLogger(__name__)

MAX_PARAGRAPH_LENGTH = 450


def save_jpeg(img: Image.Image, path: Path, quality: int = 95) -> None:
    """Save a PIL Image as JPEG without EXIF metadata.
    
    Args:
        img: The PIL Image to save
        path: The file path to save to
        quality: JPEG quality (default 95)
    """
    if img.mode == 'RGBA':
        background = Image.new('RGB', img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[3])
        img = background
    
    img.save(path, 'JPEG', quality=quality)


def find_tag(protocol_title: str) -> str | None:
    """Finds a tag for the protocol based on its title."""
    lower_stem = protocol_title.lower()
    for key, value in tags_module.TAGS.items():
        if key.lower() in lower_stem:
            return value.upper()
    return None


def split_text_into_chunks(text: str, max_length: int) -> list[str]:
    """Splits a text into chunks of a maximum length, trying to split at sentence endings."""
    if not text:
        return []

    chunks = []
    text = text.strip()

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

    if len(chunks) > 1:
        while len(chunks[-1]) < 160 and len(chunks) > 1:
            previous_chunk = chunks[-2]

            sentences = re.split(r'(?<=[.!?])\s+', previous_chunk)

            sentences = [s for s in sentences if s]

            if len(sentences) > 1:
                last_sentence = sentences.pop(-1)

                chunks[-2] = " ".join(sentences)

                chunks[-1] = last_sentence + " " + chunks[-1]
            else:
                break

    return chunks


def extract_article_content(html_content: str) -> ArticleContent | None:
    """Extracts H1 and content blocks (H2/P combinations) from an HTML string."""
    if not html_content:
        logger.warning("Empty HTML content provided")
        return None

    try:
        soup = BeautifulSoup(html_content, "html.parser")

        h1_tag = soup.find("h1")
        h1_text = h1_tag.get_text(strip=True) if h1_tag else None

        content_blocks = []
        if h1_tag:
            siblings = [tag for tag in h1_tag.find_next_siblings() if isinstance(tag, Tag)]

            i = 0
            while i < len(siblings):
                element = siblings[i]

                if element.name == 'h2' and (i + 1) < len(siblings) and siblings[i+1].name == 'p':
                    h2_tag = element
                    p_tag = siblings[i+1]
                    content_blocks.append(ContentBlock(
                        headline=h2_tag.get_text(strip=True),
                        paragraph=p_tag.get_text(strip=True)
                    ))
                    i += 2

                elif element.name == 'p':
                    content_blocks.append(ContentBlock(
                        paragraph=element.get_text(strip=True)
                    ))
                    i += 1

                elif element.name == 'h2':
                    content_blocks.append(ContentBlock(
                        headline=element.get_text(strip=True)
                    ))
                    i += 1

                else:
                    i += 1

        return ArticleContent(h1=h1_text, content_blocks=content_blocks)

    except Exception as e:
        logger.error(f"Error parsing HTML content: {e}", exc_info=True)
        return None


def draw_logo(overlay: Image.Image, img_height: int, img_width: int, top_gradient_height: int, scale: float, res_dir: Path):
    """Draws the project logo onto the overlay image."""
    try:
        logo_path = res_dir / "logo-gossip.png"
        with Image.open(logo_path).convert("RGBA") as logo_img:
            logo_side = int(img_height * 0.13 * scale)
            if logo_side == 0:
                return
            logo_img_resized = logo_img.resize((logo_side, logo_side), Image.Resampling.LANCZOS)

            padding = int(logo_side * 0.05)
            bg_side = logo_side + 2 * padding
            radius = int(bg_side * 0.2)

            bg_x = (img_width - bg_side) // 2

            if scale < 1.0:
                bg_y = int(img_height * 0.03)
                top_gradient_center_y = bg_y + (bg_side // 2)
            else:
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
        logger.warning(f"Logo file not found at {res_dir / 'logo-gossip.png'}, skipping logo.")


def create_main_image(base_img: Image.Image, text: str, protocol_title: str, res_dir: Path, bottom_gradient_ratio: float = 0.5, font_scale_factor: float = 1.0) -> Image.Image:
    """Creates the main image with gradients, logo, and headline."""
    overlay = Image.new('RGBA', base_img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    gradient_width, gradient_height = base_img.size

    bottom_gradient_height = int(gradient_height * bottom_gradient_ratio)
    for y in range(bottom_gradient_height):
        alpha = int(230 * (y / bottom_gradient_height))
        draw.line([(0, gradient_height - bottom_gradient_height + y), (gradient_width, gradient_height - bottom_gradient_height + y)], fill=(0, 0, 0, alpha))

    top_gradient_height = int(gradient_height * 0.2)
    for y in range(top_gradient_height):
        alpha = int(50 * (1 - (y / top_gradient_height)))
        draw.line([(0, y), (gradient_width, y)], fill=(0, 0, 0, alpha))

    draw_logo(overlay, base_img.height, base_img.width, top_gradient_height, scale=1.0, res_dir=res_dir)

    tag_text = find_tag(protocol_title)
    if tag_text:
        try:
            tag_font_path = str(res_dir / "Oswald-Bold.ttf")
            tag_font_size = int(base_img.width * 0.0375)
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

    try:
        font_path = str(res_dir / "Oswald-Bold.ttf")
        font_size = int(base_img.width * 0.0625 * font_scale_factor)
        font = ImageFont.truetype(font_path, size=font_size)
    except IOError:
        logger.warning("Oswald-Bold.ttf not found for main image. Using default font.")
        font = ImageFont.load_default()

    avg_char_width = font.getlength("x") if hasattr(font, 'getlength') else font.getsize("x")[0]
    max_chars_per_line = int((base_img.width * 0.85) / avg_char_width) if avg_char_width > 0 else 20
    wrapped_text = "\n".join(textwrap.wrap(text.upper(), width=max_chars_per_line))

    text_bbox = draw.multiline_textbbox((0, 0), wrapped_text, font=font, align="center")
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    x = (base_img.width - text_width) / 2
    y = base_img.height - (base_img.height * 0.05) - text_height
    draw.multiline_text((x, y), wrapped_text, font=font, fill="white", align="center")

    return Image.alpha_composite(base_img.convert('RGBA'), overlay)


def create_content_image(base_img: Image.Image, block: ContentBlock, res_dir: Path, center_vertically: bool = False, font_scale_factor: float = 1.0, min_top_margin_ratio: float = 0.0) -> Image.Image:
    """Creates a blurred content image with a smaller logo and text from a ContentBlock."""
    overlay = Image.new('RGBA', base_img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    img_width, img_height = base_img.size

    top_gradient_height = int(img_height * 0.2)
    draw_logo(overlay, img_height, img_width, top_gradient_height, scale=0.5, res_dir=res_dir)

    try:
        font_path_bold = str(res_dir / "Oswald-Bold.ttf")
        font_path_regular = str(res_dir / "RobotoCondensed-Regular.ttf")
        h2_font_size = int(img_width * 0.05 * font_scale_factor)
        p_font_size = int(img_width * 0.05 * font_scale_factor)
        h2_font = ImageFont.truetype(font_path_bold, size=h2_font_size)
        p_font = ImageFont.truetype(font_path_regular, size=p_font_size)
    except IOError:
        logger.warning("A font file was not found for the content image, using default font.")
        h2_font = ImageFont.load_default()
        p_font = ImageFont.load_default()

    padding_x = img_width * 0.05
    available_text_width = img_width - (2 * padding_x)

    h2_chars_per_line = int(available_text_width / (h2_font_size * 0.6)) if h2_font_size > 0 else 30
    p_chars_per_line = int(available_text_width / (p_font_size * 0.5)) if p_font_size > 0 else 40

    wrapped_h2 = ""
    if block.headline:
        wrapped_h2 = "\n".join(textwrap.wrap(block.headline.upper(), width=h2_chars_per_line))

    wrapped_p = ""
    if block.paragraph:
        sub_paragraphs = block.paragraph.split('\n\n')
        wrapped_parts = []
        for sub_p in sub_paragraphs:
            wrapped_parts.append("\n".join(textwrap.wrap(sub_p, width=p_chars_per_line)))
        wrapped_p = "\n\n".join(wrapped_parts)

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

    total_combined_block_height = 0
    if wrapped_h2 and wrapped_p:
        total_combined_block_height = h2_height + fixed_h2_p_spacing + p_height
    elif wrapped_h2:
        total_combined_block_height = h2_height
    elif wrapped_p:
        total_combined_block_height = p_height

    if center_vertically:
        block_y_start = (img_height - total_combined_block_height) // 2
        if min_top_margin_ratio > 0:
            min_y_start = int(img_height * min_top_margin_ratio)
            if block_y_start < min_y_start:
                block_y_start = min_y_start
    else:
        block_y_start = int(img_height * 0.1)
    block_x_start = padding_x

    if wrapped_h2 or wrapped_p:
        rect_padding_y = int(img_height * 0.04)
        rect_padding_x = int(img_width * 0.04)

        rect_x0 = block_x_start - rect_padding_x
        rect_y0 = block_y_start - rect_padding_y
        rect_x1 = block_x_start + max_text_width + rect_padding_x
        rect_y1 = block_y_start + total_combined_block_height + rect_padding_y

        rect_layer = Image.new('RGBA', base_img.size, (0, 0, 0, 0))
        rect_draw = ImageDraw.Draw(rect_layer)

        rect_color = (0, 0, 0, 140)
        rect_draw.rectangle(
            [(rect_x0, rect_y0), (rect_x1, rect_y1)],
            fill=rect_color
        )

        blurred_rect_layer = rect_layer.filter(ImageFilter.GaussianBlur(radius=30))

        overlay = Image.alpha_composite(overlay, blurred_rect_layer)
        draw = ImageDraw.Draw(overlay)

    if wrapped_h2 and wrapped_p:
        draw.multiline_text((block_x_start, block_y_start), wrapped_h2, font=h2_font, fill="white", align="left")

        p_y = block_y_start + h2_height + fixed_h2_p_spacing
        draw.multiline_text((block_x_start, p_y), wrapped_p, font=p_font, fill="white", align="left")

    elif wrapped_h2:
        draw.multiline_text((block_x_start, block_y_start), wrapped_h2, font=h2_font, fill="white", align="left")

    elif wrapped_p:
        draw.multiline_text((block_x_start, block_y_start), wrapped_p, font=p_font, fill="white", align="left")

    return Image.alpha_composite(base_img.convert('RGBA'), overlay)


def crop_to_4_5(img: Image.Image) -> Image.Image:
    """
    Crop an image to 4:5 aspect ratio (portrait).
    Width remains unchanged, top and bottom are cropped equally (center crop).
    """
    width, height = img.size
    target_height = int(width * 5 / 4)
    
    if target_height >= height:
        return img
    
    top_crop = (height - target_height) // 2
    bottom_crop = height - target_height - top_crop
    
    crop_box = (0, top_crop, width, height - bottom_crop)
    return img.crop(crop_box)


def instagram_images_exist(protocol_folder: Path, articles_data: list[dict]) -> bool:
    """
    Check if Instagram images already exist in the flat folder structure.
    Only checks for insta_{index}_main.jpg and insta_{index}_part{1,2,3}.jpg
    directly in the protocol_folder.
    """
    for article_data in articles_data:
        article_index = str(article_data["index"])
        
        main_path = protocol_folder / f"insta_{article_index}_main.jpg"
        if not main_path.exists():
            return False
        
        article_content = extract_article_content(article_data["content"])
        if article_content and article_content.content_blocks:
            raw_blocks = article_content.content_blocks
            processed_blocks = _process_content_blocks(raw_blocks)
            
            for block_idx in range(len(processed_blocks)):
                part_path = protocol_folder / f"insta_{article_index}_part{block_idx + 1}.jpg"
                if not part_path.exists():
                    return False
    
    return True


def _process_content_blocks(raw_blocks: list[ContentBlock]) -> list[ContentBlock]:
    """Process content blocks with merging and splitting logic."""
    processed_blocks = []
    i = 0
    while i < len(raw_blocks):
        current_block = raw_blocks[i]
        next_block = raw_blocks[i+1] if (i + 1) < len(raw_blocks) else None

        if (current_block.headline is not None and current_block.paragraph is not None and
            next_block and next_block.headline is None and next_block.paragraph is not None and
            len(current_block.paragraph) + len(next_block.paragraph) <= MAX_PARAGRAPH_LENGTH):

            merged_paragraph = current_block.paragraph + "\n\n" + next_block.paragraph
            merged_block = ContentBlock(headline=current_block.headline, paragraph=merged_paragraph)
            processed_blocks.append(merged_block)
            i += 2

        elif (current_block.headline is None and current_block.paragraph is not None and
              next_block and next_block.headline is None and next_block.paragraph is not None and
              len(current_block.paragraph) + len(next_block.paragraph) <= MAX_PARAGRAPH_LENGTH):

            merged_paragraph = current_block.paragraph + "\n\n" + next_block.paragraph
            merged_block = ContentBlock(paragraph=merged_paragraph)
            processed_blocks.append(merged_block)
            i += 2

        elif current_block.paragraph is not None and len(current_block.paragraph) > MAX_PARAGRAPH_LENGTH:
            chunks = split_text_into_chunks(current_block.paragraph, MAX_PARAGRAPH_LENGTH)

            first_chunk_block = ContentBlock(headline=current_block.headline, paragraph=chunks[0])
            processed_blocks.append(first_chunk_block)

            for chunk in chunks[1:]:
                processed_blocks.append(ContentBlock(paragraph=chunk))
            i += 1

        else:
            processed_blocks.append(current_block)
            i += 1
    
    return processed_blocks


def create_insta_images_for_protocol(
    protocol_folder: Path,
    articles_data: list[dict],
    protocol_title: str,
    res_dir: Path = None
) -> None:
    """
    Create Instagram-formatted images for all articles in a protocol folder.
    Images are saved flat in the protocol folder (no storys/ or posts/ subfolders).
    Only 4:5 post images are created - no story images (16:9) and no summary images.
    
    Caption is saved as a separate .txt file in the protocol folder.
    """
    if res_dir is None:
        res_dir = Path(__file__).parent.parent / "res"
    
    if instagram_images_exist(protocol_folder, articles_data):
        logger.info(f"Instagram images already exist in {protocol_folder}. Skipping generation.")
        return

    image_files = list(protocol_folder.glob("image_*.png")) + list(protocol_folder.glob("image_*.jpg"))

    articles_by_index = {str(article["index"]): article for article in articles_data}

    for image_path in image_files:
        try:
            article_index = str(int(image_path.stem.split("_")[1]))
        except (IndexError, ValueError):
            logger.warning(f"Could not parse article index from image filename: {image_path}")
            continue

        if article_index not in articles_by_index:
            logger.warning(f"No article data found for image: {image_path} (index: {article_index})")
            continue

        article_data = articles_by_index[article_index]
        article_content = extract_article_content(article_data["content"])

        if not article_content or not article_content.h1:
            logger.warning(f"Could not extract content from article index {article_index}")
            continue

        # Create main image (4:5) directly in protocol_folder
        main_path = protocol_folder / f"insta_{article_index}_main.jpg"
        if not main_path.exists():
            try:
                with Image.open(image_path) as img:
                    cropped_img = crop_to_4_5(img)
                    final_img = create_main_image(cropped_img, article_content.h1, protocol_title, res_dir, font_scale_factor=1.0)
                    save_jpeg(final_img, main_path, quality=95)
                    logger.debug(f"Created Instagram main image: {main_path}")
            except Exception as e:
                logger.error(f"Failed to create main Instagram image: {e}")

        # Save caption as .txt file if present and not already existing
        caption = article_data.get("caption")
        caption_path = protocol_folder / f"caption_{article_index}.txt"
        if caption and not caption_path.exists():
            try:
                caption_path.write_text(caption.strip(), encoding="utf-8")
                logger.debug(f"Saved caption file: {caption_path}")
            except Exception as e:
                logger.error(f"Failed to save caption file: {e}")

        # Process content blocks
        raw_blocks = article_content.content_blocks
        processed_blocks = _process_content_blocks(raw_blocks)

        # Create content images for each block (4:5) directly in protocol_folder
        for block_idx, block in enumerate(processed_blocks):
            part_path = protocol_folder / f"insta_{article_index}_part{block_idx+1}.jpg"
            if part_path.exists():
                continue

            try:
                with Image.open(image_path) as img:
                    cropped_img = crop_to_4_5(img)
                    blurred_img = cropped_img.filter(ImageFilter.GaussianBlur(radius=3))
                    final_part_img = create_content_image(blurred_img, block, res_dir, center_vertically=True, min_top_margin_ratio=0.0, font_scale_factor=1.0)
                    save_jpeg(final_part_img, part_path, quality=95)
                    logger.debug(f"Created Instagram part image: {part_path}")
            except Exception as e:
                logger.error(f"Failed to create part Instagram image: {e}")
