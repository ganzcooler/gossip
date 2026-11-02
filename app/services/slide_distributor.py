"""Deterministic article-to-slide distribution.

The article is the source of truth. This module never rewrites, shortens or
summarizes text; it only splits paragraphs at sentence/word boundaries and
moves the exact text to the next slide when the measured capacity is reached.
"""

from __future__ import annotations

import re

from app.core.post_models import (
    ArticleDraft,
    CoverPlan,
    SlideContent,
    SummarySlidePlan,
    TopicSlidePair,
    TopicSlidePlan,
)
from app.services.errors import SlidePlanError
from app.services.slide_planner import (
    MAX_SUMMARY_SLIDES,
    MAX_TOPIC_SLIDES,
    _label_from_heading,
)
from app.services.slide_metrics import summary_body_capacity, topic_body_capacity

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def _split_sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_RE.split(text.strip()) if part.strip()]


def _split_long_sentence(sentence: str, capacity: int) -> list[str]:
    parts: list[str] = []
    remaining = sentence.strip()
    while len(remaining) > capacity:
        cut = remaining.rfind(" ", 0, capacity)
        if cut <= 0:
            cut = capacity
        parts.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        parts.append(remaining)
    return parts


def _chunks(text: str, capacity: int) -> list[str]:
    """Split text into chunks without changing its words."""
    chunks: list[str] = []
    current = ""
    for sentence in _split_sentences(text):
        for part in _split_long_sentence(sentence, capacity):
            candidate = f"{current} {part}".strip()
            if len(candidate) <= capacity:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                current = part
    if current:
        chunks.append(current)
    return chunks


def _section_text(section) -> str:
    return " ".join(paragraph.strip() for paragraph in section.paragraphs).strip()


def _build_chunks(article: ArticleDraft, capacity_fn):
    chunks: list[tuple[str | None, str, str]] = []
    first = True
    for section in article.sections:
        text = _section_text(section)
        if first:
            text = f"{article.lead} {text}".strip()
            first = False
        capacity = capacity_fn(section.heading)
        parts = _chunks(text, capacity)
        for index, part in enumerate(parts):
            label = _label_from_heading(section.heading) if index == 0 else None
            chunks.append((label, section.heading, part))
    return chunks


def _split_continuation_chunk(body: str) -> list[str]:
    midpoint = len(body) // 2
    left = body[:midpoint]
    cut = max(left.rfind(". "), left.rfind("! "), left.rfind("? "))
    if cut == -1:
        cut = left.rfind(" ")
    if cut <= 0:
        return [body]
    return [body[: cut + 1].strip(), body[cut + 1 :].strip()]


def build_summary_slides(article: ArticleDraft) -> SummarySlidePlan:
    chunks = _build_chunks(article, summary_body_capacity)
    if len(chunks) > MAX_SUMMARY_SLIDES:
        raise SlidePlanError(
            f"Summary article needs {len(chunks)} slides, maximum is "
            f"{MAX_SUMMARY_SLIDES}"
        )

    slides = [
        SlideContent(label=label, headline=headline, body=body)
        for label, headline, body in chunks
    ]
    cover = CoverPlan(
        kicker="SITZUNG KOMPAKT",
        headline=article.title,
        image_brief=article.lead,
    )
    return SummarySlidePlan(cover=cover, slides=slides)


def build_topic_slides(article: ArticleDraft) -> TopicSlidePlan:
    chunks = _build_chunks(article, topic_body_capacity)
    if len(chunks) > MAX_TOPIC_SLIDES:
        raise SlidePlanError(
            f"Topic article needs {len(chunks)} slides, maximum is "
            f"{MAX_TOPIC_SLIDES}"
        )
    if len(chunks) % 2 == 1:
        label, headline, body = chunks[-1]
        split = _split_continuation_chunk(body)
        if len(split) == 2:
            chunks = chunks[:-1] + [
                (label, headline, split[0]),
                (None, headline, split[1]),
            ]

    pairs: list[TopicSlidePair] = []
    for index in range(0, len(chunks), 2):
        left = chunks[index]
        right = chunks[index + 1]
        slides = [
            SlideContent(label=left[0], headline=left[1], body=left[2]),
            SlideContent(label=right[0], headline=right[1], body=right[2]),
        ]
        headlines = " / ".join(slide.headline for slide in slides)
        pairs.append(
            TopicSlidePair(
                slides=slides,
                artwork_brief=f"Editorial scene illustrating {headlines}. One complete composition, no text.",
            )
        )

    cover = CoverPlan(
        kicker="THEMA IM FOKUS",
        headline=article.title,
        image_brief=article.lead,
    )
    return TopicSlidePlan(cover=cover, pairs=pairs)
