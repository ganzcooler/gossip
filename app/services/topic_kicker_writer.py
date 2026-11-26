"""Jev-assisted topic kickers with a deterministic word-order fallback.

The complete H2 is sent to the Decisions API as the state. When the heading has
at least two distinct words, a single ``choice`` question offers the heading
words plus deterministic compound shortenings; Jev ranks them by how well they
work as a one-word heading. The ranked candidates are tried in order and the
first that fits the follow-slide header wins. If the decision call fails or none
of its candidates fits, the deterministic candidate chain (full word, then
shortened compounds) is tried before the heading's content words (function
words are skipped unless every word is a function word). ``AKTUELL`` remains
the final guard when no heading word fits.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import replace

from app.core.post_models import TopicDraft
from app.services.decision_models import ChoiceAnswer, ChoiceQuestion
from app.services.llm_client import LLMAuthenticationError, LLMClient, LLMError
from app.services.slide_composer import TopicComposition
from app.services.text_layout import normalize_whitespace
from app.services.topic_kickers import (
    DEFAULT_TOPIC_KICKER,
    _KICKER_STOPWORDS,
    _LABEL_PUNCTUATION,
    fit_topic_kicker,
    format_follow_counter,
    kicker_candidates,
    kicker_char_budget,
    kicker_fits,
    normalize_topic_kicker,
)

logger = logging.getLogger(__name__)

TOPIC_KICKER_ROLE = "topic_kicker_choice"


def kicker_word_candidates(h2: str) -> tuple[str, ...]:
    """Return every distinct word from ``h2`` in original order."""
    seen: set[str] = set()
    candidates: list[str] = []
    for raw_word in normalize_whitespace(h2).split(" "):
        word = raw_word.strip(_LABEL_PUNCTUATION)
        if len(word) < 2 or not any(character.isalpha() for character in word):
            continue
        key = word.casefold()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(word)
    return tuple(candidates)


def kicker_choice_candidates(h2: str) -> tuple[str, ...]:
    """Return heading words plus deterministic compound shortenings."""
    candidates = list(kicker_word_candidates(h2))
    seen = {word.casefold() for word in candidates}
    for candidate in kicker_candidates(h2):
        key = candidate.casefold()
        if key not in seen:
            seen.add(key)
            candidates.append(candidate)
    return tuple(candidates)


def _fallback_candidates(h2: str) -> tuple[str, ...]:
    """Return content words in heading order, skipping function words."""
    candidates = kicker_word_candidates(h2)
    content = tuple(
        word
        for word in candidates
        if word.casefold() not in _KICKER_STOPWORDS
    )
    return content or candidates


def _fits(
    candidate: str,
    *,
    body_size: int,
    counters: Sequence[str],
) -> bool:
    normalized = normalize_topic_kicker(candidate)
    return bool(normalized) and kicker_fits(
        normalized, body_size=body_size, counters=counters
    )


def _ranked_candidates(
    answer: ChoiceAnswer,
    candidates: Sequence[str],
) -> list[str]:
    """Rank the answer's probabilities first, then keep heading order."""
    known = {word.casefold(): word for word in candidates}
    ranked: list[str] = []
    seen: set[str] = set()

    def add(word: str) -> None:
        key = word.casefold()
        if key in known and key not in seen:
            seen.add(key)
            ranked.append(known[key])

    if answer.probabilities:
        for word, _ in sorted(
            answer.probabilities.items(),
            key=lambda item: item[1],
            reverse=True,
        ):
            add(word)
    add(answer.choice)
    for word in candidates:
        add(word)
    return ranked


