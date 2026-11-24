"""Shared brand and Pillow primitives for the Summary and topic renderers.

This module is the single source of the brand palette and render tokens.
Everything here is deterministic and side-effect free until a caller writes a
file. The logo is cropped to its alpha ink and composited unchanged: the current
asset carries its own white rounded plate and transparent corners, and the
renderer never adds a plate, padding, radius, shadow or glow (see ADR 0011).
"""

from __future__ import annotations

import math
from datetime import date
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw

from app.services import text_layout
from app.utils.folder_utils import ensure_protocol_folder

RESOURCE_DIR = text_layout.RESOURCE_DIR
FONT_PATHS: dict[str, Path] = {
    "oswald": text_layout.OSWALD_PATH,
    "inter": text_layout.INTER_PATH,
}
LOGO_PATH = RESOURCE_DIR / "gossip-logo-weiss-bgr.png"

SURFACE_BASE = (30, 30, 33)
SURFACE_SUNKEN = (23, 23, 26)
ON_SURFACE = (255, 255, 255)
ON_SURFACE_MUTED = (226, 223, 216)
OUTLINE = (70, 70, 75)
BRAND_BLUE = (30, 123, 181)
BRAND_BLUE_DEEP = (21, 90, 133)
BRAND_ORANGE = (233, 79, 35)
BRAND_ORANGE_DEEP = (201, 62, 24)

UI_RADIUS = 10
UI_SUPERSAMPLE = 4

# Safe-area anchors in image pixels. Summary frames are 1080x1920, topic
# frames 1080x1350. The composers and renderers derive their module constants
# from these tokens so the two Beitrag families cannot drift apart.
SUMMARY_LOGO_TOP = 240
SUMMARY_BADGE_TOP = 260
SUMMARY_CARD_TOP = 420
SUMMARY_CARD_BOTTOM = 1720
SUMMARY_CARD_NUMBER_TOP = 460
SUMMARY_CARD_KICKER_TOP = 606
SUMMARY_CARD_RULE_TOP = 651
SUMMARY_CARD_HEADING_TOP = 678
SUMMARY_CARD_BODY_BOTTOM = 1640
SUMMARY_CARD_PAGE_TOP = 1670
SUMMARY_COVER_TITLE_BOTTOM = 1720

TOPIC_COVER_SAFE_TOP = 105
TOPIC_COVER_LOGO_TOP = 120
TOPIC_COVER_BADGE_TOP = 130
TOPIC_COVER_TITLE_BOTTOM = 1240
TOPIC_COVER_SAFE_BOTTOM = 1255
TOPIC_CONTENT_TOP = 74
TOPIC_HEADING_KICKER_TOP = 194
TOPIC_HEADING_RULE_TOP = 236
TOPIC_H2_TOP = 263
TOPIC_H2_BODY_GAP = 24
TOPIC_BODY_BOTTOM = 1140
TOPIC_FOLLOW_BODY_TOP = 136
TOPIC_FOOTER_LOGO_TOP = 1150

COVER_SCRIM_STOPS = (
    (0.00, 0.00),
    (0.40, 0.00),
    (0.47, 0.20),
    (0.55, 0.52),
    (0.62, 0.72),
    (0.78, 0.88),
    (1.00, 0.94),
)
MIN_TITLE_CONTRAST = 4.5


class RenderError(Exception):
    """A Beitrag cannot be rendered without dropping or changing content."""


def font(family: str, size: int, weight: int = 700):
    """Load a runtime font, failing loudly when its asset is missing."""
    try:
        path = Path(FONT_PATHS[family])
    except KeyError:
        raise RenderError(f"Unknown font family {family!r}") from None
    if not path.is_file():
        raise RenderError(f"Missing renderer font: {path}")
    try:
        return text_layout.load_font(path, size, weight)
    except OSError as exc:
        raise RenderError(f"Could not load renderer font {path}: {exc}") from exc


