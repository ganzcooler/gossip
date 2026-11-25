"""Deterministic topic-kicker derivation, compound shortening and fit checks.

A Kicker is the one-word uppercase label of a Themenabschnitt. The composer
starts with the first meaningful word of the H2 and shortens common German
compound suffixes only when the full word would not fit the follow-slide
header. The renderer validates the final choice; the pipeline may ask the
Kicker-Writer for a shorter word when no deterministic candidate fits.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.services.render_common import font, text_advance
from app.services.text_layout import normalize_whitespace

DEFAULT_TOPIC_KICKER = "AKTUELL"
TOPIC_KICKER_COLUMN_WIDTH = 600
TOPIC_KICKER_COUNTER_GAP = 20
TOPIC_KICKER_SIZE_OFFSET = 2
TOPIC_KICKER_COUNTER_TRACKING = 0.04

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

# Common compound heads that turn a long noun into a short, still meaningful
# label. Only the head is stripped; the remaining word must stay substantial.
_COMPOUND_SUFFIXES = (
    "veranstaltungen",
    "veranstaltung",
    "verordnungen",
    "verordnung",
    "richtlinien",
    "richtlinie",
    "maßnahmen",
    "maßnahme",
    "beschlüsse",
    "beschluss",
    "ausschüsse",
    "ausschuss",
    "satzungen",
    "satzung",
    "konzepte",
    "konzept",
    "berichte",
    "bericht",
    "vorlagen",
    "vorlage",
    "programme",
    "programm",
    "projekte",
    "projekt",
    "prüfungen",
    "prüfung",
    "verfahren",
    "anträge",
    "antrag",
    "pläne",
    "plan",
    "listen",
    "liste",
)
_CONNECTORS = ("s", "es", "n", "en")


def normalize_topic_kicker(value: str) -> str:
    """Return the one-word uppercase form of ``value`` or an empty string."""
    candidate = value.strip().upper()
    if not candidate or len(candidate.split()) != 1:
        return ""
    if not any(character.isalpha() for character in candidate):
        return ""
    return candidate


def derive_topic_kicker(h2: str) -> str:
    """Derive the one-word uppercase kicker from an H2.

    Leading articles and other filler words are skipped so the label stays
    meaningful. When every word is filler (or punctuation), the neutral
    ``AKTUELL`` label is used.
    """
    for raw_word in normalize_whitespace(h2).split(" "):
        word = raw_word.strip(_LABEL_PUNCTUATION)
        if len(word) < 2 or not any(character.isalpha() for character in word):
            continue
        if word.casefold() in _KICKER_STOPWORDS:
            continue
        return word.upper()
    return DEFAULT_TOPIC_KICKER


def shorten_topic_kicker(kicker: str) -> str | None:
    """Strip one common compound head from ``kicker`` when it stays meaningful."""
    candidate = normalize_topic_kicker(kicker)
    if not candidate:
        return None
    lowered = candidate.casefold()
    for suffix in _COMPOUND_SUFFIXES:
        if not lowered.endswith(suffix):
            continue
        base = candidate[: -len(suffix)]
        if len(base) < 5:
            continue
        for connector in _CONNECTORS:
            if base.casefold().endswith(connector) and len(base) - len(connector) >= 5:
                base = base[: -len(connector)]
                break
        shortened = normalize_topic_kicker(base)
        if shortened and shortened != candidate:
            return shortened
    return None


def kicker_candidates(h2: str) -> tuple[str, ...]:
    """Return the full kicker followed by progressively shortened compounds."""
    candidates: list[str] = []
    current = derive_topic_kicker(h2)
    while current and current not in candidates:
        candidates.append(current)
        current = shorten_topic_kicker(current)
    return tuple(candidates)


def format_follow_counter(position: int, total: int) -> str:
    """Return the zero-padded ``03/07`` follow-slide counter."""
    return f"{position:02d}/{total:02d}"


def kicker_fonts(body_size: int):
    """Return the Inter kicker font and Oswald counter font for follow slides."""
    size = body_size + TOPIC_KICKER_SIZE_OFFSET
    return font("inter", size, 600), font("oswald", size, 600), size


def kicker_fits(
    kicker: str,
    *,
    body_size: int,
    counters: Sequence[str],
) -> bool:
    """Return whether kicker plus every counter fits the 600 px text column."""
    candidate = normalize_topic_kicker(kicker)
    if not candidate:
        return False
    kicker_font, counter_font, size = kicker_fonts(body_size)
    tracking = TOPIC_KICKER_COUNTER_TRACKING * size
    kicker_width = text_advance(kicker_font, candidate)
    return all(
        kicker_width
        + TOPIC_KICKER_COUNTER_GAP
        + text_advance(counter_font, counter, tracking)
        <= TOPIC_KICKER_COLUMN_WIDTH
        for counter in counters
    )


def fit_topic_kicker(
    h2: str,
    *,
    body_size: int,
    counters: Sequence[str],
) -> str | None:
    """Return the first deterministic kicker candidate that fits, if any."""
    for candidate in kicker_candidates(h2):
        if kicker_fits(candidate, body_size=body_size, counters=counters):
            return candidate
    return None


def kicker_char_budget(*, body_size: int, counters: Sequence[str]) -> int:
    """Return a conservative character budget for the Kicker-Writer prompt."""
    _, counter_font, size = kicker_fonts(body_size)
    tracking = TOPIC_KICKER_COUNTER_TRACKING * size
    counter_width = max(
        (text_advance(counter_font, counter, tracking) for counter in counters),
        default=0.0,
    )
    available = (
        TOPIC_KICKER_COLUMN_WIDTH - TOPIC_KICKER_COUNTER_GAP - counter_width
    )
    average_character = 0.62 * size
    return max(6, int(available / average_character))


__all__ = [
    "DEFAULT_TOPIC_KICKER",
    "TOPIC_KICKER_COLUMN_WIDTH",
    "TOPIC_KICKER_COUNTER_GAP",
    "TOPIC_KICKER_COUNTER_TRACKING",
    "TOPIC_KICKER_SIZE_OFFSET",
    "derive_topic_kicker",
    "fit_topic_kicker",
    "format_follow_counter",
    "kicker_candidates",
    "kicker_char_budget",
    "kicker_fits",
    "kicker_fonts",
    "normalize_topic_kicker",
    "shorten_topic_kicker",
]
