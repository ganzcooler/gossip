"""Deterministic Pillow renderer for the orange 4:5 Themenbeitrag.

The renderer consumes the topic composition (or its persisted equivalent), slices one 720×1350 artwork per pair into the two 360×1350 image
strips, and renders every frame in memory first. Files are written only after
the whole carousel rendered successfully, so text overflow or a missing asset
never leaves a partial set in the output folder.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image, ImageDraw

from app.core.post_models import TopicDraft
from app.services.render_common import (
    BRAND_ORANGE,
    BRAND_ORANGE_DEEP,
    ON_SURFACE,
    ON_SURFACE_MUTED,
    OUTLINE,
    RenderError,
    SURFACE_BASE,
    apply_cover_scrim,
    draw_kicker_block,
    draw_logo,
    draw_organ_badge,
    draw_tracked_text,
    draw_ui_rect,
    ensure_title_contrast,
    font,
    logo_size,
    protocol_output_folder,
    text_advance,
    write_caption_file,
)
from app.services.slide_composer import (
    TOPIC_BODY_BOTTOM,
    TOPIC_CONTINUATION_TOP,
    TOPIC_COVER_INSET_WIDTH,
    TOPIC_COVER_INSET_X,
    TOPIC_COVER_LABEL,
    TOPIC_COVER_TITLE_LINE_HEIGHT,
    TOPIC_COVER_TITLE_SIZES,
    TOPIC_COVER_TITLE_WIDTH,
    TOPIC_COVER_TITLE_X,
    TOPIC_FALLBACK_LABEL,
    TOPIC_H2_EXPANDED_ZONE,
    TOPIC_H2_LINE_HEIGHT,
    TOPIC_H2_MAX_LINES,
    TOPIC_H2_SIZES,
    TOPIC_H2_TOP,
    TOPIC_H2_ZONE,
    TOPIC_MAX_CONTENT_SLIDES,
    TOPIC_MIN_CONTENT_SLIDES,
    TOPIC_PARAGRAPH_GAP_FACTOR,
    ComposedTopicSlide,
    TopicComposition,
    render_topic_markdown,
)
from app.services.text_layout import (
    fit_lines,
    normalize_whitespace,
)

logger = logging.getLogger(__name__)

TOPIC_SIZE = (1080, 1350)
TEXT_BLOCK_WIDTH = 720
IMAGE_STRIP_WIDTH = 360
CONTENT_TEXT_X_LEFT = 60
CONTENT_TEXT_X_RIGHT = 420
CONTENT_TEXT_WIDTH = 600
EDGE_WIDTH = 10
CONTENT_TOP = 74
HEADING_NUMBER_SIZE = 96
HEADING_NUMBER_Y = 74
HEADING_KICKER_Y = 194
HEADING_RULE_Y = 236
HEADING_RULE_HEIGHT = 3
H2_BODY_GAP = 24
BODY_LINE_HEIGHT = 1.4
FOOTER_LOGO_WIDTH = 104
FOOTER_LOGO_Y = 1110

COVER_LOGO_WIDTH = 288
COVER_LOGO_POSITION = (64, 150)
COVER_BADGE_TOP = 160
COVER_TITLE_BOTTOM = 1200
COVER_ACCENT_X = 44
COVER_ACCENT_WIDTH = 10
COVER_SAFE_TOP = 135
COVER_SAFE_BOTTOM = 1215
COVER_TITLE_MAX_LINES_HARD = 4
COVER_EMERGENCY_LINES = 5

_CONTENT_SLIDE_TYPES = ("heading", "continuation")
_SLUG_PATTERN = re.compile(r"^[a-z0-9-]+$")


@dataclass(frozen=True)
class TopicOutput:
    """The files written for one successfully rendered Themenbeitrag."""

    folder: Path
    image_paths: list[Path]
    caption_path: Path


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RenderError(message)


def _verify_lines(
    lines: Sequence[str],
    *,
    family: str,
    size: int,
    weight: int,
    width: float,
    tracking: float,
    label: str,
) -> None:
    _require(bool(lines), f"{label} has no rendered lines")
    display_font = font(family, size, weight)
    for line in lines:
        _require(bool(line.strip()), f"{label} contains an empty line")
        advance = text_advance(display_font, line, tracking)
        _require(
            advance <= width + 0.5,
            f"{label} line overflows {width:g}px: {line!r} ({advance:.1f}px)",
        )


def _fallback_cover_title(title: str) -> tuple[int, tuple[str, ...], int, int]:
    """Fit the cover title only when the composition carries no stored plan."""
    for x, width in (
        (TOPIC_COVER_TITLE_X, TOPIC_COVER_TITLE_WIDTH),
        (TOPIC_COVER_INSET_X, TOPIC_COVER_INSET_WIDTH),
    ):
        fit = fit_lines(
            title,
            family="oswald",
            sizes=TOPIC_COVER_TITLE_SIZES,
            width=width,
            max_lines=COVER_TITLE_MAX_LINES_HARD,
            line_height=TOPIC_COVER_TITLE_LINE_HEIGHT,
            weight=700,
        )
        if fit is not None:
            return fit.size, tuple(line.text for line in fit.lines), x, width

    fit = fit_lines(
        title,
        family="oswald",
        sizes=(TOPIC_COVER_TITLE_SIZES[-1],),
        width=TOPIC_COVER_INSET_WIDTH,
        max_lines=COVER_EMERGENCY_LINES,
        line_height=TOPIC_COVER_TITLE_LINE_HEIGHT,
        weight=700,
    )
    if fit is not None:
        logger.warning(
            "Topic cover title needs the five-line emergency fallback: %r", title
        )
        return (
            fit.size,
            tuple(line.text for line in fit.lines),
            TOPIC_COVER_INSET_X,
            TOPIC_COVER_INSET_WIDTH,
        )
    raise RenderError(
        "Topic cover title does not fit four lines at 64px (or five lines "
        f"at 64px with the inset fallback): {title!r}"
    )


def _cover_title_plan(
    composition: TopicComposition, draft: TopicDraft
) -> tuple[int, tuple[str, ...], int, int]:
    cover_plan = (composition.slide_plan or {}).get("cover")
    if not isinstance(cover_plan, Mapping):
        return _fallback_cover_title(draft.title)

    size = cover_plan.get("title_size")
    raw_lines = cover_plan.get("title_lines")
    x = cover_plan.get("title_x")
    width = cover_plan.get("title_width")
    if (
        not isinstance(size, int)
        or size not in TOPIC_COVER_TITLE_SIZES
        or not isinstance(raw_lines, list)
        or not raw_lines
        or not all(isinstance(line, str) for line in raw_lines)
        or not isinstance(x, int)
        or not isinstance(width, int)
        or x < 0
        or width <= 0
    ):
        return _fallback_cover_title(draft.title)
    return size, tuple(raw_lines), x, width


def _cover_ink_bbox(
    lines: Sequence[str], *, x: int, size: int
) -> tuple[int, int, int, int]:
    _require(bool(lines), "Topic cover title has no lines")
    display_font = font("oswald", size, 700)
    boxes = []
    for index, line in enumerate(lines):
        left, top, right, bottom = display_font.getbbox(line, anchor="la")
        # Pillow's anchored bbox reports 0 for the left bearing even though the
        # drawn mask starts a few pixels inside the box. The renderer draws
        # glyph by glyph with tracking, so the mask's left edge is the visible
        # left ink edge used to align the kicker.
        mask_bbox = display_font.getmask(line).getbbox()
        left_bearing = mask_bbox[0] if mask_bbox is not None else left
        boxes.append(
            (
                int(x + left_bearing),
                int(index * size * TOPIC_COVER_TITLE_LINE_HEIGHT + top),
                int(x + right),
                int(index * size * TOPIC_COVER_TITLE_LINE_HEIGHT + bottom),
            )
        )
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _verify_cover(
    composition: TopicComposition, draft: TopicDraft
) -> tuple[int, tuple[str, ...], int, int]:
    _require(
        composition.slides and composition.slides[0].slide_type == "cover",
        "The first topic image must be the cover",
    )
    cover = composition.slides[0]
    _require(cover.headline == draft.title, "Topic cover title does not match the draft")
    size, lines, x, width = _cover_title_plan(composition, draft)
    _require(
        " ".join(lines) == normalize_whitespace(draft.title),
        "Stored Topic cover title lines do not reconstruct the draft title",
    )
    _require(
        len(lines) <= COVER_TITLE_MAX_LINES_HARD
        or (size == TOPIC_COVER_TITLE_SIZES[-1] and len(lines) == COVER_EMERGENCY_LINES),
        "Topic cover title exceeds four lines (five only at 64px)",
    )
    _verify_lines(
        lines,
        family="oswald",
        size=size,
        weight=700,
        width=width,
        tracking=-0.005 * size,
        label="Topic cover title",
    )
    return size, lines, x, width


def _follow_counter(slide: ComposedTopicSlide, content_total: int) -> str:
    return f"{slide.content_position:02d}/{content_total:02d}"


def _visible_kickers(
    content_slides: Sequence[ComposedTopicSlide],
    *,
    body_size: int,
    content_total: int,
) -> dict[int, str]:
    """Resolve one visible kicker per section for the heading and follow slides.

    The section keeps its own kicker only when it is one word and the combined
    advance of kicker, gap and follow counter fits the 600px column on every
    slide of the section. Otherwise the whole section shows the neutral THEMA.
    """
    size = body_size + 2
    kicker_font = font("inter", size, 600)
    counter_font = font("oswald", size, 600)
    counter_tracking = 0.04 * size
    by_section: dict[int, list[ComposedTopicSlide]] = {}
    for slide in content_slides:
        section_index = slide.section_index
        _require(
            section_index is not None,
            "Topic content slide has no section index",
        )
        by_section.setdefault(section_index, []).append(slide)

    visible: dict[int, str] = {}
    for section_index, slides in by_section.items():
        heading = next(
            (slide for slide in slides if slide.slide_type == "heading"), None
        )
        label = ((heading.kicker or heading.label) if heading else "") or ""
        candidate = label.strip().upper()
        fits = bool(candidate) and len(candidate.split()) == 1
        if fits:
            kicker_width = text_advance(kicker_font, candidate)
            fits = all(
                kicker_width
                + 20
                + text_advance(
                    counter_font,
                    _follow_counter(slide, content_total),
                    counter_tracking,
                )
                <= CONTENT_TEXT_WIDTH
                for slide in slides
            )
        if not fits:
            logger.warning(
                "Topic section %s has a kicker that does not fit the follow-slide "
                "header; using THEMA",
                section_index,
            )
            visible[section_index] = TOPIC_FALLBACK_LABEL
        else:
            visible[section_index] = candidate
    return visible


def _body_paragraphs(slide: ComposedTopicSlide) -> tuple[tuple[str, ...], ...]:
    paragraphs = tuple(tuple(line for line in block) for block in slide.body_paragraphs)
    if not paragraphs:
        _require(bool(slide.body_lines), "Topic body has no rendered lines")
        return (tuple(slide.body_lines),)

    flattened = tuple(line for block in paragraphs for line in block)
    _require(
        flattened == tuple(slide.body_lines),
        "Topic body lines do not reconstruct the body paragraphs",
    )
    _require(all(paragraphs), "Topic body contains an empty paragraph block")
    _require(
        all(line.strip() for block in paragraphs for line in block),
        "Topic body contains an empty line",
    )
    return paragraphs


def _verify_body(slide: ComposedTopicSlide, body_size: int) -> None:
    paragraphs = _body_paragraphs(slide)
    _verify_lines(
        tuple(line for block in paragraphs for line in block),
        family="inter",
        size=body_size,
        weight=400,
        width=CONTENT_TEXT_WIDTH,
        tracking=0,
        label="Topic body",
    )


def _body_block_height(
    paragraphs: Sequence[Sequence[str]], body_size: int
) -> float:
    line_height = body_size * BODY_LINE_HEIGHT
    gap = round(body_size * TOPIC_PARAGRAPH_GAP_FACTOR)
    return (
        sum(len(block) * line_height for block in paragraphs)
        + gap * max(0, len(paragraphs) - 1)
    )


def _draw_body(
    draw: ImageDraw.ImageDraw,
    paragraphs: Sequence[Sequence[str]],
    *,
    x: int,
    top: float,
    body_size: int,
) -> None:
    body_font = font("inter", body_size, 400)
    line_height = body_size * BODY_LINE_HEIGHT
    gap = round(body_size * TOPIC_PARAGRAPH_GAP_FACTOR)
    cursor = top
    for block_index, block in enumerate(paragraphs):
        if block_index:
            cursor += gap
        for line in block:
            draw_tracked_text(
                draw,
                (x, cursor),
                line,
                font=body_font,
                fill=ON_SURFACE_MUTED,
            )
            cursor += line_height


def _draw_footer(canvas: Image.Image, text_x: int) -> None:
    logo_width, logo_height = logo_size(FOOTER_LOGO_WIDTH)
    logo_x = text_x + CONTENT_TEXT_WIDTH - logo_width
    _require(
        FOOTER_LOGO_Y + logo_height <= TOPIC_SIZE[1],
        "Topic footer logo leaves the canvas",
    )
    draw_logo(canvas, logo_x, FOOTER_LOGO_Y, FOOTER_LOGO_WIDTH)


def _side(content_position: int) -> tuple[int, int, tuple[int, int, int, int]]:
    if content_position % 2 == 1:
        return CONTENT_TEXT_X_LEFT, 720, (710, 0, 720, TOPIC_SIZE[1])
    return CONTENT_TEXT_X_RIGHT, 0, (360, 0, 370, TOPIC_SIZE[1])


def _render_heading_slide(
    slide: ComposedTopicSlide,
    *,
    kicker: str,
    content_position: int,
    content_total: int,
    body_size: int,
    pane: Image.Image,
) -> Image.Image:
    text_x, image_x, edge_box = _side(content_position)
    canvas = Image.new("RGB", TOPIC_SIZE, SURFACE_BASE)
    canvas.paste(pane, (image_x, 0))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle(
        (edge_box[0], edge_box[1], edge_box[2] - 1, edge_box[3] - 1),
        fill=BRAND_ORANGE_DEEP,
    )

    _require(
        slide.heading_size in TOPIC_H2_SIZES,
        f"Unsupported Topic H2 size: {slide.heading_size}",
    )
    _require(
        bool(slide.heading_lines),
        "Topic heading slide has no H2 lines",
    )
    _require(
        len(slide.heading_lines) <= TOPIC_H2_MAX_LINES,
        "Topic H2 exceeds three lines",
    )
    zone = slide.heading_zone
    if zone is None:
        zone = (
            TOPIC_H2_EXPANDED_ZONE
            if len(slide.heading_lines) == 3
            else TOPIC_H2_ZONE
        )
    _require(
        zone in (TOPIC_H2_ZONE, TOPIC_H2_EXPANDED_ZONE),
        f"Unsupported Topic H2 zone: {zone}",
    )
    heading_height = (
        len(slide.heading_lines) * slide.heading_size * TOPIC_H2_LINE_HEIGHT
    )
    _require(
        heading_height <= zone + 0.5,
        "Topic H2 exceeds its fitted 160/204px zone",
    )
    _verify_lines(
        slide.heading_lines,
        family="oswald",
        size=slide.heading_size,
        weight=600,
        width=CONTENT_TEXT_WIDTH,
        tracking=-0.005 * slide.heading_size,
        label="Topic H2",
    )
    _verify_body(slide, body_size)

    number_font = font("oswald", HEADING_NUMBER_SIZE, 700)
    draw_tracked_text(
        draw,
        (text_x, HEADING_NUMBER_Y),
        f"{content_position:02d}",
        font=number_font,
        fill=BRAND_ORANGE,
        tracking=0.01 * HEADING_NUMBER_SIZE,
        anchor="la",
    )

    kicker_font = font("inter", 22, 700)
    draw_tracked_text(
        draw,
        (text_x, HEADING_KICKER_Y),
        kicker,
        font=kicker_font,
        fill=ON_SURFACE,
        tracking=3,
        anchor="la",
    )

    draw.rectangle(
        (
            text_x,
            HEADING_RULE_Y,
            text_x + CONTENT_TEXT_WIDTH - 1,
            HEADING_RULE_Y + HEADING_RULE_HEIGHT - 1,
        ),
        fill=BRAND_ORANGE,
    )

    heading_font = font("oswald", slide.heading_size, 600)
    heading_line_height = slide.heading_size * TOPIC_H2_LINE_HEIGHT
    heading_tracking = -0.005 * slide.heading_size
    for index, line in enumerate(slide.heading_lines):
        draw_tracked_text(
            draw,
            (text_x, TOPIC_H2_TOP + index * heading_line_height),
            line,
            font=heading_font,
            fill=ON_SURFACE,
            tracking=heading_tracking,
            anchor="la",
        )

    body_top = TOPIC_H2_TOP + zone + H2_BODY_GAP
    paragraphs = _body_paragraphs(slide)
    body_height = _body_block_height(paragraphs, body_size)
    _require(
        body_top + body_height <= TOPIC_BODY_BOTTOM + 0.5,
        f"Topic body overflows the slide at {body_top + body_height:.1f}px",
    )
    _draw_body(
        draw, paragraphs, x=text_x, top=body_top, body_size=body_size
    )
    _draw_footer(canvas, text_x)
    return canvas


def _render_continuation_slide(
    slide: ComposedTopicSlide,
    *,
    kicker: str,
    content_position: int,
    content_total: int,
    body_size: int,
    pane: Image.Image,
) -> Image.Image:
    text_x, image_x, edge_box = _side(content_position)
    canvas = Image.new("RGB", TOPIC_SIZE, SURFACE_BASE)
    canvas.paste(pane, (image_x, 0))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle(
        (edge_box[0], edge_box[1], edge_box[2] - 1, edge_box[3] - 1),
        fill=BRAND_ORANGE_DEEP,
    )

    counter = _follow_counter(slide, content_total)
    size = body_size + 2
    kicker_font = font("inter", size, 600)
    counter_font = font("oswald", size, 600)
    counter_tracking = 0.04 * size
    kicker_width = text_advance(kicker_font, kicker)
    counter_width = text_advance(counter_font, counter, counter_tracking)
    _require(
        kicker_width + 20 + counter_width <= CONTENT_TEXT_WIDTH,
        "Topic follow kicker and counter do not fit the 600px column",
    )

    draw_tracked_text(
        draw,
        (text_x, CONTENT_TOP),
        kicker,
        font=kicker_font,
        fill=ON_SURFACE,
        anchor="la",
    )
    draw_tracked_text(
        draw,
        (text_x + CONTENT_TEXT_WIDTH - counter_width, CONTENT_TOP),
        counter,
        font=counter_font,
        fill=BRAND_ORANGE,
        tracking=counter_tracking,
        anchor="la",
    )
    draw.rectangle(
        (text_x, 135, text_x + CONTENT_TEXT_WIDTH - 1, 135),
        fill=OUTLINE,
    )

    _verify_body(slide, body_size)
    paragraphs = _body_paragraphs(slide)
    body_height = _body_block_height(paragraphs, body_size)
    region_height = TOPIC_BODY_BOTTOM - TOPIC_CONTINUATION_TOP
    _require(
        body_height <= region_height + 0.5,
        f"Topic body overflows the continuation region at {body_height:.1f}px",
    )
    body_top = (
        TOPIC_CONTINUATION_TOP
        + (region_height - body_height) / 2
        - round(0.03 * body_height)
    )
    body_top = max(TOPIC_CONTINUATION_TOP, body_top)
    _require(
        body_top + body_height <= TOPIC_BODY_BOTTOM + 0.5,
        f"Topic body overflows the slide at {body_top + body_height:.1f}px",
    )
    _draw_body(
        draw, paragraphs, x=text_x, top=body_top, body_size=body_size
    )
    _draw_footer(canvas, text_x)
    return canvas


def _render_cover(
    draft: TopicDraft,
    composition: TopicComposition,
    *,
    cover_art: Image.Image,
    organ: str,
) -> Image.Image:
    _require(
        cover_art.size == TOPIC_SIZE,
        f"Topic cover art must be {TOPIC_SIZE}, got {cover_art.size}",
    )
    size, lines, title_x, title_width = _verify_cover(composition, draft)
    canvas = apply_cover_scrim(cover_art)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, TOPIC_SIZE[0] - 1, 5), fill=BRAND_ORANGE)

    logo_box = draw_logo(
        canvas,
        COVER_LOGO_POSITION[0],
        COVER_LOGO_POSITION[1],
        COVER_LOGO_WIDTH,
    )
    badge_box = draw_organ_badge(
        canvas, organ, top=COVER_BADGE_TOP, fill=BRAND_ORANGE_DEEP
    )
    _require(
        badge_box[0] >= logo_box[2] + 24,
        "Organ badge collides with the topic cover logo",
    )

    ink_bbox = _cover_ink_bbox(lines, x=title_x, size=size)
    shift = COVER_TITLE_BOTTOM - ink_bbox[3]
    ink_top = ink_bbox[1] + shift
    ink_bottom = ink_bbox[3] + shift
    shifted_bbox = (
        ink_bbox[0],
        ink_top,
        ink_bbox[2],
        ink_bottom,
    )

    kicker_y = ink_top - 24 - 64
    # The kicker shares the title's visible left edge. The normal path keeps
    # its x=64 layout edge; the inset/emergency fallback aligns to the title
    # ink so a x=48 title and the kicker do not look offset.
    kicker_x = (
        ink_bbox[0] if title_x == TOPIC_COVER_INSET_X else title_x
    )
    kicker_box = draw_kicker_block(
        canvas,
        TOPIC_COVER_LABEL,
        x=kicker_x,
        y=kicker_y,
        fill=BRAND_ORANGE_DEEP,
    )

    _require(
        ink_top >= COVER_SAFE_TOP,
        "Topic cover title leaves the 1:1 safe band at the top",
    )
    _require(
        kicker_box[1] >= COVER_SAFE_TOP,
        "Topic cover kicker leaves the 1:1 safe band at the top",
    )
    accent_bottom = ink_bottom + 8
    _require(
        accent_bottom <= COVER_SAFE_BOTTOM,
        "Topic cover accent bar leaves the 1:1 safe band at the bottom",
    )
    for label, box in (
        ("logo", logo_box),
        ("organ badge", badge_box),
        ("kicker", kicker_box),
    ):
        _require(
            box[1] >= COVER_SAFE_TOP and box[3] <= COVER_SAFE_BOTTOM,
            f"Topic cover {label} leaves the 1:1 safe band",
        )

    draw_ui_rect(
        canvas,
        (
            COVER_ACCENT_X,
            ink_top - 8,
            COVER_ACCENT_X + COVER_ACCENT_WIDTH,
            ink_bottom + 8,
        ),
        fill=BRAND_ORANGE_DEEP,
        maximum=5,
    )

    canvas = ensure_title_contrast(canvas, shifted_bbox)
    draw = ImageDraw.Draw(canvas)
    title_font = font("oswald", size, 700)
    tracking = -0.005 * size
    line_height = size * TOPIC_COVER_TITLE_LINE_HEIGHT
    for index, line in enumerate(lines):
        draw_tracked_text(
            draw,
            (title_x, shift + index * line_height),
            line,
            font=title_font,
            fill=ON_SURFACE,
            tracking=tracking,
            anchor="la",
        )
    return canvas


def _pane_for(
    content_position: int,
    *,
    pair_art: Mapping[int, Image.Image],
    single_art: Image.Image | None,
) -> Image.Image:
    pair_index = (content_position + 1) // 2
    if single_art is not None and content_position % 2 == 1 and pair_index not in pair_art:
        pane = single_art
    else:
        art = pair_art[pair_index]
        pane = (
            art.crop((0, 0, IMAGE_STRIP_WIDTH, TOPIC_SIZE[1]))
            if content_position % 2 == 1
            else art.crop(
                (IMAGE_STRIP_WIDTH, 0, 2 * IMAGE_STRIP_WIDTH, TOPIC_SIZE[1])
            )
        )
    _require(
        pane.size == (IMAGE_STRIP_WIDTH, TOPIC_SIZE[1]),
        f"Topic image strip must be 360x1350, got {pane.size}",
    )
    return pane


def render_topic_frames(
    draft: TopicDraft,
    composition: TopicComposition,
    *,
    cover_art: Image.Image,
    pair_art: Mapping[int, Image.Image],
    single_art: Image.Image | None = None,
    organ: str,
) -> list[Image.Image]:
    """Render the cover plus 4–7 content slides in memory, in image order."""
    _require(
        4 <= len(composition.slides) - 1 <= 7,
        "A Themenbeitrag needs 4 to 7 content slides",
    )
    content_slides = list(composition.slides[1:])
    content_total = len(content_slides)
    pair_count = content_total // 2
    expects_single = content_total % 2 == 1

    _require(
        set(pair_art) == set(range(1, pair_count + 1)),
        "Topic pair artwork does not match the composed pair count",
    )
    for index, art in pair_art.items():
        _require(
            art.size == (2 * IMAGE_STRIP_WIDTH, TOPIC_SIZE[1]),
            f"Topic pair {index} must be 720x1350, got {art.size}",
        )
    if expects_single:
        _require(single_art is not None, "Topic unpaired last artwork is missing")
        _require(
            single_art.size == (IMAGE_STRIP_WIDTH, TOPIC_SIZE[1]),
            f"Topic single artwork must be 360x1350, got {single_art.size}",
        )
    else:
        single_art = None

    for slide in content_slides:
        _require(
            slide.slide_type in _CONTENT_SLIDE_TYPES,
            f"Unsupported topic slide type: {slide.slide_type}",
        )
        _require(
            slide.content_position is not None,
            "Topic content slide has no content position",
        )
        _require(
            slide.body_size == composition.body_size,
            "Topic slides do not share one post-wide body size",
        )
    _require(
        composition.body_size in (42, 39, 36),
        f"Unsupported Topic body size: {composition.body_size}",
    )
    _require(
        [slide.content_position for slide in content_slides]
        == list(range(1, content_total + 1)),
        "Topic content positions are not consecutive",
    )

    visible_kickers = _visible_kickers(
        content_slides,
        body_size=composition.body_size,
        content_total=content_total,
    )
    frames = [
        _render_cover(draft, composition, cover_art=cover_art, organ=organ)
    ]
    for content_position, slide in enumerate(content_slides, start=1):
        pane = _pane_for(
            content_position,
            pair_art=pair_art,
            single_art=single_art,
        )
        kicker = visible_kickers[slide.section_index]
        if slide.slide_type == "heading":
            frame = _render_heading_slide(
                slide,
                kicker=kicker,
                content_position=content_position,
                content_total=content_total,
                body_size=composition.body_size,
                pane=pane,
            )
        else:
            frame = _render_continuation_slide(
                slide,
                kicker=kicker,
                content_position=content_position,
                content_total=content_total,
                body_size=composition.body_size,
                pane=pane,
            )
        frames.append(frame)

    for frame in frames:
        _require(
            frame.size == TOPIC_SIZE and frame.mode == "RGB",
            "Every topic image must be an RGB 1080x1350 image",
        )
    return frames


def _stored_slide_plan(
    slide_plan: Mapping[str, Any], slide_index: int
) -> Mapping[str, Any]:
    for entry in slide_plan.get("slides", []):
        if entry.get("slide_index") == slide_index:
            return entry
    raise RenderError(
        f"Stored topic slide plan has no entry for slide {slide_index}"
    )


def _stored_kicker(entry: Mapping[str, Any], fallback: Any) -> str | None:
    """Prefer the plan's stored kicker; fall back to a slide label if absent."""
    kicker = entry.get("kicker")
    if isinstance(kicker, str) and kicker.strip():
        return kicker
    if isinstance(fallback, str) and fallback.strip():
        return fallback
    return None


