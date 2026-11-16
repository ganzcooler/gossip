"""Deterministic retrieval of source excerpts for a Quellenanker.

The retriever never calls an LLM. It normalises whitespace for matching (exact
substring first, case-insensitive fallback), maps the match back to the original
protocol text and returns the containing paragraph(s), bounded to a readable
size.
"""

import re
from collections.abc import Iterable

from app.core.post_models import SourceExcerpt

DEFAULT_MAX_EXCERPT_CHARS = 1200
_PARAGRAPH_SEPARATOR = re.compile(r"\n[ \t]*\n")


class MissingSourceAnchor(Exception):
    """Raised when a planner anchor cannot be found in the protocol text."""

    def __init__(self, anchor: str):
        self.anchor = anchor
        super().__init__(f"Quellenanker nicht im Protokoll gefunden: {anchor!r}")


def _normalise_with_offsets(text: str) -> tuple[str, list[int]]:
    """Collapse whitespace and remember the original offset of every character."""
    characters: list[str] = []
    offsets: list[int] = []
    index = 0
    length = len(text)

    while index < length:
        if text[index].isspace():
            index += 1
            continue
        if characters:
            characters.append(" ")
            offsets.append(index - 1)
        while index < length and not text[index].isspace():
            characters.append(text[index])
            offsets.append(index)
            index += 1

    return "".join(characters), offsets


def _paragraph_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    for separator in _PARAGRAPH_SEPARATOR.finditer(text):
        spans.append((start, separator.start()))
        start = separator.end()
    spans.append((start, len(text)))
    return spans


def _containing_span(
    spans: list[tuple[int, int]], start: int, end: int
) -> tuple[int, int, int]:
    for index, (span_start, span_end) in enumerate(spans):
        if span_start <= start and end <= span_end:
            return index, span_start, span_end
    # The anchor crossed a paragraph boundary; use the text between both ends.
    return 0, spans[0][0], spans[-1][1]


def _bounded_excerpt(
    text: str, start: int, end: int, max_chars: int
) -> str:
    spans = _paragraph_spans(text)
    index, span_start, span_end = _containing_span(spans, start, end)

    # A bare heading block gets its following paragraph as context. Larger
    # paragraphs already carry enough context and stay local.
    if "\n" not in text[span_start:span_end] and span_end - span_start < 100:
        low = high = index
        while span_end - span_start < 100:
            if high + 1 < len(spans):
                candidate_end = spans[high + 1][1]
                if candidate_end - span_start <= max_chars:
                    high += 1
                    span_end = candidate_end
                    continue
            if low > 0:
                candidate_start = spans[low - 1][0]
                if span_end - candidate_start <= max_chars:
                    low -= 1
                    span_start = candidate_start
                    continue
            break

    if span_end - span_start <= max_chars:
        return text[span_start:span_end].strip()

    available = max_chars - (end - start)
    if available < 0:
        # The anchor itself is longer than the budget; never truncate it.
        return text[start:end].strip()

    window_start = max(span_start, start - available // 2)
    window_end = min(span_end, window_start + max_chars)
    if window_end < end:
        window_end = min(span_end, end)
        window_start = max(span_start, window_end - max_chars)

    # Snap to line boundaries where possible so the context starts and ends cleanly.
    line_start = text.find("\n", window_start, start)
    if line_start != -1:
        window_start = line_start + 1
    line_end = text.rfind("\n", end, window_end)
    if line_end != -1:
        window_end = line_end

    return text[window_start:window_end].strip()


def retrieve_source_excerpt(
    protocol_text: str,
    anchor: str,
    *,
    max_chars: int = DEFAULT_MAX_EXCERPT_CHARS,
) -> SourceExcerpt:
    """Return the excerpt around one anchor, or raise ``MissingSourceAnchor``."""
    if max_chars < 1:
        raise ValueError("max_chars must be at least 1")

    normalised_anchor = " ".join(anchor.split())
    if not normalised_anchor:
        raise MissingSourceAnchor(anchor)

    normalised_text, offsets = _normalise_with_offsets(protocol_text)
    position = normalised_text.find(normalised_anchor)
    if position == -1:
        position = normalised_text.lower().find(normalised_anchor.lower())
    if position == -1:
        raise MissingSourceAnchor(anchor)

    start = offsets[position]
    end = offsets[position + len(normalised_anchor) - 1] + 1

    return SourceExcerpt(
        anchor=anchor,
        excerpt=_bounded_excerpt(protocol_text, start, end, max_chars),
    )


def retrieve_source_excerpts(
    protocol_text: str,
    anchors: Iterable[str],
    *,
    max_chars: int = DEFAULT_MAX_EXCERPT_CHARS,
) -> list[SourceExcerpt]:
    """Retrieve anchors in order, deduplicating identical excerpt texts."""
    excerpts: list[SourceExcerpt] = []
    seen: set[str] = set()

    for anchor in anchors:
        excerpt = retrieve_source_excerpt(protocol_text, anchor, max_chars=max_chars)
        if excerpt.excerpt in seen:
            continue
        seen.add(excerpt.excerpt)
        excerpts.append(excerpt)

    return excerpts
