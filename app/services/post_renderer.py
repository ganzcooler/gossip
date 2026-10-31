"""Deterministic Pillow renderer for the two post types.

The renderer owns line wrapping, fixed font sizes, text-box fit checks, and
image composition. It never shrinks fonts or truncates text. Overflow raises a
structured error so the caller can repair the semantic slide plan.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from app.core.post_models import SlideContent, SummarySlidePlan, TopicSlidePlan
from app.services.errors import TextOverflowError

logger = logging.getLogger(__name__)

CANVAS_9_16 = (1080, 1920)
CANVAS_4_5 = (1080, 1350)
PANEL_WIDTH = 540

CHARCOAL = (30, 30, 33)
CHARCOAL_2 = (38, 38, 42)
BLUE = (30, 123, 181)
ORANGE = (233, 79, 35)
ORANGE_DEEP = (201, 62, 24)
WHITE = (255, 255, 255)
WARM_GREY = (226, 223, 216)
RULE_GREY = (120, 120, 125)

MUNICIPALITY_BADGE = "GEMEINDERAT ROSDORF"

SUMMARY_FONTS = {
    "cover_headline": 86,
    "cover_kicker": 32,
    "cover_badge": 26,
    "content_number": 150,
    "content_label": 30,
    "content_headline": 62,
    "content_body": 38,
    "content_counter": 26,
}

TOPIC_FONTS = {
    "cover_headline": 80,
    "cover_kicker": 30,
    "cover_badge": 24,
    "content_number": 150,
    "content_label": 28,
    "content_headline": 54,
    "content_body": 36,
    "content_counter": 24,
}


def _font(res_dir: Path, family: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    filenames = {
        "oswald": "Oswald-Bold.ttf",
        "inter": "Inter-Regular.ttf",
        "inter_semibold": "Inter-SemiBold.ttf",
    }
    try:
        return ImageFont.truetype(str(res_dir / filenames[family]), size=size)
    except OSError:
        logger.warning("Font %s not found, using Pillow default", filenames[family])
        return ImageFont.load_default()


def _line_height(font, spacing: int = 0) -> int:
    ascent, descent = font.getmetrics()
    return ascent + descent + spacing


def _tracked_width(draw: ImageDraw.ImageDraw, text: str, font, tracking: float) -> float:
    if not text:
        return 0.0
    return sum(draw.textlength(char, font=font) for char in text) + tracking * (len(text) - 1)


def _draw_tracked_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font,
    fill,
    tracking: float = 2.0,
) -> None:
    x, y = xy
    for char in text:
        draw.text((x, y), char, font=font, fill=fill)
        x += draw.textlength(char, font=font) + tracking


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    """Width-based wrapping with real font metrics.

    Improvements over the old character-count heuristic: long words are split
    at the pixel boundary, explicit paragraph breaks survive, and a single-word
    orphan is avoided by pulling one word from the previous line.
    """
    lines: list[str] = []
    paragraphs = text.replace("\r\n", "\n").split("\n")

    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            if lines and lines[-1] != "":
                lines.append("")
            continue

        current = ""
        for word in paragraph.split():
            candidate = f"{current} {word}".strip()
            if draw.textlength(candidate, font=font) <= max_width:
                current = candidate
                continue

            if current:
                lines.append(current)

            while draw.textlength(word, font=font) > max_width:
                low, high = 1, len(word)
                while low < high:
                    mid = (low + high + 1) // 2
                    if draw.textlength(word[:mid], font=font) <= max_width:
                        low = mid
                    else:
                        high = mid - 1
                lines.append(word[:low])
                word = word[low:]

            current = word

        if current:
            lines.append(current)

    while lines and lines[-1] == "":
        lines.pop()

    if len(lines) >= 2 and len(lines[-1].split()) == 1 and len(lines[-2].split()) > 1:
        previous = lines[-2].split()
        moved = previous.pop()
        lines[-2] = " ".join(previous)
        lines[-1] = f"{moved} {lines[-1]}"

    return lines


def _fit_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    font,
    max_width: int,
    max_height: int,
    role: str,
    spacing: int,
) -> list[str]:
    lines = _wrap_text(draw, text, font, max_width)
    height = len(lines) * _line_height(font, spacing) - spacing if lines else 0
    if height > max_height:
        raise TextOverflowError(
            role=role,
            text=text,
            max_width=max_width,
            max_height=max_height,
        )
    return lines


def _draw_lines(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    xy: tuple[int, int],
    font,
    fill,
    spacing: int,
) -> int:
    x, y = xy
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += _line_height(font, spacing)
    return y


def _prepare_image(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    return ImageOps.fit(image.convert("RGB"), size, method=Image.Resampling.LANCZOS)


def _gradient(
    image: Image.Image,
    start_ratio: float,
    end_alpha: int,
    *,
    from_top: bool = False,
) -> Image.Image:
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    height = image.height
    start = max(1, int(height * start_ratio))

    if from_top:
        for y in range(start):
            alpha = int(end_alpha * (1 - y / start))
            draw.line([(0, y), (image.width, y)], fill=(0, 0, 0, alpha))
    else:
        span = max(1, height - start)
        for y in range(start, height):
            alpha = int(end_alpha * ((y - start) / span))
            draw.line([(0, y), (image.width, y)], fill=(0, 0, 0, alpha))

    return Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")


def _darken(image: Image.Image, alpha: int) -> Image.Image:
    overlay = Image.new("RGBA", image.size, (0, 0, 0, alpha))
    return Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")


def _paste_logo(base: Image.Image, res_dir: Path, xy: tuple[int, int], size: int) -> None:
    logo_path = res_dir / "logo-gossip-white.png"
    if not logo_path.exists():
        logo_path = res_dir / "logo-gossip.png"
    try:
        logo = Image.open(logo_path).convert("RGBA")
    except OSError:
        logger.warning("Logo file not found, skipping logo")
        return
    logo = logo.resize((size, size), Image.Resampling.LANCZOS)
    base.paste(logo, xy, logo)


def _draw_badge(
    draw: ImageDraw.ImageDraw,
    text: str,
    font,
    fill,
    top_right: tuple[int, int],
    *,
    padding_x: int = 22,
    padding_y: int = 12,
    tracking: float = 2.0,
) -> None:
    text_width = _tracked_width(draw, text, font, tracking)
    ascent, descent = font.getmetrics()
    rect_width = int(text_width + 2 * padding_x)
    rect_height = ascent + descent + 2 * padding_y
    x1, y0 = top_right
    x0 = x1 - rect_width
    draw.rectangle([(x0, y0), (x1, y0 + rect_height)], fill=fill)
    _draw_tracked_text(
        draw,
        (x0 + padding_x, y0 + padding_y),
        text,
        font,
        WHITE,
        tracking,
    )


def _draw_kicker(
    draw: ImageDraw.ImageDraw,
    text: str,
    font,
    fill,
    xy: tuple[int, int],
    *,
    padding_x: int = 26,
    padding_y: int = 14,
    tracking: float = 2.0,
) -> int:
    text_width = _tracked_width(draw, text, font, tracking)
    ascent, descent = font.getmetrics()
    rect_width = int(text_width + 2 * padding_x)
    rect_height = ascent + descent + 2 * padding_y
    x0, y0 = xy
    draw.rectangle([(x0, y0), (x0 + rect_width, y0 + rect_height)], fill=fill)
    _draw_tracked_text(
        draw,
        (x0 + padding_x, y0 + padding_y),
        text,
        font,
        WHITE,
        tracking,
    )
    return y0 + rect_height


def _draw_top_border(draw: ImageDraw.ImageDraw, width: int, color) -> None:
    draw.rectangle([(0, 0), (width, 10)], fill=color)


def _save_jpeg(image: Image.Image, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(path, "JPEG", quality=95)
    return path


def _summary_background(cover_image: Image.Image) -> Image.Image:
    background = _prepare_image(cover_image, CANVAS_9_16)
    background = background.filter(ImageFilter.GaussianBlur(radius=28))
    background = ImageEnhance.Brightness(background).enhance(0.42)
    return _darken(background, 80)


def render_summary_story(
    *,
    cover_image: Image.Image,
    plan: SummarySlidePlan,
    output_dir: Path,
    res_dir: Path | None = None,
) -> list[Path]:
    """Render the 9:16 summary cover and content slides."""
    res_dir = res_dir or Path(__file__).parent.parent / "res"
    paths: list[Path] = []

    paths.append(_render_summary_cover(cover_image, plan, output_dir, res_dir))

    background = _summary_background(cover_image)
    total = len(plan.slides) + 1
    for index, slide in enumerate(plan.slides, start=1):
        image = _render_summary_content(
            background,
            slide,
            slide_number=index,
            page=index + 1,
            total=total,
            res_dir=res_dir,
        )
        paths.append(_save_jpeg(image, output_dir / f"summary_slide_{index:02d}.jpg"))

    return paths


def _render_summary_cover(
    cover_image: Image.Image,
    plan: SummarySlidePlan,
    output_dir: Path,
    res_dir: Path,
) -> Path:
    image = _prepare_image(cover_image, CANVAS_9_16)
    image = _gradient(image, 0.48, 238)
    image = _gradient(image, 0.20, 90, from_top=True)
    draw = ImageDraw.Draw(image)
    _draw_top_border(draw, CANVAS_9_16[0], BLUE)

    _paste_logo(image, res_dir, (72, 250), 170)
    badge_font = _font(res_dir, "oswald", SUMMARY_FONTS["cover_badge"])
    _draw_badge(
        draw,
        MUNICIPALITY_BADGE,
        badge_font,
        BLUE,
        (CANVAS_9_16[0] - 72, 250),
    )

    kicker_font = _font(res_dir, "oswald", SUMMARY_FONTS["cover_kicker"])
    kicker_bottom = _draw_kicker(
        draw,
        plan.cover.kicker,
        kicker_font,
        BLUE,
        (72, 1160),
    )

    headline_font = _font(res_dir, "oswald", SUMMARY_FONTS["cover_headline"])
    headline_top = kicker_bottom + 34
    lines = _fit_lines(
        draw,
        plan.cover.headline,
        headline_font,
        max_width=900,
        max_height=1720 - headline_top,
        role="summary_cover_headline",
        spacing=0,
    )
    headline_bottom = _draw_lines(
        draw, lines, (90, headline_top), headline_font, WHITE, spacing=0
    )
    draw.rectangle([(48, headline_top), (62, headline_bottom)], fill=BLUE)

    return _save_jpeg(image, output_dir / "summary_cover.jpg")


def _render_summary_content(
    background: Image.Image,
    slide: SlideContent,
    *,
    slide_number: int,
    page: int,
    total: int,
    res_dir: Path,
) -> Image.Image:
    image = background.copy()
    card_box = (48, 150, 1032, 1770)
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rectangle(card_box, fill=(30, 30, 33, 242))
    image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(image)

    draw.rectangle([(48, 150), (62, 1770)], fill=BLUE)

    number_font = _font(res_dir, "oswald", SUMMARY_FONTS["content_number"])
    draw.text(
        (100, 190),
        f"{slide_number:02d}",
        font=number_font,
        fill=BLUE,
    )

    if slide.label:
        label_font = _font(res_dir, "oswald", SUMMARY_FONTS["content_label"])
        _draw_tracked_text(
            draw,
            (100, 372),
            slide.label.upper(),
            label_font,
            WHITE,
            tracking=2.0,
        )

    draw.line([(100, 436), (980, 436)], fill=RULE_GREY, width=2)

    headline_font = _font(res_dir, "oswald", SUMMARY_FONTS["content_headline"])
    headline_top = 482
    headline_lines = _fit_lines(
        draw,
        slide.headline,
        headline_font,
        max_width=880,
        max_height=3 * _line_height(headline_font, 6),
        role=f"summary_slide_{page:02d}_headline",
        spacing=0,
    )
    headline_bottom = _draw_lines(
        draw, headline_lines, (100, headline_top), headline_font, WHITE, spacing=0
    )

    body_font = _font(res_dir, "inter", SUMMARY_FONTS["content_body"])
    body_top = headline_bottom + 36
    body_lines = _fit_lines(
        draw,
        slide.body,
        body_font,
        max_width=880,
        max_height=1640 - body_top,
        role=f"summary_slide_{page:02d}_body",
        spacing=10,
    )
    _draw_lines(draw, body_lines, (100, body_top), body_font, WHITE, spacing=10)

    counter_font = _font(res_dir, "oswald", SUMMARY_FONTS["content_counter"])
    _draw_tracked_text(
        draw,
        (100, 1710),
        f"{page:02d} / {total:02d}",
        counter_font,
        BLUE,
        tracking=1.0,
    )

    _paste_logo(image, res_dir, (870, 1650), 100)
    return image


def render_topic_carousel(
    *,
    cover_image: Image.Image,
    artwork_images: list[Image.Image],
    plan: TopicSlidePlan,
    output_dir: Path,
    post_index: int,
    res_dir: Path | None = None,
) -> list[Path]:
    """Render the 4:5 cover and paired content slides for one topic post."""
    if len(artwork_images) != len(plan.pairs):
        raise ValueError(
            f"Expected {len(plan.pairs)} artworks, got {len(artwork_images)}"
        )

    res_dir = res_dir or Path(__file__).parent.parent / "res"
    paths: list[Path] = [ _render_topic_cover(cover_image, plan, output_dir, post_index, res_dir) ]

    total = len(plan.pairs) * 2 + 1
    page = 2
    slide_number = 1
    for pair, artwork in zip(plan.pairs, artwork_images):
        for side, slide in zip(("left", "right"), pair.slides):
            image = _render_topic_content(
                artwork,
                slide,
                slide_number=slide_number,
                page=page,
                total=total,
                panel_side=side,
                res_dir=res_dir,
            )
            paths.append(
                _save_jpeg(
                    image,
                    output_dir / f"topic_{post_index:02d}_slide_{slide_number:02d}.jpg",
                )
            )
            page += 1
            slide_number += 1

    return paths


def _render_topic_cover(
    cover_image: Image.Image,
    plan: TopicSlidePlan,
    output_dir: Path,
    post_index: int,
    res_dir: Path,
) -> Path:
    image = _prepare_image(cover_image, CANVAS_4_5)
    image = _gradient(image, 0.50, 238)
    image = _gradient(image, 0.18, 90, from_top=True)
    draw = ImageDraw.Draw(image)
    _draw_top_border(draw, CANVAS_4_5[0], ORANGE)

    _paste_logo(image, res_dir, (72, 100), 160)
    badge_font = _font(res_dir, "oswald", TOPIC_FONTS["cover_badge"])
    _draw_badge(
        draw,
        MUNICIPALITY_BADGE,
        badge_font,
        ORANGE,
        (CANVAS_4_5[0] - 72, 100),
    )

    kicker_font = _font(res_dir, "oswald", TOPIC_FONTS["cover_kicker"])
    kicker_bottom = _draw_kicker(
        draw,
        plan.cover.kicker,
        kicker_font,
        ORANGE,
        (72, 748),
    )

    headline_font = _font(res_dir, "oswald", TOPIC_FONTS["cover_headline"])
    headline_top = kicker_bottom + 32
    lines = _fit_lines(
        draw,
        plan.cover.headline,
        headline_font,
        max_width=900,
        max_height=4 * _line_height(headline_font, 8),
        role=f"topic_{post_index:02d}_cover_headline",
        spacing=0,
    )
    headline_bottom = _draw_lines(
        draw, lines, (90, headline_top), headline_font, WHITE, spacing=0
    )
    draw.rectangle([(48, headline_top), (62, headline_bottom)], fill=ORANGE)

    return _save_jpeg(image, output_dir / f"topic_{post_index:02d}_cover.jpg")


def _render_topic_content(
    artwork: Image.Image,
    slide: SlideContent,
    *,
    slide_number: int,
    page: int,
    total: int,
    panel_side: str,
    res_dir: Path,
) -> Image.Image:
    canvas = Image.new("RGB", CANVAS_4_5, CHARCOAL)
    artwork = _prepare_image(artwork, CANVAS_4_5)

    if panel_side == "left":
        panel_color = ORANGE
        image_half = artwork.crop((0, 0, PANEL_WIDTH, CANVAS_4_5[1]))
        canvas.paste(panel_color, (0, 0, PANEL_WIDTH, CANVAS_4_5[1]))
        canvas.paste(image_half, (PANEL_WIDTH, 0))
        text_x = 60
        panel_x = 0
        accent = WHITE
    else:
        panel_color = CHARCOAL
        image_half = artwork.crop((PANEL_WIDTH, 0, CANVAS_4_5[0], CANVAS_4_5[1]))
        canvas.paste(image_half, (0, 0))
        canvas.paste(panel_color, (PANEL_WIDTH, 0, CANVAS_4_5[0], CANVAS_4_5[1]))
        text_x = 600
        panel_x = PANEL_WIDTH
        accent = ORANGE

    draw = ImageDraw.Draw(canvas)

    number_font = _font(res_dir, "oswald", TOPIC_FONTS["content_number"])
    draw.text((text_x, 80), f"{slide_number:02d}", font=number_font, fill=accent)

    if slide.label:
        label_font = _font(res_dir, "oswald", TOPIC_FONTS["content_label"])
        _draw_tracked_text(
            draw,
            (text_x, 260),
            slide.label.upper(),
            label_font,
            accent,
            tracking=2.0,
        )

    draw.line([(text_x, 314), (text_x + 420, 314)], fill=accent, width=2)

    headline_font = _font(res_dir, "oswald", TOPIC_FONTS["content_headline"])
    headline_top = 356
    headline_lines = _fit_lines(
        draw,
        slide.headline,
        headline_font,
        max_width=420,
        max_height=4 * _line_height(headline_font, 6),
        role=f"topic_slide_{page:02d}_headline",
        spacing=0,
    )
    headline_bottom = _draw_lines(
        draw, headline_lines, (text_x, headline_top), headline_font, WHITE, spacing=0
    )

    body_font = _font(res_dir, "inter", TOPIC_FONTS["content_body"])
    body_top = headline_bottom + 30
    body_lines = _fit_lines(
        draw,
        slide.body,
        body_font,
        max_width=420,
        max_height=1120 - body_top,
        role=f"topic_slide_{page:02d}_body",
        spacing=10,
    )
    _draw_lines(draw, body_lines, (text_x, body_top), body_font, WHITE, spacing=10)

    counter_font = _font(res_dir, "oswald", TOPIC_FONTS["content_counter"])
    _draw_tracked_text(
        draw,
        (text_x, 1240),
        f"{page:02d} / {total:02d}",
        counter_font,
        accent,
        tracking=1.0,
    )

    _paste_logo(canvas, res_dir, (panel_x + PANEL_WIDTH - 110, 1150), 80)
    return canvas
