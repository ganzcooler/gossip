"""Deterministic Pillow renderer for the blue 9:16 Summary-Beitrag.

The renderer consumes the Summary composition (or its persisted equivalent)
and renders every frame in memory first. Files are written only after the whole
post rendered successfully, so a text-overflow or asset failure never leaves a
partial story in the output folder.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from app.core.post_models import SummaryDraft
from app.services.render_common import (
    BRAND_BLUE,
    ON_SURFACE,
    ON_SURFACE_MUTED,
    OUTLINE,
    RenderError,
    SURFACE_BASE,
    SURFACE_SUNKEN,
    apply_cover_scrim,
    draw_kicker_block,
    draw_logo_plate,
    draw_organ_badge,
    draw_tracked_text,
    ensure_title_contrast,
    font,
    protocol_output_folder,
    rounded_ui_mask,
    text_advance,
    write_caption_file,
)
from app.services.slide_composer import (
    CARD_BODY_BOTTOM,
    CARD_BODY_LINE_HEIGHT,
    CARD_HEADING_BODY_GAP,
    CARD_HEADING_LINE_HEIGHT,
    CARD_HEADING_MAX_HEIGHT,
    CARD_HEADING_MAX_LINES,
    CARD_HEADING_SIZES,
    CARD_TEXT_WIDTH,
    COVER_LABEL,
    COVER_TITLE_LINE_HEIGHT,
    COVER_TITLE_MAX_LINES,
    COVER_TITLE_SIZES,
    COVER_TITLE_WIDTH,
    SUMMARY_BODY_SIZES,
    ComposedSummarySlide,
    SummaryComposition,
)

logger = logging.getLogger(__name__)

SUMMARY_SIZE = (1080, 1920)
CARD_BOX = (64, 460, 1016, 1680)
CARD_EDGE_WIDTH = 10
CARD_TEXT_X = 118

COVER_LOGO_WIDTH = 300
CARD_LOGO_WIDTH = 140
COVER_TITLE_X = 64
COVER_TITLE_Y = 800
KICKER_X = 64
KICKER_Y = 720

CARD_NUMBER_POSITION = (118, 500)
CARD_KICKER_POSITION = (118, 646)
CARD_RULE_BOX = (118, 691, 918, 694)
CARD_HEADING_POSITION = (118, 718)
CARD_PAGE_POSITION = (118, 1630)

_ORGAN_BADGE_LEFT = 1016
_ORGAN_BADGE_TOP = 300
_ORGAN_BADGE_HEIGHT = 62
_LOGO_CLEAR_SPACE = 24


@dataclass(frozen=True)
class SummaryOutput:
    """The files written for one successfully rendered Summary-Beitrag."""

    folder: Path
    image_paths: list[Path]
    caption_path: Path


def summary_body_top(heading_size: int, heading_lines: int) -> float:
    """Return the body line-box top for the approved Summary card geometry."""
    return (
        CARD_HEADING_POSITION[1]
        + heading_lines * heading_size * CARD_HEADING_LINE_HEIGHT
        + CARD_HEADING_BODY_GAP
    )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RenderError(message)


def _verify_lines(
    lines: Sequence[str],
    *,
    font_family: str,
    size: int,
    weight: int,
    width: float,
    tracking: float,
    label: str,
) -> None:
    _require(bool(lines), f"{label} has no rendered lines")
    display_font = font(font_family, size, weight)
    for line in lines:
        _require(bool(line.strip()), f"{label} contains an empty line")
        advance = text_advance(display_font, line, tracking)
        _require(
            advance <= width + 0.5,
            f"{label} line overflows {width:g}px: {line!r} ({advance:.1f}px)",
        )


def _verify_cover(composition: SummaryComposition, draft: SummaryDraft) -> None:
    _require(bool(composition.slides), "Summary composition has no frames")
    cover = composition.slides[0]
    _require(
        cover.slide_type == "cover", "The first Summary frame must be the cover"
    )
    _require(
        cover.headline == draft.cover_title,
        "Summary cover title does not match the draft",
    )
    _require(
        cover.heading_size in COVER_TITLE_SIZES,
        f"Unsupported Summary cover title size: {cover.heading_size}",
    )
    _require(
        len(cover.heading_lines) <= COVER_TITLE_MAX_LINES,
        "Summary cover title exceeds three lines",
    )
    _verify_lines(
        cover.heading_lines,
        font_family="oswald",
        size=cover.heading_size,
        weight=700,
        width=COVER_TITLE_WIDTH,
        tracking=-0.005 * cover.heading_size,
        label="Summary cover title",
    )


def _verify_card(slide: ComposedSummarySlide, body_size: int) -> None:
    _require(
        slide.slide_type == "heading",
        "Summary cards must use the heading slide type",
    )
    _require(
        slide.heading_size in CARD_HEADING_SIZES,
        f"Unsupported Summary heading size: {slide.heading_size}",
    )
    _require(
        len(slide.heading_lines) <= CARD_HEADING_MAX_LINES,
        "Summary heading exceeds four lines",
    )
    _require(
        len(slide.heading_lines) * slide.heading_size * CARD_HEADING_LINE_HEIGHT
        <= CARD_HEADING_MAX_HEIGHT,
        "Summary heading exceeds the fitted 360px block",
    )
    _verify_lines(
        slide.heading_lines,
        font_family="oswald",
        size=slide.heading_size,
        weight=700,
        width=CARD_TEXT_WIDTH,
        tracking=-0.005 * slide.heading_size,
        label="Summary heading",
    )
    _require(slide.card_number is not None, "Summary card number is missing")
    _require(bool(slide.page_label), "Summary page label is missing")
    _require(
        body_size in SUMMARY_BODY_SIZES,
        f"Unsupported Summary body size: {body_size}",
    )
    _verify_lines(
        slide.body_lines,
        font_family="inter",
        size=body_size,
        weight=400,
        width=CARD_TEXT_WIDTH,
        tracking=0,
        label="Summary body",
    )
    body_bottom = summary_body_top(
        slide.heading_size, len(slide.heading_lines)
    ) + len(slide.body_lines) * body_size * CARD_BODY_LINE_HEIGHT
    _require(
        body_bottom <= CARD_BODY_BOTTOM + 0.5,
        f"Summary body overflows the card at {body_bottom:.1f}px",
    )


def _ink_bbox(
    lines: Sequence[str],
    *,
    x: int,
    y: int,
    size: int,
    line_height: float,
    weight: int,
) -> tuple[int, int, int, int]:
    display_font = font("oswald", size, weight)
    boxes = []
    for index, line in enumerate(lines):
        left, top, right, bottom = display_font.getbbox(line, anchor="la")
        line_top = y + index * line_height
        boxes.append(
            (
                int(x + left),
                int(line_top + top),
                int(x + right),
                int(line_top + bottom),
            )
        )
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _render_cover(
    composition: SummaryComposition,
    *,
    cover_art: Image.Image,
    organ: str,
) -> Image.Image:
    _require(
        cover_art.size == SUMMARY_SIZE,
        f"Summary cover art must be {SUMMARY_SIZE}, got {cover_art.size}",
    )
    cover = composition.slides[0]
    canvas = apply_cover_scrim(cover_art)

    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, SUMMARY_SIZE[0] - 1, 5), fill=BRAND_BLUE)

    logo_box = draw_logo_plate(canvas, 64, 280, COVER_LOGO_WIDTH)
    badge_box = draw_organ_badge(canvas, organ, top=_ORGAN_BADGE_TOP)
    _require(
        badge_box[0] >= logo_box[2] + _LOGO_CLEAR_SPACE,
        "Organ badge collides with the cover logo plate",
    )

    draw_kicker_block(canvas, COVER_LABEL, x=KICKER_X, y=KICKER_Y)

    title_size = cover.heading_size
    title_font = font("oswald", title_size, 700)
    title_line_height = title_size * COVER_TITLE_LINE_HEIGHT
    tracking = -0.005 * title_size
    ink_bbox = _ink_bbox(
        cover.heading_lines,
        x=COVER_TITLE_X,
        y=COVER_TITLE_Y,
        size=title_size,
        line_height=title_line_height,
        weight=700,
    )
    canvas = ensure_title_contrast(canvas, ink_bbox)
    draw = ImageDraw.Draw(canvas)
    for index, line in enumerate(cover.heading_lines):
        draw_tracked_text(
            draw,
            (COVER_TITLE_X, COVER_TITLE_Y + index * title_line_height),
            line,
            font=title_font,
            fill=ON_SURFACE,
            tracking=tracking,
            anchor="la",
        )
    return canvas


def _card_background(cover_art: Image.Image) -> Image.Image:
    background = ImageOps.fit(
        cover_art.convert("RGB"),
        (1145, 2035),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )
    background = background.filter(ImageFilter.GaussianBlur(18))
    background = ImageOps.fit(
        background,
        SUMMARY_SIZE,
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )
    tint = Image.new("RGB", SUMMARY_SIZE, SURFACE_SUNKEN)
    return Image.blend(background, tint, 0.62)


def _kicker_text(slide: ComposedSummarySlide) -> str:
    label = (slide.label or "").strip()
    if not label or len(label.split()) != 1:
        logger.warning(
            "Summary card %s has a missing or invalid kicker; using THEMA",
            slide.slide_index,
        )
        return "THEMA"
    return label.upper()


def _render_card(
    slide: ComposedSummarySlide,
    *,
    body_size: int,
    background: Image.Image,
    organ: str,
) -> Image.Image:
    canvas = background.copy()
    draw = ImageDraw.Draw(canvas)

    logo_box = draw_logo_plate(canvas, 64, 280, CARD_LOGO_WIDTH)
    badge_box = draw_organ_badge(canvas, organ, top=_ORGAN_BADGE_TOP)
    _require(
        badge_box[0] >= logo_box[2] + _LOGO_CLEAR_SPACE,
        "Organ badge collides with the card logo plate",
    )

    x0, y0, x1, y1 = CARD_BOX
    card_mask = rounded_ui_mask(x1 - x0, y1 - y0)
    canvas.paste(SURFACE_BASE, (x0, y0), card_mask)
    canvas.paste(
        BRAND_BLUE,
        (x0, y0),
        card_mask.crop((0, 0, CARD_EDGE_WIDTH, y1 - y0)),
    )

    number_font = font("oswald", 118, 700)
    draw_tracked_text(
        draw,
        CARD_NUMBER_POSITION,
        f"{slide.card_number:02d}",
        font=number_font,
        fill=BRAND_BLUE,
        tracking=0.01 * 118,
        anchor="la",
    )

    kicker_font = font("inter", 24, 700)
    draw_tracked_text(
        draw,
        CARD_KICKER_POSITION,
        _kicker_text(slide),
        font=kicker_font,
        fill=ON_SURFACE,
        tracking=4,
        anchor="la",
    )

    draw.rectangle(
        (
            CARD_RULE_BOX[0],
            CARD_RULE_BOX[1],
            CARD_RULE_BOX[2] - 1,
            CARD_RULE_BOX[3] - 1,
        ),
        fill=OUTLINE,
    )

    heading_font = font("oswald", slide.heading_size, 700)
    heading_line_height = slide.heading_size * CARD_HEADING_LINE_HEIGHT
    heading_tracking = -0.005 * slide.heading_size
    for index, line in enumerate(slide.heading_lines):
        draw_tracked_text(
            draw,
            (
                CARD_HEADING_POSITION[0],
                CARD_HEADING_POSITION[1] + index * heading_line_height,
            ),
            line,
            font=heading_font,
            fill=ON_SURFACE,
            tracking=heading_tracking,
            anchor="la",
        )

    body_font = font("inter", body_size, 400)
    body_line_height = body_size * CARD_BODY_LINE_HEIGHT
    body_top = summary_body_top(
        slide.heading_size, len(slide.heading_lines)
    )
    for index, line in enumerate(slide.body_lines):
        draw_tracked_text(
            draw,
            (CARD_TEXT_X, body_top + index * body_line_height),
            line,
            font=body_font,
            fill=ON_SURFACE_MUTED,
        )

    page_font = font("inter", 21, 700)
    draw_tracked_text(
        draw,
        CARD_PAGE_POSITION,
        slide.page_label,
        font=page_font,
        fill=BRAND_BLUE,
        tracking=1,
        anchor="la",
    )
    return canvas


def render_summary_frames(
    draft: SummaryDraft,
    composition: SummaryComposition,
    *,
    cover_art: Image.Image,
    organ: str,
) -> list[Image.Image]:
    """Render the cover plus 2-6 cards in memory, in frame order."""
    _verify_cover(composition, draft)
    cards = list(composition.slides[1:])
    _require(
        2 <= len(cards) <= 6,
        f"A Summary story needs 2 to 6 cards, got {len(cards)}",
    )
    for slide in cards:
        _verify_card(slide, composition.body_size)

    background = _card_background(cover_art)
    frames = [_render_cover(composition, cover_art=cover_art, organ=organ)]
    frames.extend(
        _render_card(
            slide,
            body_size=composition.body_size,
            background=background,
            organ=organ,
        )
        for slide in cards
    )
    return frames


def _stored_card_plan(
    slide_plan: Mapping[str, Any], slide_index: int
) -> Mapping[str, Any]:
    for card in slide_plan.get("cards", []):
        if card.get("slide_index") == slide_index:
            return card
    raise RenderError(
        f"Stored Summary slide plan has no card for slide {slide_index}"
    )


def summary_composition_from_stored(
    draft: SummaryDraft,
    slide_plan: Mapping[str, Any] | None,
    slides: Sequence[Any],
) -> SummaryComposition:
    """Rebuild the render composition from the persisted plan and slide rows."""
    try:
        _require(slide_plan is not None, "Stored slide plan is missing")
        _require(
            slide_plan.get("family") == "summary",
            "Stored slide plan is not a Summary plan",
        )
        body_size = int(slide_plan["body_size"])
        cover_plan = slide_plan["cover"]
        _require(
            cover_plan["title_size"] in COVER_TITLE_SIZES,
            "Stored Summary cover title size is invalid",
        )
        ordered = sorted(slides, key=lambda slide: slide.slide_index)
        _require(len(ordered) >= 3, "Stored Summary slides are incomplete")
        cover_row = ordered[0]
        _require(
            cover_row.slide_type == "cover",
            "Stored Summary slides do not start with a cover",
        )
        composed: list[ComposedSummarySlide] = [
            ComposedSummarySlide(
                slide_index=cover_row.slide_index,
                slide_type="cover",
                label=cover_row.label,
                headline=cover_row.headline,
                body=None,
                alt_text=cover_row.alt_text or "",
                heading_size=int(cover_plan["title_size"]),
                heading_lines=tuple(cover_plan["title_lines"]),
            )
        ]
        for slide in ordered[1:]:
            card = _stored_card_plan(slide_plan, slide.slide_index)
            composed.append(
                ComposedSummarySlide(
                    slide_index=slide.slide_index,
                    slide_type=slide.slide_type,
                    label=slide.label,
                    headline=slide.headline,
                    body=slide.body,
                    alt_text=slide.alt_text or "",
                    card_number=int(card["card_number"]),
                    page_label=card["page_label"],
                    point_index=card.get("point_index"),
                    part_index=card.get("part_index"),
                    heading_size=int(card["heading_size"]),
                    heading_lines=tuple(card["heading_lines"]),
                    body_size=body_size,
                    body_lines=tuple(card["body_lines"]),
                )
            )
    except RenderError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise RenderError(
            f"Stored Summary render plan is invalid: {exc}"
        ) from exc

    return SummaryComposition(
        slides=tuple(composed),
        body_size=body_size,
        cover_title_size=int(cover_plan["title_size"]),
        slide_plan=dict(slide_plan),
        alt_texts=tuple(slide.alt_text or "" for slide in ordered),
    )


def _summary_file_name(session_date: date, frame_index: int) -> str:
    return f"summary-{session_date.isoformat()}-story-{frame_index:02d}.png"


def write_summary_output(
    frames: Sequence[Image.Image],
    *,
    post: Any,
    protocol: Any,
    output_dir: Path | str,
) -> SummaryOutput:
    """Write the rendered frames and the one caption file, without extras."""
    _require(3 <= len(frames) <= 7, "A Summary story needs 3 to 7 frames")
    for frame in frames:
        _require(
            frame.size == SUMMARY_SIZE and frame.mode == "RGB",
            "Every Summary frame must be an RGB 1080x1920 image",
        )

    caption = getattr(post, "caption", None)
    _require(
        bool(caption and str(caption).strip()),
        "A post caption is required to write the caption file",
    )
    session_date = getattr(protocol, "session_date", None)
    _require(
        isinstance(session_date, date),
        "The protocol session date is required for Summary filenames",
    )
    title = getattr(protocol, "title", None)
    _require(
        bool(title and str(title).strip()),
        "The protocol title is required for the output folder",
    )

    folder = protocol_output_folder(output_dir, session_date, title)
    image_paths: list[Path] = []
    caption_path = folder / "caption-summary-summary.txt"
    written: list[Path] = []
    try:
        for index, frame in enumerate(frames, start=1):
            path = folder / _summary_file_name(session_date, index)
            frame.save(path, format="PNG")
            image_paths.append(path)
            written.append(path)
        caption_path = write_caption_file(
            folder,
            post_type="summary",
            slug="summary",
            caption=str(caption),
        )
        written.append(caption_path)
    except Exception:
        for path in written:
            path.unlink(missing_ok=True)
        raise

    expected = set(image_paths) | {caption_path}
    for path in folder.iterdir():
        if path in expected or not path.is_file():
            continue
        if path.name.startswith("summary-") and "-story-" in path.name:
            path.unlink()
        elif path.name.startswith("caption-summary-"):
            path.unlink()

    return SummaryOutput(
        folder=folder,
        image_paths=image_paths,
        caption_path=caption_path,
    )


__all__ = [
    "CARD_BOX",
    "CARD_EDGE_WIDTH",
    "CARD_TEXT_WIDTH",
    "CARD_TEXT_X",
    "RenderError",
    "SUMMARY_SIZE",
    "SummaryOutput",
    "render_summary_frames",
    "summary_body_top",
    "summary_composition_from_stored",
    "write_summary_output",
]