def topic_composition_from_stored(
    draft: TopicDraft,
    slide_plan: Mapping[str, Any] | None,
    slides: Sequence[Any],
) -> TopicComposition:
    """Rebuild the render composition from the persisted plan and slide rows."""
    try:
        _require(slide_plan is not None, "Stored topic slide plan is missing")
        _require(
            slide_plan.get("family") == "topic",
            "Stored slide plan is not a topic plan",
        )
        body_size = int(slide_plan["body_size"])
        cover_plan = slide_plan["cover"]
        cover_title_size = int(cover_plan["title_size"])
        _require(
            cover_title_size in TOPIC_COVER_TITLE_SIZES,
            "Stored topic cover title size is invalid",
        )
        cover_title_lines = tuple(cover_plan["title_lines"])
        _require(
            " ".join(cover_title_lines) == normalize_whitespace(draft.title),
            "Stored topic cover title does not match the draft",
        )
        ordered = sorted(slides, key=lambda slide: slide.slide_index)
        _require(
            TOPIC_MIN_CONTENT_SLIDES + 1 <= len(ordered) <= TOPIC_MAX_CONTENT_SLIDES + 1,
            "Stored topic slides are incomplete",
        )
        cover_row = ordered[0]
        _require(
            cover_row.slide_type == "cover",
            "Stored topic slides do not start with a cover",
        )
        composed: list[ComposedTopicSlide] = [
            ComposedTopicSlide(
                slide_index=cover_row.slide_index,
                slide_type="cover",
                label=cover_row.label or TOPIC_COVER_LABEL,
                headline=cover_row.headline or draft.title,
                body=None,
                alt_text=cover_row.alt_text or "",
            )
        ]
        stored_entries = [
            (slide, _stored_slide_plan(slide_plan, slide.slide_index))
            for slide in ordered[1:]
        ]
        section_kickers: dict[int, str] = {}
        for slide, entry in stored_entries:
            if slide.slide_type != "heading":
                continue
            section_index = int(entry["section_index"])
            kicker = _stored_kicker(entry, slide.label)
            if kicker is not None:
                section_kickers[section_index] = kicker

        for slide, entry in stored_entries:
            section_index = int(entry["section_index"])
            composed.append(
                ComposedTopicSlide(
                    slide_index=slide.slide_index,
                    slide_type=slide.slide_type,
                    label=slide.label,
                    headline=slide.headline,
                    body=slide.body,
                    alt_text=slide.alt_text or "",
                    pair_index=int(entry["pair_index"]),
                    content_position=int(entry["content_position"]),
                    section_index=section_index,
                    kicker=_stored_kicker(
                        entry, section_kickers.get(section_index)
                    ),
                    chapter_short=entry.get("chapter_short"),
                    heading_size=entry.get("heading_size"),
                    heading_zone=entry.get("heading_zone"),
                    heading_lines=tuple(entry.get("heading_lines", [])),
                    body_size=body_size,
                    body_lines=tuple(entry.get("body_lines", [])),
                    body_paragraphs=tuple(
                        tuple(block) for block in entry.get("body_paragraphs", [])
                    ),
                )
            )
    except RenderError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise RenderError(f"Stored topic render plan is invalid: {exc}") from exc

    return TopicComposition(
        slides=tuple(composed),
        body_size=body_size,
        cover_title_size=cover_title_size,
        slide_plan=dict(slide_plan),
        alt_texts=tuple(slide.alt_text or "" for slide in ordered),
        markdown=render_topic_markdown(draft),
    )


