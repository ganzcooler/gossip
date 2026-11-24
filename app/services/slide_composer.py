"""Deterministic composition of drafts into Summary cards and topic slides.

No LLM is involved here. The composers choose one post-wide body size from
42/39/36, fit every heading and the cover title, and split overlong text
without rewording, truncating, or hyphenating it. The resulting plans give the
renderers exact line boxes and deterministic Alt-Texte.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.post_models import SummaryDraft, SummaryPoint, TopicDraft
from app.services.text_layout import (
    FitResult,
    TextLine,
    TextOverflowError,
    body_size_that_fits,
    fit_lines,
    inter_font,
    normalize_whitespace,
    split_text_balanced,
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
CARD_BODY_TOP = 678
CARD_HEADING_BODY_GAP = 38
CARD_BODY_BOTTOM = 1640
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


# ---------------------------------------------------------------------------
# Topic composition: orange 1080×1350 carousel.
# ---------------------------------------------------------------------------

TOPIC_BODY_SIZES = (42, 39, 36)
TOPIC_COVER_TITLE_SIZES = (96, 92, 88, 84, 80, 76, 72, 68, 64)
TOPIC_H2_SIZES = (72, 68, 64)

TOPIC_COVER_TITLE_WIDTH = 930
TOPIC_COVER_TITLE_X = 64
TOPIC_COVER_INSET_X = 48
TOPIC_COVER_INSET_WIDTH = 984
TOPIC_COVER_TITLE_MAX_LINES = 4
TOPIC_COVER_TITLE_LINE_HEIGHT = 1.0

TOPIC_TEXT_WIDTH = 600
TOPIC_H2_TOP = 263
TOPIC_H2_LINE_HEIGHT = 1.06
TOPIC_H2_MAX_LINES = 3
TOPIC_H2_ZONE = 160
TOPIC_H2_EXPANDED_ZONE = 204
TOPIC_H2_BODY_GAP = 24
TOPIC_BODY_BOTTOM = 1100
TOPIC_CONTINUATION_TOP = 136
TOPIC_BODY_LINE_HEIGHT = 1.4
TOPIC_PARAGRAPH_GAP_FACTOR = 0.72

TOPIC_COVER_LABEL = "IM FOKUS"
TOPIC_FALLBACK_LABEL = "THEMA"
TOPIC_MAX_CHAPTER_SHORT = 28
TOPIC_MIN_CONTENT_SLIDES = 4
TOPIC_MAX_CONTENT_SLIDES = 7

_LABEL_PUNCTUATION = ".,;:!?()[]{}\"'„“”‚‘’–—…"
_KICKER_STOPWORDS = frozenset(
    {
        "der",
        "die",
        "das",
        "den",
        "dem",
        "des",
        "ein",
        "eine",
        "einen",
        "einem",
        "eines",
        "einer",
        "und",
        "oder",
        "aber",
        "im",
        "in",
        "am",
        "an",
        "auf",
        "aus",
        "bei",
        "für",
        "mit",
        "von",
        "vor",
        "zu",
        "zur",
        "zum",
        "über",
        "unter",
        "um",
        "was",
        "wie",
        "warum",
        "wann",
        "wo",
        "wer",
        "auch",
        "nicht",
        "mehr",
        "neue",
        "neuer",
        "neues",
        "neuen",
    }
)


class TopicCompositionError(Exception):
    """The topic draft cannot be composed without changing its text."""


@dataclass(frozen=True)
class ComposedTopicSlide:
    """One deterministic topic Folie before rendering."""

    slide_index: int
    slide_type: str
    label: str | None
    headline: str | None
    body: str | None
    alt_text: str
    pair_index: int | None = None
    content_position: int | None = None
    section_index: int | None = None
    chapter_short: str | None = None
    heading_size: int | None = None
    heading_zone: int | None = None
    heading_lines: tuple[str, ...] = ()
    body_size: int | None = None
    body_lines: tuple[str, ...] = ()
    body_paragraphs: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class TopicComposition:
    """The composed Folien plus the persisted slide-plan and Markdown."""

    slides: tuple[ComposedTopicSlide, ...]
    body_size: int
    cover_title_size: int
    slide_plan: dict[str, Any]
    alt_texts: tuple[str, ...]
    markdown: str


@dataclass(frozen=True)
class _TopicBodyChunk:
    paragraph_index: int
    lines: tuple[TextLine, ...]


def derive_topic_kicker(h2: str) -> str:
    """Derive the one-word uppercase kicker from an H2.

    Leading articles and other filler words are skipped so the label stays
    meaningful. When every word is filler (or punctuation), the neutral
    ``THEMA`` label is used.
    """
    for raw_word in normalize_whitespace(h2).split(" "):
        word = raw_word.strip(_LABEL_PUNCTUATION)
        if len(word) < 2 or not any(character.isalpha() for character in word):
            continue
        if word.casefold() in _KICKER_STOPWORDS:
            continue
        return word.upper()
    return TOPIC_FALLBACK_LABEL


def derive_chapter_short(h2: str) -> str:
    """Derive the continuation label as a word-boundary prefix of the H2.

    The result is at most 28 characters and never gains an ellipsis. If the
    first word alone exceeds the limit, the neutral ``THEMA`` label is used;
    the article text itself is never changed.
    """
    words: list[str] = []
    length = 0
    for word in normalize_whitespace(h2).split(" "):
        candidate = len(word) if not words else length + 1 + len(word)
        if candidate > TOPIC_MAX_CHAPTER_SHORT:
            break
        words.append(word)
        length = candidate
    if not words:
        return TOPIC_FALLBACK_LABEL
    return " ".join(words)


def _fit_topic_cover_title(title: str) -> tuple[FitResult, int, int]:
    fit = fit_lines(
        title,
        family="oswald",
        sizes=TOPIC_COVER_TITLE_SIZES,
        width=TOPIC_COVER_TITLE_WIDTH,
        max_lines=TOPIC_COVER_TITLE_MAX_LINES,
        line_height=TOPIC_COVER_TITLE_LINE_HEIGHT,
        weight=700,
    )
    if fit is not None:
        return fit, TOPIC_COVER_TITLE_X, TOPIC_COVER_TITLE_WIDTH

    fit = fit_lines(
        title,
        family="oswald",
        sizes=TOPIC_COVER_TITLE_SIZES,
        width=TOPIC_COVER_INSET_WIDTH,
        max_lines=TOPIC_COVER_TITLE_MAX_LINES,
        line_height=TOPIC_COVER_TITLE_LINE_HEIGHT,
        weight=700,
    )
    if fit is not None:
        return fit, TOPIC_COVER_INSET_X, TOPIC_COVER_INSET_WIDTH

    fit = fit_lines(
        title,
        family="oswald",
        sizes=(TOPIC_COVER_TITLE_SIZES[-1],),
        width=TOPIC_COVER_INSET_WIDTH,
        max_lines=5,
        line_height=TOPIC_COVER_TITLE_LINE_HEIGHT,
        weight=700,
    )
    if fit is not None:
        return fit, TOPIC_COVER_INSET_X, TOPIC_COVER_INSET_WIDTH

    raise TopicCompositionError(
        "Topic cover title does not fit four lines at 64px (or five lines "
        f"at 64px with the inset fallback): {title!r}"
    )


def _fit_topic_h2(heading: str) -> tuple[FitResult, int]:
    for size in TOPIC_H2_SIZES:
        fit = fit_lines(
            heading,
            family="oswald",
            sizes=(size,),
            width=TOPIC_TEXT_WIDTH,
            max_lines=TOPIC_H2_MAX_LINES,
            line_height=TOPIC_H2_LINE_HEIGHT,
            weight=600,
        )
        if fit is None:
            continue
        zone = (
            TOPIC_H2_EXPANDED_ZONE
            if len(fit.lines) == 3
            else TOPIC_H2_ZONE
        )
        if fit.height <= zone + 1e-9:
            return fit, zone
    raise TopicCompositionError(
        "Topic H2 does not fit three lines at 64px within its 160/204px zone: "
        f"{heading!r}"
    )


def _wrap_topic_paragraph(
    paragraph: str,
    *,
    font,
) -> tuple[TextLine, ...]:
    try:
        lines = wrap_text(
            paragraph,
            font,
            TOPIC_TEXT_WIDTH,
            allow_char_split=False,
        )
    except TextOverflowError as exc:
        raise TopicCompositionError(
            "Topic body contains a word that is wider than the 600px column: "
            f"{paragraph[:80]!r}"
        ) from exc
    if not lines:
        raise TopicCompositionError("Topic body contains an empty paragraph")
    return tuple(lines)


def _pack_topic_section(
    paragraphs: list[str],
    *,
    font,
    body_size: int,
    first_capacity: float,
    require_sentence_boundaries: bool = False,
) -> list[list[_TopicBodyChunk]]:
    """Pack paragraphs into slides after checking each against its page.

    The first paragraph of a section is measured against the smaller heading
    slide (H2 present), every later paragraph against the continuation slide.
    A paragraph that fits its full page is atomic: when it does not fit the
    remainder of the current slide it moves whole to the next one. Only a
    paragraph that exceeds its full page is split, at sentence boundaries near
    the middle or at balanced word boundaries when no sentence qualifies. Each
    split part occupies its own slide as one body block, so a split paragraph
    never produces an internal paragraph gap.

    With ``require_sentence_boundaries`` every continuation of a multi-sentence
    paragraph must keep two complete sentences and the size minimum, preferring
    a sentence boundary but accepting a word boundary that still leaves enough
    substance. The composer uses that mode first and retries with the relaxed
    word-boundary fallback only when no body size can satisfy it.
    """
    line_height = body_size * TOPIC_BODY_LINE_HEIGHT
    paragraph_gap = round(body_size * TOPIC_PARAGRAPH_GAP_FACTOR)
    continuation_capacity = TOPIC_BODY_BOTTOM - TOPIC_CONTINUATION_TOP
    wrapped = [
        _wrap_topic_paragraph(paragraph, font=font)
        for paragraph in paragraphs
    ]
    page_capacities = [first_capacity] + [continuation_capacity] * (
        len(wrapped) - 1
    )
    overlong = [
        len(lines) * line_height > capacity + 1e-9
        for lines, capacity in zip(wrapped, page_capacities)
    ]

    slides: list[list[_TopicBodyChunk]] = []
    current: list[_TopicBodyChunk] = []
    used = 0.0
    capacity = first_capacity

    for paragraph_index, lines in enumerate(wrapped):
        if overlong[paragraph_index]:
            # An overlong paragraph starts at the top of its page; it never
            # fills the remainder of the slide that holds the previous one.
            if current:
                slides.append(current)
                current = []
                used = 0.0
                capacity = continuation_capacity

            try:
                parts = split_text_balanced(
                    paragraphs[paragraph_index],
                    font,
                    width=TOPIC_TEXT_WIDTH,
                    first_capacity=capacity,
                    continuation_capacity=continuation_capacity,
                    line_height=line_height,
                    require_sentence_boundaries=require_sentence_boundaries,
                )
            except TextOverflowError as exc:
                raise TopicCompositionError(
                    "Topic body paragraph cannot be split into fitting parts "
                    f"without changing it: {paragraphs[paragraph_index][:80]!r}"
                ) from exc

            for part in parts:
                slides.append(
                    [
                        _TopicBodyChunk(
                            paragraph_index,
                            _wrap_topic_paragraph(part, font=font),
                        )
                    ]
                )
            capacity = continuation_capacity
            used = 0.0
            continue

        # A paragraph that fits its full page stays atomic. If the current
        # slide has no room left, move it whole to the next slide.
        while True:
            gap = paragraph_gap if current else 0
            available = capacity - used - gap
            whole_height = len(lines) * line_height

            if whole_height <= available + 1e-9:
                current.append(_TopicBodyChunk(paragraph_index, lines))
                used += gap + whole_height
                break

            if current:
                slides.append(current)
                current = []
                used = 0.0
                capacity = continuation_capacity
                continue

            if capacity != continuation_capacity:
                capacity = continuation_capacity
                continue

            raise TopicCompositionError(
                "Topic body paragraph does not fit an empty content slide"
            )

    if current:
        slides.append(current)
    return slides


def _topic_body_text(chunks: list[_TopicBodyChunk]) -> str:
    parts: list[str] = []
    previous_paragraph: int | None = None
    for chunk in chunks:
        text = " ".join(line.text for line in chunk.lines)
        if parts and chunk.paragraph_index == previous_paragraph:
            parts[-1] = f"{parts[-1]} {text}"
        else:
            parts.append(text)
        previous_paragraph = chunk.paragraph_index
    return "\n\n".join(parts)


def _topic_body_lines(chunks: list[_TopicBodyChunk]) -> tuple[str, ...]:
    return tuple(line.text for chunk in chunks for line in chunk.lines)


def _topic_body_paragraphs(
    chunks: list[_TopicBodyChunk],
) -> tuple[tuple[str, ...], ...]:
    return tuple(
        tuple(line.text for line in chunk.lines) for chunk in chunks
    )


def _topic_cover_alt_text(title: str) -> str:
    return f"Titelbild des Themenbeitrags: {title}"


def _topic_content_alt_text(
    *,
    position: int,
    total: int,
    label: str,
    headline: str | None,
    body: str,
) -> str:
    prefix = f"Themen-Folie {position:02d} von {total:02d}: {label}."
    if headline:
        return f"{prefix} {headline}. {body}"
    return f"{prefix} {body}"


def compose_topic_slides(draft: TopicDraft) -> TopicComposition:
    """Compose the cover and 4–7 content slides for a topic ``draft``.

    Raises :class:`TopicCompositionError` when the draft cannot be laid out
    within the approved limits. The composer never shortens, rewords or
    truncates article text; overflow continues on separate slides.
    """
    cover_fit, cover_x, cover_width = _fit_topic_cover_title(draft.title)
    section_fits = [
        _fit_topic_h2(section.h2) for section in draft.sections
    ]

    def try_size(
        size: int,
        *,
        require_sentence_boundaries: bool,
    ) -> tuple[list[list[list[_TopicBodyChunk]]], int] | None:
        font = inter_font(size, weight=400)
        section_parts: list[list[list[_TopicBodyChunk]]] = []
        total = 0
        for section, (_, zone) in zip(draft.sections, section_fits):
            body_top = TOPIC_H2_TOP + zone + TOPIC_H2_BODY_GAP
            try:
                parts = _pack_topic_section(
                    section.paragraphs,
                    font=font,
                    body_size=size,
                    first_capacity=TOPIC_BODY_BOTTOM - body_top,
                    require_sentence_boundaries=require_sentence_boundaries,
                )
            except TopicCompositionError:
                # A word may be too wide at this size, or a multi-sentence
                # paragraph cannot keep its continuation rule; a smaller body
                # size gets its own chance before the draft is rejected.
                return None
            section_parts.append(parts)
            total += len(parts)
        if TOPIC_MIN_CONTENT_SLIDES <= total <= TOPIC_MAX_CONTENT_SLIDES:
            return section_parts, total
        return None

    found = body_size_that_fits(
        lambda size: try_size(size, require_sentence_boundaries=True),
        TOPIC_BODY_SIZES,
    )
    if found is None:
        # No size can keep every continuation substantial without leaving a
        # one-sentence orphan. Fall back to balanced word boundaries rather
        # than rejecting the article.
        found = body_size_that_fits(
            lambda size: try_size(size, require_sentence_boundaries=False),
            TOPIC_BODY_SIZES,
        )
    if found is None:
        # Report the smallest-size outcome for the writer's retry feedback.
        font = inter_font(TOPIC_BODY_SIZES[-1], weight=400)
        total = 0
        for section, (_, zone) in zip(draft.sections, section_fits):
            body_top = TOPIC_H2_TOP + zone + TOPIC_H2_BODY_GAP
            total += len(
                _pack_topic_section(
                    section.paragraphs,
                    font=font,
                    body_size=TOPIC_BODY_SIZES[-1],
                    first_capacity=TOPIC_BODY_BOTTOM - body_top,
                )
            )
        raise TopicCompositionError(
            "Topic draft yields "
            f"{total} content slides at {TOPIC_BODY_SIZES[-1]}px; "
            f"{TOPIC_MIN_CONTENT_SLIDES} to {TOPIC_MAX_CONTENT_SLIDES} are "
            "required. Shorten the article text or adjust the section "
            "structure without dropping facts."
        )
    body_size, (section_parts, content_count) = found

    content_plans: list[
        tuple[int, int, int, list[_TopicBodyChunk]]
    ] = []  # section index, part index, content position, chunks
    position = 0
    for section_index, parts in enumerate(section_parts):
        for part_index, chunks in enumerate(parts):
            position += 1
            content_plans.append((section_index, part_index, position, chunks))

    slides: list[ComposedTopicSlide] = [
        ComposedTopicSlide(
            slide_index=1,
            slide_type="cover",
            label=TOPIC_COVER_LABEL,
            headline=draft.title,
            body=None,
            alt_text=_topic_cover_alt_text(draft.title),
        )
    ]
    slide_plan_entries: list[dict[str, Any]] = []

    for section_index, part_index, content_position, chunks in content_plans:
        section = draft.sections[section_index]
        heading_fit, heading_zone = section_fits[section_index]
        kicker = derive_topic_kicker(section.h2)
        chapter_short = derive_chapter_short(section.h2)
        body = _topic_body_text(chunks)
        body_lines = _topic_body_lines(chunks)
        body_paragraphs = _topic_body_paragraphs(chunks)
        pair_index = (content_position + 1) // 2
        slide_index = content_position + 1

        if part_index == 0:
            slide_type = "heading"
            label = kicker
            headline = section.h2
            alt_label = kicker
            alt_headline = section.h2
        else:
            slide_type = "continuation"
            label = chapter_short
            headline = None
            alt_label = chapter_short
            alt_headline = None

        alt_text = _topic_content_alt_text(
            position=content_position,
            total=content_count,
            label=alt_label,
            headline=alt_headline,
            body=body,
        )
        slides.append(
            ComposedTopicSlide(
                slide_index=slide_index,
                slide_type=slide_type,
                label=label,
                headline=headline,
                body=body,
                alt_text=alt_text,
                pair_index=pair_index,
                content_position=content_position,
                section_index=section_index,
                chapter_short=chapter_short,
                heading_size=heading_fit.size if part_index == 0 else None,
                heading_zone=heading_zone if part_index == 0 else None,
                heading_lines=(
                    tuple(line.text for line in heading_fit.lines)
                    if part_index == 0
                    else ()
                ),
                body_size=body_size,
                body_lines=body_lines,
                body_paragraphs=body_paragraphs,
            )
        )
        entry: dict[str, Any] = {
            "slide_index": slide_index,
            "slide_type": slide_type,
            "content_position": content_position,
            "pair_index": pair_index,
            "section_index": section_index,
            "part_index": part_index,
            "kicker": kicker,
            "chapter_short": chapter_short,
            "body": body,
            "body_lines": list(body_lines),
            "body_paragraphs": [list(lines) for lines in body_paragraphs],
        }
        if part_index == 0:
            entry["headline"] = section.h2
            entry["heading_size"] = heading_fit.size
            entry["heading_zone"] = heading_zone
            entry["heading_lines"] = [
                line.text for line in heading_fit.lines
            ]
        slide_plan_entries.append(entry)

    slide_plan = {
        "family": "topic",
        "body_size": body_size,
        "content_slides": content_count,
        "total_slides": content_count + 1,
        "cover": {
            "label": TOPIC_COVER_LABEL,
            "title_size": cover_fit.size,
            "title_x": cover_x,
            "title_width": cover_width,
            "title_lines": [line.text for line in cover_fit.lines],
        },
        "slides": slide_plan_entries,
    }
    return TopicComposition(
        slides=tuple(slides),
        body_size=body_size,
        cover_title_size=cover_fit.size,
        slide_plan=slide_plan,
        alt_texts=tuple(slide.alt_text for slide in slides),
        markdown=render_topic_markdown(draft),
    )


def render_topic_markdown(draft: TopicDraft) -> str:
    """Render the persisted Markdown representation of a topic draft."""
    blocks = [f"# {draft.title}"]
    for section in draft.sections:
        blocks.append(f"## {section.h2}")
        blocks.extend(section.paragraphs)
    return "\n\n".join(blocks) + "\n"


__all__ = [
    "CARD_BODY_BOTTOM",
    "CARD_BODY_LINE_HEIGHT",
    "CARD_BODY_TOP",
    "CARD_HEADING_BODY_GAP",
    "CARD_HEADING_LINE_HEIGHT",
    "CARD_HEADING_MAX_HEIGHT",
    "CARD_HEADING_MAX_LINES",
    "CARD_HEADING_SIZES",
    "CARD_TEXT_WIDTH",
    "COVER_LABEL",
    "COVER_TITLE_LINE_HEIGHT",
    "COVER_TITLE_MAX_LINES",
    "COVER_TITLE_SIZES",
    "COVER_TITLE_WIDTH",
    "MAX_CARDS",
    "SUMMARY_BODY_SIZES",
    "TOPIC_BODY_BOTTOM",
    "TOPIC_BODY_LINE_HEIGHT",
    "TOPIC_BODY_SIZES",
    "TOPIC_CONTINUATION_TOP",
    "TOPIC_COVER_LABEL",
    "TOPIC_H2_EXPANDED_ZONE",
    "TOPIC_H2_ZONE",
    "TOPIC_MAX_CHAPTER_SHORT",
    "TOPIC_MAX_CONTENT_SLIDES",
    "TOPIC_MIN_CONTENT_SLIDES",
    "TOPIC_TEXT_WIDTH",
    "ComposedSummarySlide",
    "ComposedTopicSlide",
    "SummaryComposition",
    "SummaryCompositionError",
    "TopicComposition",
    "TopicCompositionError",
    "compose_summary_slides",
    "compose_topic_slides",
    "derive_chapter_short",
    "derive_topic_kicker",
    "render_summary_markdown",
    "render_topic_markdown",
]
