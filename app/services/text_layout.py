"""Shared Pillow text-layout primitives for the post renderers.

The module owns the runtime fonts and the deterministic fitting rules used by
the Summary composer and the topic/visual stages. Text is
never reworded, truncated, or hyphenated: a heading either fits or the caller
gets a :class:`TextOverflowError`, and body text is only split at line or word
boundaries while preserving every character.

All measurements use the real variable-font metrics from Pillow. The two
variable fonts are opened once per (family, size, weight) and cached.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import IntEnum
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

RESOURCE_DIR = Path(__file__).resolve().parent.parent / "res"
OSWALD_PATH = RESOURCE_DIR / "Oswald-var.ttf"
INTER_PATH = RESOURCE_DIR / "Inter-var.ttf"

FAMILY_PATHS = {
    "oswald": OSWALD_PATH,
    "inter": INTER_PATH,
}

_MIN_VISIBLE_CHARS = 4
_WHITESPACE = re.compile(r"[ \t\r\n\f\v]+")
_SENTENCE_END = ".!?…"
_CLOSING_QUOTES = "\"'„“”‘’"
_ABBREVIATION_TAIL = re.compile(
    r"(?<!\w)(?:z\.\s*B\.|d\.\s*h\.|u\.\s*a\.|usw\.|Nr\.|Dr\.|St\.|ca\.)$",
    re.IGNORECASE,
)
_ABBREVIATION_STEM = re.compile(
    r"(?<!\w)(?:z\.|d\.|u\.)$",
    re.IGNORECASE,
)


class TextOverflowError(Exception):
    """Raised when text cannot be laid out without changing its content."""


@dataclass(frozen=True)
class TextLine:
    """One wrapped line; ``continues_word`` marks a character split."""

    text: str
    continues_word: bool = False


@dataclass(frozen=True)
class FitResult:
    """A successfully fitted heading or title."""

    text: str
    size: int
    lines: tuple[TextLine, ...]
    line_height: float

    @property
    def height(self) -> float:
        return len(self.lines) * self.line_height


def _font_path(family: str) -> Path:
    try:
        return FAMILY_PATHS[family]
    except KeyError:
        raise ValueError(f"unknown font family {family!r}") from None


@lru_cache(maxsize=None)
def load_font(
    path: Path | str, size: int, weight: int, opsz: int | None = None
) -> ImageFont.FreeTypeFont:
    """Load a variable font at ``size`` and apply the correct axes.

    Oswald has one axis (``wght``). Inter has two (``opsz``, ``wght``); passing
    only the weight would silently set the optical size instead, so the
    optical size is always passed explicitly and clamped to 14..32.
    """
    font_path = Path(path)
    font = ImageFont.truetype(str(font_path), size)
    axes = font.get_variation_axes()

    if font_path.name == "Oswald-var.ttf":
        font.set_variation_by_axes([weight])
    elif font_path.name == "Inter-var.ttf":
        optical_size = min(32, max(14, opsz if opsz is not None else size))
        # Axes order is defined by the font; Inter-var is [opsz, wght].
        assert len(axes) == 2
        font.set_variation_by_axes([optical_size, weight])
    return font


def oswald_font(size: int, weight: int = 700) -> ImageFont.FreeTypeFont:
    """Return a cached Oswald font at ``size`` and ``weight``."""
    if size < 1:
        raise ValueError("font size must be positive")
    return load_font(OSWALD_PATH, size, weight)


def inter_font(size: int, weight: int = 400) -> ImageFont.FreeTypeFont:
    """Return a cached Inter font at ``size`` and ``weight``."""
    if size < 1:
        raise ValueError("font size must be positive")
    return load_font(INTER_PATH, size, weight)


def _glyph_mask(font: ImageFont.FreeTypeFont, character: str) -> Image.Image:
    size = max(font.size, 1)
    image = Image.new("L", (size * 3, size * 3), 0)
    ImageDraw.Draw(image).text((0, 0), character, font=font, fill=255)
    return image


def glyph_present(font: ImageFont.FreeTypeFont, character: str) -> bool:
    """Return whether ``character`` has its own outline in ``font``.

    A missing character renders as the ``.notdef`` glyph. Comparing the two
    masks catches a tofu box as well as a silently empty fallback.
    """
    glyph = _glyph_mask(font, character)
    missing = _glyph_mask(font, "\uffff")
    return ImageChops.difference(glyph, missing).getbbox() is not None


def missing_glyphs(font: ImageFont.FreeTypeFont, text: str) -> list[str]:
    """Return the characters of ``text`` that would render as ``.notdef``."""
    missing: list[str] = []
    seen: set[str] = set()
    for character in text:
        if character.isspace() or character in seen:
            continue
        seen.add(character)
        if not glyph_present(font, character):
            missing.append(character)
    return missing


def normalize_whitespace(text: str) -> str:
    """Collapse horizontal/vertical whitespace runs to single spaces."""
    return _WHITESPACE.sub(" ", text).strip()


def visible_char_count(text: str) -> int:
    """Count non-whitespace characters in a line."""
    return sum(1 for character in text if not character.isspace())


def reconstruct_lines(lines: Sequence[TextLine]) -> str:
    """Rebuild the original paragraph from wrapped lines.

    Character-split chunks join without a space; all other boundaries are word
    boundaries and join with exactly one space.
    """
    result = ""
    for line in lines:
        if not result:
            result = line.text
        elif line.continues_word:
            result += line.text
        else:
            result += " " + line.text
    return result


def _char_chunks(
    word: str, font: ImageFont.FreeTypeFont, max_width: float
) -> list[str]:
    chunks: list[str] = []
    current = ""
    for character in word:
        candidate = current + character
        if current and font.getlength(candidate) > max_width:
            chunks.append(current)
            current = character
        else:
            current = candidate
    if current:
        chunks.append(current)
    if any(font.getlength(chunk) > max_width for chunk in chunks):
        raise TextOverflowError(f"character does not fit in {max_width}px: {word!r}")
    return chunks


def _avoid_widow(
    lines: list[TextLine], font: ImageFont.FreeTypeFont, max_width: float
) -> list[TextLine]:
    """Move one word down when the last line would be a lone orphan."""
    if len(lines) < 2 or any(line.continues_word for line in lines):
        return lines
    last_words = lines[-1].text.split(" ")
    previous_words = lines[-2].text.split(" ")
    if len(last_words) != 1 or len(previous_words) < 2:
        return lines
    moved = previous_words[-1]
    candidate = moved + " " + lines[-1].text
    if font.getlength(candidate) > max_width:
        return lines
    lines[-2] = TextLine(" ".join(previous_words[:-1]))
    lines[-1] = TextLine(candidate)
    return lines


def wrap_text(
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: float,
    *,
    allow_char_split: bool = False,
) -> list[TextLine]:
    """Greedy-wrap one paragraph using the font's real advance widths.

    Headings and titles must pass ``allow_char_split=False`` so an overlong
    word raises :class:`TextOverflowError` instead of being broken. Body copy
    may opt into a character split as a last resort; the resulting line is
    flagged so reconstruction can join it without inserting a space.
    """
    normalized = normalize_whitespace(text)
    if not normalized:
        return []
    if max_width <= 0:
        raise TextOverflowError("max_width must be positive")

    lines: list[TextLine] = []
    current = ""
    current_continues = False

    for word in normalized.split(" "):
        candidate = word if not current else current + " " + word
        if font.getlength(candidate) <= max_width:
            current = candidate
            continue

        if current:
            lines.append(TextLine(current, continues_word=current_continues))
            current = ""
            current_continues = False

        if font.getlength(word) <= max_width:
            current = word
            continue

        if not allow_char_split:
            raise TextOverflowError(f"word does not fit in {max_width}px: {word!r}")

        chunks = _char_chunks(word, font, max_width)
        lines.extend(
            TextLine(chunk, continues_word=index > 0)
            for index, chunk in enumerate(chunks[:-1])
        )
        current = chunks[-1]
        current_continues = True

    if current:
        lines.append(TextLine(current, continues_word=current_continues))
    return _avoid_widow(lines, font, max_width)


def fit_lines(
    text: str,
    *,
    family: str,
    sizes: Sequence[int],
    width: float,
    max_lines: int,
    line_height: float,
    weight: int,
    max_height: float | None = None,
    allow_char_split: bool = False,
    min_visible_chars: int = _MIN_VISIBLE_CHARS,
) -> FitResult | None:
    """Try display sizes from largest to smallest and return the first fit.

    A candidate is rejected when it wraps to more than ``max_lines``, contains
    a line with fewer than four visible characters, exceeds ``max_height``, or
    contains a word wider than the column (headings never character-split).
    """
    font_path = _font_path(family)

    for size in sizes:
        font = load_font(font_path, size, weight)
        try:
            lines = wrap_text(
                text, font, width, allow_char_split=allow_char_split
            )
        except TextOverflowError:
            continue

        if not lines or len(lines) > max_lines:
            continue
        if any(
            visible_char_count(line.text) < min_visible_chars for line in lines
        ):
            continue

        line_height_px = size * line_height
        if max_height is not None and len(lines) * line_height_px > max_height:
            continue

        return FitResult(
            text=normalize_whitespace(text),
            size=size,
            lines=tuple(lines),
            line_height=line_height_px,
        )

    return None


def _height_of(
    text: str,
    font: ImageFont.FreeTypeFont,
    width: float,
    line_height: float,
) -> float:
    return len(wrap_text(text, font, width, allow_char_split=False)) * line_height


def _word_boundaries(text: str) -> list[int]:
    """Return indexes at which a new part may start (after each space)."""
    return [index + 1 for index, character in enumerate(text) if character == " "]


def _is_sentence_boundary(text: str, position: int) -> bool:
    before = text[:position].rstrip()
    if not before:
        return False
    if before[-1] in _SENTENCE_END:
        return True
    return (
        before[-1] in "\"'„“”‘’"
        and len(before) > 1
        and before[-2] in _SENTENCE_END
    )


def _is_abbreviation_boundary(text: str, position: int) -> bool:
    """Return whether ``position`` closes a known German abbreviation."""
    before = text[:position].rstrip()
    if not before:
        return False
    core = before.rstrip(_CLOSING_QUOTES).rstrip()
    return bool(
        _ABBREVIATION_TAIL.search(core) or _ABBREVIATION_STEM.search(core)
    )


def _is_topic_sentence_boundary(text: str, position: int) -> bool:
    """Sentence-end heuristic for topic body copy.

    Extends the shared heuristic with a static abbreviation list so ``z. B.``,
    ``d. h.``, ``usw.`` and friends do not start a new slide. The ``(?<!\\w)``
    guard keeps real sentence ends such as ``Test.`` and ``Africa.`` valid.
    """
    return _is_sentence_boundary(text, position) and not (
        _is_abbreviation_boundary(text, position)
    )


def _sentence_end_positions(text: str) -> list[int]:
    positions = [
        position
        for position in _word_boundaries(text)
        if _is_topic_sentence_boundary(text, position)
    ]
    if _is_sentence_boundary(text, len(text)):
        positions.append(len(text))
    return positions


def _complete_sentences_after(
    text: str, position: int, sentence_ends: Sequence[int]
) -> int:
    """Count complete sentences in the suffix that starts at ``position``.

    A split inside a sentence leaves that sentence incomplete, so its closing
    punctuation does not count.
    """
    if _is_topic_sentence_boundary(text, position):
        return sum(1 for end in sentence_ends if end > position)
    return max(
        0,
        sum(1 for end in sentence_ends if end > position) - 1,
    )


def _fit_two_parts(
    text: str,
    font: ImageFont.FreeTypeFont,
    width: float,
    heights: tuple[float, float],
    line_height: float,
) -> list[str] | None:
    first_capacity, second_capacity = heights
    candidates: list[tuple[int, int, float, int]] = []

    for position in _word_boundaries(text):
        first = text[:position].strip()
        second = text[position:].strip()
        if not first or not second:
            continue
        first_height = _height_of(first, font, width, line_height)
        if first_height > first_capacity:
            continue
        second_height = _height_of(second, font, width, line_height)
        if second_height > second_capacity:
            continue
        score = (
            0 if _is_sentence_boundary(text, position) else 1,
            abs(first_height - second_height),
            -position,
        )
        candidates.append((score[0], score[1], score[2], position))

    if not candidates:
        return None
    position = min(candidates)[-1]
    return [text[:position].strip(), text[position:].strip()]


def split_text_to_fit(
    text: str,
    font: ImageFont.FreeTypeFont,
    *,
    width: float,
    max_heights: Sequence[float],
    line_height: float,
    allow_char_split: bool = False,
) -> list[str] | None:
    """Split one paragraph into consecutive parts that each fit a capacity.

    Boundaries are chosen at sentence endings first, then at word boundaries;
    with two capacities the split balances the rendered height. The returned
    parts join with single spaces to the normalized input, so callers can prove
    that no text was dropped or reworded. Returns ``None`` when the text needs
    more parts than ``max_heights`` allows.
    """
    if allow_char_split:
        raise ValueError(
            "split_text_to_fit cannot preserve reconstruction with character splits"
        )
    if not max_heights:
        return None
    if any(capacity <= 0 for capacity in max_heights):
        return None

    normalized = normalize_whitespace(text)
    if not normalized:
        return []

    if _height_of(normalized, font, width, line_height) <= max_heights[0]:
        return [normalized]

    if len(max_heights) == 2:
        return _fit_two_parts(
            normalized,
            font,
            width,
            (max_heights[0], max_heights[1]),
            line_height,
        )

    parts: list[str] = []
    remainder = normalized
    for index, capacity in enumerate(max_heights):
        if not remainder:
            return parts
        remainder_height = _height_of(remainder, font, width, line_height)
        if remainder_height <= capacity:
            parts.append(remainder)
            return parts
        if index == len(max_heights) - 1:
            return None

        chosen: str | None = None
        for position in reversed(_word_boundaries(remainder)):
            prefix = remainder[:position].strip()
            if not prefix:
                continue
            if _height_of(prefix, font, width, line_height) <= capacity:
                chosen = prefix
                break
        if chosen is None:
            return None
        parts.append(chosen)
        remainder = remainder[len(chosen):].strip()

    return None


@dataclass(frozen=True)
class _ParagraphBudget:
    """Continuation minimums measured once on the whole paragraph.

    Recursive splits must keep judging against the original paragraph rather
    than the shrinking remainder; otherwise a short first part lowers the bar
    for every later continuation and a three-sentence paragraph can end in a
    one-sentence orphan.
    """

    full_lines: int
    full_height: float
    sentence_count: int

    @property
    def requires_two_sentences(self) -> bool:
        return self.sentence_count >= 3

    @property
    def requires_substantial_continuation(self) -> bool:
        return self.full_lines >= 4

    @property
    def minimum_continuation_height(self) -> float:
        return 0.25 * self.full_height


@dataclass(frozen=True)
class _SplitContext:
    """Font metrics and page budget shared by every split of one paragraph."""

    font: ImageFont.FreeTypeFont
    width: float
    line_height: float
    continuation_capacity: float
    paragraph: _ParagraphBudget

    def wrap(self, text: str) -> list[TextLine]:
        return wrap_text(text, self.font, self.width, allow_char_split=False)

    def height(self, text: str) -> float:
        return len(self.wrap(text)) * self.line_height


class _SplitTier(IntEnum):
    """Preference order for a split boundary; lower tiers win."""

    SENTENCE_WITH_SUBSTANTIAL_CONTINUATION = 0
    WORD_WITH_SUBSTANTIAL_CONTINUATION = 1
    SENTENCE_WITH_RELAXED_SENTENCES = 2
    WORD_WITH_COMPLETE_SENTENCE = 3
    WORD_WITH_RELAXED_SENTENCES = 4
    WORD_WITHOUT_SIZE = 5
    ABBREVIATION_BOUNDARY = 6


@dataclass(frozen=True)
class _SplitCandidate:
    """One evaluated word boundary and its ranking key."""

    tier: _SplitTier
    balance: float
    position: int

    @property
    def rank(self) -> tuple[int, float, int]:
        # Lower tier and balance win; a later position breaks exact ties.
        return (int(self.tier), self.balance, -self.position)


def _choose_balanced_split(
    text: str,
    context: _SplitContext,
    *,
    capacity: float,
    first_part: bool,
    starts_at_sentence: bool,
    require_sentence_boundaries: bool = False,
) -> int | None:
    """Choose the best word boundary for the next balanced part.

    Sentence boundaries near the middle are preferred. A word boundary is the
    fallback and never splits inside a known abbreviation while a neutral
    boundary exists. The tiers encode substantial continuations above relaxed
    ones. A split is rejected when it would leave exactly one complete sentence
    as a continuation part, whether as the current prefix or as the final
    suffix of a paragraph that started with at least three sentences.

    With ``require_sentence_boundaries`` every continuation must still meet the
    two-sentence and size minimums. The composer uses that strict mode to try a
    smaller body size before it accepts a continuation below those minimums.
    """
    budget = context.paragraph
    full_height = context.height(text)
    can_finish_in_two = (
        full_height <= capacity + context.continuation_capacity + 1e-9
    )
    target = min(capacity, full_height / 2) if not can_finish_in_two else 0.0
    sentence_ends = _sentence_end_positions(text)
    boundaries = _word_boundaries(text)
    sentence_positions = [
        position
        for position in boundaries
        if _is_topic_sentence_boundary(text, position)
    ]
    sentence_position_set = set(sentence_positions)
    strict = require_sentence_boundaries and budget.requires_two_sentences

    def evaluate(position: int) -> _SplitCandidate | None:
        first = text[:position].strip()
        second = text[position:].strip()
        if not first or not second:
            return None

        first_height = context.height(first)
        if first_height > capacity + 1e-9:
            return None
        second_lines = context.wrap(second)
        second_height = len(second_lines) * context.line_height
        if can_finish_in_two and second_height > context.continuation_capacity + 1e-9:
            return None

        is_sentence = position in sentence_position_set
        is_abbreviation = _is_abbreviation_boundary(text, position)
        complete_sentences = _complete_sentences_after(
            text, position, sentence_ends
        )
        enough_sentences = (
            not budget.requires_two_sentences or complete_sentences >= 2
        )
        enough_size = not budget.requires_substantial_continuation or (
            len(second_lines) >= 2
            and second_height >= budget.minimum_continuation_height - 1e-9
        )
        final_suffix = second_height <= context.continuation_capacity + 1e-9
        prefix_ends = sum(1 for end in sentence_ends if end <= position)
        prefix_sentences = (
            prefix_ends if starts_at_sentence else max(0, prefix_ends - 1)
        )

        # Never leave exactly one complete sentence as a continuation part.
        lone_suffix = (
            budget.requires_two_sentences
            and is_sentence
            and final_suffix
            and complete_sentences == 1
        )
        lone_prefix = (
            budget.requires_two_sentences
            and not first_part
            and starts_at_sentence
            and is_sentence
            and prefix_sentences == 1
        )
        if lone_suffix or lone_prefix:
            return None
        if strict and not first_part and prefix_sentences < 2:
            return None

        if is_sentence and enough_sentences and enough_size:
            tier = _SplitTier.SENTENCE_WITH_SUBSTANTIAL_CONTINUATION
        elif not is_abbreviation and enough_sentences and enough_size:
            tier = _SplitTier.WORD_WITH_SUBSTANTIAL_CONTINUATION
        elif strict:
            return None
        elif is_sentence and enough_size:
            tier = _SplitTier.SENTENCE_WITH_RELAXED_SENTENCES
        elif (
            not is_abbreviation
            and enough_size
            and (not budget.requires_two_sentences or complete_sentences >= 1)
        ):
            tier = _SplitTier.WORD_WITH_COMPLETE_SENTENCE
        elif not is_abbreviation and enough_size:
            tier = _SplitTier.WORD_WITH_RELAXED_SENTENCES
        elif not is_abbreviation:
            tier = _SplitTier.WORD_WITHOUT_SIZE
        else:
            tier = _SplitTier.ABBREVIATION_BOUNDARY

        balance = (
            abs(first_height - second_height)
            if can_finish_in_two
            else abs(first_height - target)
        )
        return _SplitCandidate(tier, balance, position)

    candidates: list[_SplitCandidate] = []
    for position in sentence_positions:
        candidate = evaluate(position)
        if candidate is not None:
            candidates.append(candidate)
    substantial = [
        candidate
        for candidate in candidates
        if candidate.tier == _SplitTier.SENTENCE_WITH_SUBSTANTIAL_CONTINUATION
    ]
    if substantial:
        return min(substantial, key=lambda candidate: candidate.rank).position

    for position in boundaries:
        if position in sentence_position_set:
            continue
        candidate = evaluate(position)
        if candidate is not None:
            candidates.append(candidate)
    word_substantial = [
        candidate
        for candidate in candidates
        if candidate.tier == _SplitTier.WORD_WITH_SUBSTANTIAL_CONTINUATION
    ]
    if word_substantial:
        return min(word_substantial, key=lambda candidate: candidate.rank).position
    if not candidates:
        return None
    return min(candidates, key=lambda candidate: candidate.rank).position


def split_text_balanced(
    text: str,
    font: ImageFont.FreeTypeFont,
    *,
    width: float,
    first_capacity: float,
    continuation_capacity: float,
    line_height: float,
    require_sentence_boundaries: bool = False,
) -> list[str]:
    """Split topic copy into substantial parts that each fit a page.

    The first part fits ``first_capacity``; every later part fits
    ``continuation_capacity``. Sentence boundaries near the middle win. For a
    paragraph of at least three sentences the continuation keeps at least two
    complete sentences, and for a paragraph of at least four lines it also
    keeps two rendered lines and 25 % of the original paragraph height,
    whenever the page geometry allows it. The splitter never leaves exactly one
    sentence as a final continuation; it prefers a balanced earlier split or,
    with ``require_sentence_boundaries``, raises so the caller can try a
    smaller body size. Without a suitable sentence boundary the best balanced
    word boundary is used. Parts join with single spaces to the normalized
    input, so no text is reworded, shortened, hyphenated or character-split.
    """
    normalized = normalize_whitespace(text)
    if not normalized:
        return []
    if first_capacity <= 0 or continuation_capacity <= 0:
        raise TextOverflowError("split capacities must be positive")

    full_lines = len(wrap_text(normalized, font, width, allow_char_split=False))
    full_height = full_lines * line_height
    if full_height <= first_capacity + 1e-9:
        return [normalized]

    context = _SplitContext(
        font=font,
        width=width,
        line_height=line_height,
        continuation_capacity=continuation_capacity,
        paragraph=_ParagraphBudget(
            full_lines=full_lines,
            full_height=full_height,
            sentence_count=len(_sentence_end_positions(normalized)),
        ),
    )

    parts: list[str] = []
    remainder = normalized
    capacity = first_capacity
    starts_at_sentence = True
    while context.height(remainder) > capacity + 1e-9:
        position = _choose_balanced_split(
            remainder,
            context,
            capacity=capacity,
            first_part=not parts,
            starts_at_sentence=starts_at_sentence,
            require_sentence_boundaries=require_sentence_boundaries,
        )
        if position is None:
            raise TextOverflowError(
                "text cannot be split into fitting parts without rewriting"
            )
        parts.append(remainder[:position].strip())
        starts_at_sentence = _is_topic_sentence_boundary(remainder, position)
        remainder = remainder[position:].strip()
        if not remainder:
            raise TextOverflowError(
                "text cannot be split into fitting parts without rewriting"
            )
        capacity = continuation_capacity

    parts.append(remainder)
    return parts


def body_size_that_fits(
    fits_at_size,
    sizes: Sequence[int] = (42, 39, 36),
):
    """Return the first size whose ``fits_at_size(size)`` returns a truthy value.

    Family-specific capacity calculations stay in their composers; this helper
    only keeps the post-wide "largest size wins" rule in one place.
    """
    for size in sizes:
        result = fits_at_size(size)
        if result:
            return size, result
    return None
