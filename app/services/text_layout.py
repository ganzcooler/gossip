"""Shared Pillow text-layout primitives for the post renderers.

The module owns the runtime fonts and the deterministic fitting rules used by
the Summary composer (ticket 04) and the later topic/visual tickets. Text is
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


def body_size_that_fits(
    fits_at_size,
    sizes: Sequence[int] = (42, 39, 36),
):
    """Return the first size whose ``fits_at_size(size)`` returns a truthy value.

    Ticket-specific capacity calculations stay in their composers; this helper
    only keeps the post-wide "largest size wins" rule in one place.
    """
    for size in sizes:
        result = fits_at_size(size)
        if result:
            return size, result
    return None