async def choose_topic_kicker(
    h2: str,
    *,
    body_size: int,
    max_chars: int,
    counters: Sequence[str],
    llm: LLMClient,
    role: str = TOPIC_KICKER_ROLE,
) -> str | None:
    """Ask Jev for the best label, falling back to deterministic candidates."""
    words = kicker_word_candidates(h2)
    if not words:
        return None

    ranked: list[str] = []
    if len(words) >= 2:
        candidates = kicker_choice_candidates(h2)
        question = ChoiceQuestion(
            instructions=(
                "Which one-word label from this section heading, including "
                "shortened compounds, works best as the heading? Prefer a "
                "German noun that names the section; otherwise choose the "
                "label that best names it. Ignore articles, prepositions, "
                "conjunctions and numbers. Prefer a label that is clear out of "
                f"context and at most {max_chars} characters."
            ),
            criteria={
                word: f"Candidate label: {word}" for word in candidates
            },
        )
        try:
            response = await llm.decide(
                role=role,
                state=h2,
                questions={"kicker": question},
            )
        except LLMAuthenticationError:
            raise
        except LLMError as exc:
            logger.warning(
                "Kicker decision failed for %r; using deterministic fallback: %s",
                h2,
                exc,
            )
        else:
            answer = response.answers.get("kicker")
            if isinstance(answer, ChoiceAnswer):
                ranked = _ranked_candidates(answer, candidates)
            else:
                logger.warning(
                    "Kicker decision returned no choice for %r; using "
                    "deterministic fallback",
                    h2,
                )

    for candidate in ranked:
        if _fits(candidate, body_size=body_size, counters=counters):
            return normalize_topic_kicker(candidate)

    deterministic = fit_topic_kicker(
        h2,
        body_size=body_size,
        counters=counters,
    )
    if deterministic is not None:
        return normalize_topic_kicker(deterministic)

    for candidate in _fallback_candidates(h2):
        if _fits(candidate, body_size=body_size, counters=counters):
            return normalize_topic_kicker(candidate)

    return None


def apply_topic_kickers(
    composition: TopicComposition,
    kickers: dict[int, str],
) -> TopicComposition:
    """Return a copy of ``composition`` with the resolved section kickers."""
    if not kickers:
        return composition
    slides = tuple(
        replace(
            slide,
            kicker=kickers.get(slide.section_index, slide.kicker),
        )
        for slide in composition.slides
    )
    slide_plan = {
        **composition.slide_plan,
        "slides": [
            {
                **entry,
                **(
                    {"kicker": kickers[entry["section_index"]]}
                    if entry.get("section_index") in kickers
                    else {}
                ),
            }
            for entry in composition.slide_plan.get("slides", [])
        ],
    }
    return replace(
        composition,
        slides=slides,
        slide_plan=slide_plan,
    )


async def resolve_topic_kickers(
    draft: TopicDraft,
    composition: TopicComposition,
    llm: LLMClient,
) -> TopicComposition:
    """Resolve missing or invalid section kickers, reusing stored ones."""
    content_slides = [
        slide for slide in composition.slides if slide.slide_type != "cover"
    ]
    content_total = len(content_slides)
    if not content_total:
        return composition

    # Persisted plans carry this marker so re-renders keep their visible
    # kickers instead of paying for another Jev decision.
    reuse_stored = bool(composition.slide_plan.get("kickers_resolved"))
    resolved: dict[int, str] = {}
    for section_index, section in enumerate(draft.sections):
        slides = [
            slide
            for slide in content_slides
            if slide.section_index == section_index
        ]
        if not slides:
            continue
        counters = tuple(
            format_follow_counter(int(slide.content_position), content_total)
            for slide in slides
            if slide.content_position is not None
        )
        if not counters:
            continue

        if reuse_stored:
            stored = {
                normalize_topic_kicker(slide.kicker or "")
                for slide in slides
            }
            stored.discard("")
            if len(stored) == 1:
                stored_kicker = next(iter(stored))
                if stored_kicker != "THEMA" and kicker_fits(
                    stored_kicker,
                    body_size=composition.body_size,
                    counters=counters,
                ):
                    resolved[section_index] = stored_kicker
                    continue

        max_chars = kicker_char_budget(
            body_size=composition.body_size, counters=counters
        )
        candidate = await choose_topic_kicker(
            section.h2,
            body_size=composition.body_size,
            max_chars=max_chars,
            counters=counters,
            llm=llm,
        )
        if candidate is None:
            logger.warning(
                "No heading word fits section %s; using %s",
                section_index,
                DEFAULT_TOPIC_KICKER,
            )
            candidate = DEFAULT_TOPIC_KICKER
        resolved[section_index] = candidate

    resolved_composition = apply_topic_kickers(composition, resolved)
    slide_plan = {
        **resolved_composition.slide_plan,
        "kickers_resolved": True,
    }
    return replace(resolved_composition, slide_plan=slide_plan)


__all__ = [
    "TOPIC_KICKER_ROLE",
    "apply_topic_kickers",
    "choose_topic_kicker",
    "kicker_choice_candidates",
    "kicker_word_candidates",
    "resolve_topic_kickers",
]
