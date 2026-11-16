"""Deterministic composition of a Summary draft into cover and cards.

No LLM is involved here. The composer chooses one post-wide body size from
42/39/36, fits every heading and the cover title on the approved 1080×1920
geometry, and splits an overlong point onto at most two consecutive cards
without rewording, truncating, or hyphenating it. The resulting plan gives the
renderer exact line boxes and deterministic Alt-Texte.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.post_models import SummaryDraft, SummaryPoint
from app.services.text_layout import (
    FitResult,
    TextOverflowError,
    body_size_that_fits,
    fit_lines,
    inter_font,
    split_text_to_fit,
    wrap_text,
)

SUMMARY_BODY_SIZES = (42, 39, 36)
COVER_TITLE_SIZES = (76, 72, 68, 64)
CARD_HEADING_SIZES = (76, 72, 68)

COVER_TITLE_WIDTH = 950
COVER_TITLE_MAX_LINES = 3
COVER_TITLE_LINE_HEIGHT = 1.04

CARD_TEXT_WIDTH = 800
CARD_HEADING_MAX_LINES = 4
CARD_HEADING_LINE_HEIGHT = 1.08
CARD_HEADING_MAX_HEIGHT = 360
CARD_BODY_TOP = 718
CARD_HEADING_BODY_GAP = 38
CARD_BODY_BOTTOM = 1600
CARD_BODY_LINE_HEIGHT = 1.4

COVER_LABEL = "SITZUNG KOMPAKT"
MAX_CARDS = 6


class SummaryCompositionError(Exception):
    """The Summary draft cannot be composed without changing its text."""


@dataclass(frozen=True)
class ComposedSummarySlide:
    """One deterministic Summary-Folie before rendering."""

    slide_index: int
    slide_type: str
    label: str | None
    headline: str
    body: str | None
    alt_text: str
    pair_index: int | None = None
    card_number: int | None = None
    page_label: str | None = None
    point_index: int | None = None
    part_index: int | None = None
    heading_size: int | None = None
    heading_lines: tuple[str, ...] = ()
    body_size: int | None = None
    body_lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class SummaryComposition:
    """The composed Folien plus the persisted slide-plan representation."""

    slides: tuple[ComposedSummarySlide, ...]
    body_size: int
    cover_title_size: int
    slide_plan: dict[str, Any]
    alt_texts: tuple[str, ...]


@dataclass(frozen=True)
class _CardPlan:
    point_index: int
    part_index: int
    point: SummaryPoint
    heading: FitResult
    body: str
    body_lines: tuple[str, ...]


def _fit_cover_title(title: str) -> FitResult:
    fit = fit_lines(
        title,
        family="oswald",
        sizes=COVER_TITLE_SIZES,
        width=COVER_TITLE_WIDTH,
        max_lines=COVER_TITLE_MAX_LINES,
        line_height=COVER_TITLE_LINE_HEIGHT,
        weight=700,
    )
    if fit is None:
        raise SummaryCompositionError(
            f"Summary cover title does not fit {COVER_TITLE_MAX_LINES} lines "
            f"at {COVER_TITLE_SIZES[-1]}px: {title!r}"
        )
    return fit


def _fit_card_heading(heading: str) -> FitResult:
    fit = fit_lines(
        heading,
        family="oswald",
        sizes=CARD_HEADING_SIZES,
        width=CARD_TEXT_WIDTH,
        max_lines=CARD_HEADING_MAX_LINES,
        line_height=CARD_HEADING_LINE_HEIGHT,
        weight=700,
        max_height=CARD_HEADING_MAX_HEIGHT,
    )
    if fit is None:
        raise SummaryCompositionError(
            f"Summary card heading does not fit {CARD_HEADING_MAX_LINES} lines "
            f"at {CARD_HEADING_SIZES[-1]}px: {heading!r}"
        )
    return fit


def _plan_cards(
    draft: SummaryDraft, body_size: int, headings: list[FitResult]
) -> list[_CardPlan] | None:
    font = inter_font(body_size, weight=400)
    line_height = body_size * CARD_BODY_LINE_HEIGHT
    cards: list[_CardPlan] = []

    for point_index, (point, heading) in enumerate(zip(draft.points, headings)):
        capacity = CARD_BODY_BOTTOM - (
            CARD_BODY_TOP + heading.height + CARD_HEADING_BODY_GAP
        )
        if capacity <= 0:
            return None

        try:
            parts = split_text_to_fit(
                point.body,
                font,
                width=CARD_TEXT_WIDTH,
                max_heights=(capacity, capacity),
                line_height=line_height,
                allow_char_split=False,
            )
        except TextOverflowError:
            return None

        if parts is None or len(parts) > 2:
            return None

        for part_index, part in enumerate(parts):
            try:
                lines = wrap_text(part, font, CARD_TEXT_WIDTH)
            except TextOverflowError:
                return None
            cards.append(
                _CardPlan(
                    point_index=point_index,
                    part_index=part_index,
                    point=point,
                    heading=heading,
                    body=part,
                    body_lines=tuple(line.text for line in lines),
                )
            )

    return cards


def _cover_alt_text(title: str) -> str:
    return f"Titelbild des Summary-Beitrags: {title}"


def _card_alt_text(
    *, kicker: str, heading: str, body: str, number: int, total: int
) -> str:
    return (
        f"Summary-Card {number:02d} von {total:02d}: "
        f"{kicker}. {heading}. {body}"
    )


def compose_summary_slides(draft: SummaryDraft) -> SummaryComposition:
    """Compose the cover and 2–6 cards for ``draft``.

    Raises :class:`SummaryCompositionError` when the draft cannot be laid out
    within the approved limits. The composer never falls back to shortening or
    rephrasing a heading, title, kicker, or body.
    """
    cover = _fit_cover_title(draft.cover_title)
    headings = [_fit_card_heading(point.heading) for point in draft.points]

    def try_size(size: int) -> list[_CardPlan] | None:
        plans = _plan_cards(draft, size, headings)
        if plans is None or not 2 <= len(plans) <= MAX_CARDS:
            return None
        return plans

    found = body_size_that_fits(try_size, SUMMARY_BODY_SIZES)
    if found is None:
        raise SummaryCompositionError(
            "Summary draft needs more than six cards at the smallest body "
            "size, or a point needs more than two cards"
        )
    body_size, card_plans = found

    total_frames = 1 + len(card_plans)
    slides: list[ComposedSummarySlide] = [
        ComposedSummarySlide(
            slide_index=1,
            slide_type="cover",
            label=COVER_LABEL,
            headline=draft.cover_title,
            body=None,
            alt_text=_cover_alt_text(draft.cover_title),
            heading_size=cover.size,
            heading_lines=tuple(line.text for line in cover.lines),
        )
    ]
    card_plan_json: list[dict[str, Any]] = []

    for card_index, plan in enumerate(card_plans, start=1):
        slide_index = card_index + 1
        page_label = f"{slide_index:02d} / {total_frames:02d}"
        slides.append(
            ComposedSummarySlide(
                slide_index=slide_index,
                slide_type="heading",
                label=plan.point.kicker,
                headline=plan.point.heading,
                body=plan.body,
                alt_text=_card_alt_text(
                    kicker=plan.point.kicker,
                    heading=plan.point.heading,
                    body=plan.body,
                    number=card_index,
                    total=len(card_plans),
                ),
                pair_index=None,
                card_number=card_index,
                page_label=page_label,
                point_index=plan.point_index,
                part_index=plan.part_index,
                heading_size=plan.heading.size,
                heading_lines=tuple(line.text for line in plan.heading.lines),
                body_size=body_size,
                body_lines=plan.body_lines,
            )
        )
        card_plan_json.append(
            {
                "slide_index": slide_index,
                "card_number": card_index,
                "page_label": page_label,
                "point_index": plan.point_index,
                "part_index": plan.part_index,
                "heading_size": plan.heading.size,
                "heading_lines": [line.text for line in plan.heading.lines],
                "body_lines": list(plan.body_lines),
            }
        )

    slide_plan = {
        "family": "summary",
        "body_size": body_size,
        "total_frames": total_frames,
        "cover": {
            "title_size": cover.size,
            "title_lines": [line.text for line in cover.lines],
        },
        "cards": card_plan_json,
    }
    return SummaryComposition(
        slides=tuple(slides),
        body_size=body_size,
        cover_title_size=cover.size,
        slide_plan=slide_plan,
        alt_texts=tuple(slide.alt_text for slide in slides),
    )


def render_summary_markdown(draft: SummaryDraft) -> str:
    """Render the persisted Markdown representation of a Summary draft."""
    blocks = [f"# {draft.cover_title}"]
    for point in draft.points:
        blocks.append(f"## {point.kicker}: {point.heading}")
        blocks.append(point.body)
    return "\n\n".join(blocks) + "\n"


__all__ = [
    "CARD_BODY_BOTTOM",
    "CARD_BODY_LINE_HEIGHT",
    "CARD_BODY_TOP",
    "CARD_HEADING_BODY_GAP",
    "CARD_TEXT_WIDTH",
    "COVER_LABEL",
    "MAX_CARDS",
    "SUMMARY_BODY_SIZES",
    "ComposedSummarySlide",
    "SummaryComposition",
    "SummaryCompositionError",
    "compose_summary_slides",
    "render_summary_markdown",
]