def text_advance(font, text: str, tracking: float = 0.0) -> float:
    """Return the advance width of ``text`` with tracking between glyphs."""
    if not text:
        return 0.0
    if tracking == 0:
        return font.getlength(text)
    return sum(font.getlength(character) for character in text) + tracking * (
        len(text) - 1
    )


def draw_tracked_text(
    draw: ImageDraw.ImageDraw,
    position: tuple[float, float],
    text: str,
    *,
    font,
    fill,
    tracking: float = 0.0,
    anchor: str = "la",
) -> float:
    """Draw one line glyph by glyph and return its advance width.

    Pillow has no letter-spacing parameter, so the exact design tracking is
    applied between characters. Untracked lines are drawn in one call to keep
    kerning; only left-anchored horizontal anchors are needed by the renderers.
    """
    x, y = position
    if tracking == 0:
        draw.text((x, y), text, font=font, fill=fill, anchor=anchor)
        return font.getlength(text)
    cursor = x
    for character in text:
        draw.text((cursor, y), character, font=font, fill=fill, anchor=anchor)
        cursor += font.getlength(character) + tracking
    return text_advance(font, text, tracking)


def ui_radius(width: int, height: int, maximum: int = UI_RADIUS) -> int:
    """Clamp the UI radius so narrow shapes never become pills."""
    return max(0, min(maximum, width // 2, height // 2))


@lru_cache(maxsize=None)
def _ui_mask(width: int, height: int, radius: int) -> Image.Image:
    scale = UI_SUPERSAMPLE
    mask = Image.new("L", (width * scale, height * scale), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle(
        (0, 0, width * scale - 1, height * scale - 1),
        radius=radius * scale,
        fill=255,
    )
    return mask.resize((width, height), Image.Resampling.LANCZOS)


def rounded_ui_mask(
    width: int, height: int, maximum: int = UI_RADIUS
) -> Image.Image:
    """Return the anti-aliased mask of one clamped rounded UI rectangle."""
    return _ui_mask(width, height, ui_radius(width, height, maximum))


def draw_ui_rect(
    canvas: Image.Image,
    box: tuple[int, int, int, int],
    *,
    fill,
    maximum: int = UI_RADIUS,
) -> tuple[int, int, int, int]:
    """Fill a rounded UI rectangle whose radius is clamped per shape."""
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    if width <= 0 or height <= 0:
        raise RenderError(f"UI rectangle has an empty box: {box!r}")
    canvas.paste(fill, (x0, y0), rounded_ui_mask(width, height, maximum))
    return (x0, y0, x1, y1)


def _load_logo(path: str) -> Image.Image:
    logo_path = Path(path)
    if not logo_path.is_file():
        raise RenderError(f"Missing renderer logo: {logo_path}")
    try:
        with Image.open(logo_path) as image:
            logo = image.convert("RGBA")
    except OSError as exc:
        raise RenderError(f"Could not load renderer logo {logo_path}: {exc}") from exc
    bbox = logo.getchannel("A").getbbox()
    if bbox is None:
        raise RenderError(f"Renderer logo has no visible pixels: {logo_path}")
    return logo.crop(bbox)


@lru_cache(maxsize=None)
def _cropped_logo(path: str) -> Image.Image:
    return _load_logo(path)


@lru_cache(maxsize=None)
def _scaled_logo(path: str, width: int) -> Image.Image:
    logo = _cropped_logo(path)
    height = max(1, round(width * logo.height / logo.width))
    # Resize premultiplied so transparent edge pixels do not darken the ink.
    return (
        logo.convert("RGBa")
        .resize((width, height), Image.Resampling.LANCZOS)
        .convert("RGBA")
    )


def logo_size(logo_width: int) -> tuple[int, int]:
    """Return the rendered logo ink size for a requested width."""
    logo = _cropped_logo(str(LOGO_PATH))
    height = max(1, round(logo_width * logo.height / logo.width))
    return (logo_width, height)


def draw_logo(
    canvas: Image.Image, x: int, y: int, logo_width: int
) -> tuple[int, int, int, int]:
    """Composite the logo at its ink anchor and return the box."""
    if canvas.mode != "RGB":
        raise RenderError("The logo must be drawn on an RGB canvas")
    logo = _scaled_logo(str(LOGO_PATH), logo_width)
    canvas.paste(logo, (x, y), logo)
    return (x, y, x + logo.width, y + logo.height)


def _interpolate_scrim_alpha(t: float) -> float:
    stops = COVER_SCRIM_STOPS
    if t <= stops[0][0]:
        return stops[0][1]
    for (start, start_alpha), (end, end_alpha) in zip(stops, stops[1:]):
        if t <= end:
            span = end - start
            ratio = 0.0 if span == 0 else (t - start) / span
            return start_alpha + (end_alpha - start_alpha) * ratio
    return stops[-1][1]


def apply_cover_scrim(image: Image.Image) -> Image.Image:
    """Composite the vertical charcoal cover scrim over a full-bleed image."""
    source = image.convert("RGB")
    width, height = source.size
    alpha = Image.new("L", (1, height))
    denominator = max(1, height - 1)
    for y in range(height):
        value = _interpolate_scrim_alpha(y / denominator)
        alpha.putpixel((0, y), round(value * 255))
    mask = alpha.resize((width, height), Image.Resampling.NEAREST)
    overlay = Image.new("RGB", source.size, SURFACE_SUNKEN)
    return Image.composite(overlay, source, mask)


def _relative_luminance(red: int, green: int, blue: int) -> float:
    def channel(value: int) -> float:
        normalized = value / 255
        if normalized <= 0.04045:
            return normalized / 12.92
        return ((normalized + 0.055) / 1.055) ** 2.4

    return (
        0.2126 * channel(red)
        + 0.7152 * channel(green)
        + 0.0722 * channel(blue)
    )


def _white_contrast(red: int, green: int, blue: int) -> float:
    return 1.05 / (_relative_luminance(red, green, blue) + 0.05)


def _clamp_box(box: tuple[int, int, int, int], size: tuple[int, int]):
    width, height = size
    x0, y0, x1, y1 = box
    return (
        max(0, min(width, x0)),
        max(0, min(height, y0)),
        max(0, min(width, x1)),
        max(0, min(height, y1)),
    )


def ensure_title_contrast(
    image: Image.Image, ink_bbox: tuple[int, int, int, int]
) -> Image.Image:
    """Fail the render when white title text misses 4.5:1 on the cover scrim.

    The check uses a worst-case white artwork instead of the actual image, so a
    dark photo cannot hide a scrim that is too weak for a bright one. It never
    changes the image: the single bottom-up scrim is the only darkening.
    """
    box = _clamp_box(
        (ink_bbox[0] - 8, ink_bbox[1] - 8, ink_bbox[2] + 8, ink_bbox[3] + 8),
        image.size,
    )
    if box[2] <= box[0] or box[3] <= box[1]:
        raise RenderError("Cover title contrast box is empty")

    white_art = Image.new("RGB", image.size, ON_SURFACE)
    extrema = apply_cover_scrim(white_art).crop(box).getextrema()
    contrast = _white_contrast(
        extrema[0][1], extrema[1][1], extrema[2][1]
    )
    if contrast < MIN_TITLE_CONTRAST:
        raise RenderError(
            f"Cover title contrast {contrast:.2f}:1 is below "
            f"{MIN_TITLE_CONTRAST:g}:1 against a white image"
        )
    return image


def draw_organ_badge(
    canvas: Image.Image,
    organ: str,
    *,
    top: int = 300,
    fill=BRAND_BLUE,
) -> tuple:
    """Draw the right-aligned official Organ badge."""
    text = organ.strip().upper()
    if not text:
        raise RenderError("Cannot render an empty Organ badge")
    badge_font = font("inter", 24, 700)
    tracking = 4
    width = math.ceil(text_advance(badge_font, text, tracking)) + 36
    height = 62
    right = 1016
    left = right - width
    draw = ImageDraw.Draw(canvas)
    draw_ui_rect(canvas, (left, top, right, top + height), fill=fill)
    draw_tracked_text(
        draw,
        (left + 18, top + height / 2),
        text,
        font=badge_font,
        fill=ON_SURFACE,
        tracking=tracking,
        anchor="lm",
    )
    return (left, top, right, top + height)


def draw_kicker_block(
    canvas: Image.Image,
    text: str,
    *,
    x: int,
    y: int,
    fill=BRAND_BLUE,
) -> tuple[int, int, int, int]:
    """Draw the solid one-line kicker block with tracked Oswald text."""
    label = text.strip().upper()
    if not label:
        raise RenderError("Cannot render an empty kicker block")
    kicker_font = font("oswald", 40, 600)
    tracking = 6
    width = math.ceil(text_advance(kicker_font, label, tracking)) + 36
    height = 64
    draw = ImageDraw.Draw(canvas)
    draw_ui_rect(canvas, (x, y, x + width, y + height), fill=fill)
    draw_tracked_text(
        draw,
        (x + 18, y + height / 2),
        label,
        font=kicker_font,
        fill=ON_SURFACE,
        tracking=tracking,
        anchor="lm",
    )
    return (x, y, x + width, y + height)


def protocol_output_folder(
    output_dir: Path | str, session_date: date, title: str
) -> Path:
    """Create or reuse the ``YYMMDD_<normalized title>`` protocol folder."""
    return ensure_protocol_folder(Path(output_dir), session_date, title)


def write_caption_file(
    folder: Path, *, post_type: str, slug: str, caption: str
) -> Path:
    """Write the one caption file for a Beitrag."""
    if not caption or not caption.strip():
        raise RenderError("A post caption is required to write the caption file")
    path = folder / f"caption-{post_type}-{slug}.txt"
    path.write_text(caption, encoding="utf-8")
    return path


__all__ = [
    "BRAND_BLUE",
    "BRAND_BLUE_DEEP",
    "BRAND_ORANGE",
    "BRAND_ORANGE_DEEP",
    "COVER_SCRIM_STOPS",
    "FONT_PATHS",
    "LOGO_PATH",
    "MIN_TITLE_CONTRAST",
    "ON_SURFACE",
    "ON_SURFACE_MUTED",
    "OUTLINE",
    "RESOURCE_DIR",
    "RenderError",
    "SUMMARY_BADGE_TOP",
    "SUMMARY_CARD_BODY_BOTTOM",
    "SUMMARY_CARD_BOTTOM",
    "SUMMARY_CARD_HEADING_TOP",
    "SUMMARY_CARD_KICKER_TOP",
    "SUMMARY_CARD_NUMBER_TOP",
    "SUMMARY_CARD_PAGE_TOP",
    "SUMMARY_CARD_RULE_TOP",
    "SUMMARY_CARD_TOP",
    "SUMMARY_COVER_TITLE_BOTTOM",
    "SUMMARY_LOGO_TOP",
    "SURFACE_BASE",
    "SURFACE_SUNKEN",
    "TOPIC_BODY_BOTTOM",
    "TOPIC_CONTENT_TOP",
    "TOPIC_COVER_BADGE_TOP",
    "TOPIC_COVER_LOGO_TOP",
    "TOPIC_COVER_SAFE_BOTTOM",
    "TOPIC_COVER_SAFE_TOP",
    "TOPIC_COVER_TITLE_BOTTOM",
    "TOPIC_FOLLOW_BODY_TOP",
    "TOPIC_FOOTER_LOGO_TOP",
    "TOPIC_H2_BODY_GAP",
    "TOPIC_H2_TOP",
    "TOPIC_HEADING_KICKER_TOP",
    "TOPIC_HEADING_RULE_TOP",
    "UI_RADIUS",
    "apply_cover_scrim",
    "draw_kicker_block",
    "draw_logo",
    "draw_organ_badge",
    "draw_tracked_text",
    "draw_ui_rect",
    "ensure_title_contrast",
    "font",
    "logo_size",
    "protocol_output_folder",
    "rounded_ui_mask",
    "text_advance",
    "ui_radius",
    "write_caption_file",
]
