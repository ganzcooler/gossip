"""Kicker-Writer fallback for topic sections that no deterministic label fits.

The composer and renderer never invent a generic visible label. If the derived
compound and every shortened candidate still overflow the 600 px follow-header,
this module asks a dedicated stateless LLM role for a short one-word Kicker.
The result is width-checked and retried once; a final neutral ``AKTUELL`` label
guards against repeated provider failures.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import replace

from app.core.post_models import TopicDraft, TopicKicker
from app.core.post_prompts import build_topic_kicker_prompt
from app.services.llm_client import LLMAuthenticationError, LLMClient, LLMSchemaError
from app.services.slide_composer import ComposedTopicSlide, TopicComposition
from app.services.topic_kickers import (
    DEFAULT_TOPIC_KICKER,
    fit_topic_kicker,
    format_follow_counter,
    kicker_char_budget,
    kicker_fits,
    normalize_topic_kicker,
)

logger = logging.getLogger(__name__)

TOPIC_KICKER_ROLE = "topic_kicker"


class TopicKickerError(Exception):
    """The Kicker-Writer did not produce a usable one-word label."""


def _section_candidate(slides: list[ComposedTopicSlide]) -> str:
    values = {
        normalize_topic_kicker(slide.kicker or slide.label or "")
        for slide in slides
    }
    values.discard("")
    if len(values) == 1:
        return next(iter(values))
    return ""


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
    slide_plan = copy.deepcopy(composition.slide_plan)
    for entry in slide_plan.get("slides", []):
        section_index = entry.get("section_index")
        if section_index in kickers:
            entry["kicker"] = kickers[section_index]
    return replace(
        composition,
        slides=slides,
        slide_plan=slide_plan,
    )


async def write_topic_kicker(
    *,
    title: str,
    section_h2: str,
    max_chars: int,
    llm: LLMClient,
    feedback: str | None = None,
) -> str:
    """Ask the Kicker-Writer for one short uppercase word."""
    prompt = build_topic_kicker_prompt(
        title=title,
        section_h2=section_h2,
        max_chars=max_chars,
        feedback=feedback,
    )
    try:
        response = await llm.generate_json(
            role=TOPIC_KICKER_ROLE,
            prompt=prompt,
            schema=TopicKicker,
        )
    except LLMAuthenticationError:
        raise
    except (LLMSchemaError, ValueError, TypeError) as exc:
        raise TopicKickerError(f"Kicker-Writer response is invalid: {exc}") from exc

    candidate = normalize_topic_kicker(response.kicker)
    if not candidate:
        raise TopicKickerError("Kicker-Writer returned an empty or multi-word label")
    if len(candidate) > max_chars:
        raise TopicKickerError(
            f"Kicker-Writer label {candidate!r} exceeds {max_chars} characters"
        )
    return candidate


async def resolve_topic_kickers(
    draft: TopicDraft,
    composition: TopicComposition,
    llm: LLMClient,
) -> TopicComposition:
    """Resolve every visible section kicker, using the LLM only as fallback."""
    content_slides = [
        slide for slide in composition.slides if slide.slide_type != "cover"
    ]
    content_total = len(content_slides)
    if not content_total:
        return composition

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

        current = _section_candidate(slides)
        if (
            current
            and current != "THEMA"
            and kicker_fits(
                current, body_size=composition.body_size, counters=counters
            )
        ):
            continue

        deterministic = fit_topic_kicker(
            section.h2,
            body_size=composition.body_size,
            counters=counters,
        )
        if deterministic is not None:
            resolved[section_index] = deterministic
            continue

        candidate: str | None = None
        max_chars = kicker_char_budget(
            body_size=composition.body_size, counters=counters
        )
        feedback: str | None = None
        for attempt in (1, 2):
            try:
                candidate = await write_topic_kicker(
                    title=draft.title,
                    section_h2=section.h2,
                    max_chars=max_chars,
                    llm=llm,
                    feedback=feedback,
                )
            except LLMAuthenticationError:
                raise
            except TopicKickerError as exc:
                logger.warning(
                    "Kicker-Writer attempt %s for section %s failed: %s",
                    attempt,
                    section_index,
                    exc,
                )
                candidate = None
                max_chars = max(6, max_chars - 2)
                feedback = str(exc)
                continue

            if kicker_fits(
                candidate, body_size=composition.body_size, counters=counters
            ):
                break
            feedback = (
                f"Das Wort {candidate} ist mit dem Zähler zu breit für die "
                f"600-px-Zeile. Liefere höchstens {max(6, max_chars - 2)} Zeichen."
            )
            max_chars = max(6, max_chars - 2)
            candidate = None

        if candidate is None:
            logger.warning(
                "Kicker-Writer did not produce a fitting label for section %s; "
                "using %s",
                section_index,
                DEFAULT_TOPIC_KICKER,
            )
            candidate = DEFAULT_TOPIC_KICKER
        resolved[section_index] = candidate

    return apply_topic_kickers(composition, resolved)


__all__ = [
    "TOPIC_KICKER_ROLE",
    "TopicKickerError",
    "apply_topic_kickers",
    "resolve_topic_kickers",
    "write_topic_kicker",
]