def _topic_file_name(session_date: date, image_index: int) -> str:
    return f"topic-{session_date.isoformat()}-{image_index:02d}.png"


def _safe_slug(slug: Any) -> str:
    value = str(slug or "").strip()
    if _SLUG_PATTERN.fullmatch(value):
        return value
    sanitized = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
    if not sanitized:
        raise RenderError("A topic slug is required for the caption file")
    return sanitized


def write_topic_output(
    frames: Sequence[Image.Image],
    *,
    post: Any,
    protocol: Any,
    output_dir: Path | str,
) -> TopicOutput:
    """Write one topic's images and caption into its own protocol subfolder.

    The spec's image and caption basenames stay exact. Each Themenbeitrag gets
    the stable ``<protocol_folder>/topic-<slug>/`` subfolder so two topics in
    one protocol never overwrite each other's frames.
    """
    _require(5 <= len(frames) <= 8, "A Themenbeitrag needs 5 to 8 images")
    for frame in frames:
        _require(
            frame.size == TOPIC_SIZE and frame.mode == "RGB",
            "Every topic image must be an RGB 1080x1350 image",
        )

    caption = getattr(post, "caption", None)
    _require(
        bool(caption and str(caption).strip()),
        "A post caption is required to write the caption file",
    )
    session_date = getattr(protocol, "session_date", None)
    _require(
        isinstance(session_date, date),
        "The protocol session date is required for topic filenames",
    )
    title = getattr(protocol, "title", None)
    _require(
        bool(title and str(title).strip()),
        "The protocol title is required for the output folder",
    )
    slug = _safe_slug(getattr(post, "slug", None))

    protocol_folder = protocol_output_folder(output_dir, session_date, title)
    folder = protocol_folder / f"topic-{slug}"
    folder.mkdir(parents=True, exist_ok=True)
    image_paths: list[Path] = []
    written: list[Path] = []
    try:
        for index, frame in enumerate(frames, start=1):
            path = folder / _topic_file_name(session_date, index)
            frame.save(path, format="PNG")
            image_paths.append(path)
            written.append(path)
        caption_path = write_caption_file(
            folder,
            post_type="topic",
            slug=slug,
            caption=str(caption),
        )
        written.append(caption_path)
    except Exception:
        for path in written:
            path.unlink(missing_ok=True)
        raise

    expected = set(image_paths) | {caption_path}
    prefix = f"topic-{session_date.isoformat()}-"
    for path in folder.iterdir():
        if path in expected or not path.is_file():
            continue
        if path.name.startswith(prefix) and path.suffix == ".png":
            path.unlink()

    return TopicOutput(
        folder=folder,
        image_paths=image_paths,
        caption_path=caption_path,
    )


__all__ = [
    "CONTENT_TEXT_WIDTH",
    "CONTENT_TEXT_X_LEFT",
    "CONTENT_TEXT_X_RIGHT",
    "EDGE_WIDTH",
    "FOOTER_LOGO_WIDTH",
    "HEADING_NUMBER_SIZE",
    "TOPIC_SIZE",
    "TopicOutput",
    "render_topic_frames",
    "topic_composition_from_stored",
    "write_topic_output",
]
