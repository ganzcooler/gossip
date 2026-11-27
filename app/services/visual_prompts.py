"""Stateless visual-prompt roles for the Summary and topic Beiträge.

Each writer receives only its validated draft (plus the number of artwork
prompts for a topic). It never sees the full protocol, source excerpts, other
posts, or any conversation history.
"""

from __future__ import annotations

import logging
import re

from pydantic import ValidationError

from app.core.post_models import (
    SummaryDraft,
    TopicDraft,
    TopicVisualPrompts,
    VisualPrompts,
)
from app.core.post_prompts import (
    build_summary_visual_prompt,
    build_topic_visual_prompt,
)
from app.services.llm_client import LLMAuthenticationError, LLMClient, LLMError

SUMMARY_VISUAL_PROMPTS_ROLE = "summary_visual_prompts"
TOPIC_VISUAL_PROMPTS_ROLE = "topic_visual_prompts"

logger = logging.getLogger(__name__)

# Positive split language in a generated image prompt makes the provider draw a
# diptych with a visible centre seam. The writer is told not to use these terms
# at all; this validator enforces it at the step boundary.
_SPLIT_COMPOSITION_PATTERNS = (
    ("seam", re.compile(r"\bseams?\b", re.IGNORECASE)),
    (
        "panel",
        re.compile(
            r"\b(?:two|three|multiple|centre|center|central|vertical)\s+panels?\b"
            r"|\bmulti-panel\b|\bpanel\s+(?:composition|layout|split)\b",
            re.IGNORECASE,
        ),
    ),
    ("split", re.compile(r"\bsplits?\b|\bsplit-screen\b", re.IGNORECASE)),
    (
        "halves",
        re.compile(
            r"\bhalves\b|\b(?:left|right)\s+half\b|\btwo\s+halves\b",
            re.IGNORECASE,
        ),
    ),
    (
        "left/right portion",
        re.compile(
            r"\b(?:left|right)\s+(?:portion|third)\b|\bleft/right\b",
            re.IGNORECASE,
        ),
    ),
    (
        "diptych/triptych",
        re.compile(r"\b(?:diptych|triptych)\b", re.IGNORECASE),
    ),
    ("collage", re.compile(r"\bcollages?\b", re.IGNORECASE)),
    (
        "vertical divider",
        re.compile(r"\bvertical\s+(?:divider|separator)\b", re.IGNORECASE),
    ),
    (
        "pair composition",
        re.compile(
            r"\b(?:image|artwork|photo|photograph)\s+pair\b"
            r"|\bpair\s+(?:composition|layout|format)\b",
            re.IGNORECASE,
        ),
    ),
)


def _split_language(prompt: str) -> tuple[str, ...]:
    """Return the split-composition labels found in one generated prompt."""
    return tuple(
        label
        for label, pattern in _SPLIT_COMPOSITION_PATTERNS
        if pattern.search(prompt)
    )


class VisualPromptError(Exception):
    """The visual-prompt call did not produce a valid prompt object."""


async def write_summary_visual_prompts(
    draft: SummaryDraft,
    llm: LLMClient,
    *,
    role: str = SUMMARY_VISUAL_PROMPTS_ROLE,
) -> VisualPrompts:
    """Generate the Summary cover prompt from the Summary draft only."""
    prompt = build_summary_visual_prompt(draft)
    try:
        response = await llm.generate_json(
            role=role, prompt=prompt, schema=VisualPrompts
        )
        if isinstance(response, VisualPrompts):
            return response
        return VisualPrompts.model_validate(response)
    except LLMAuthenticationError:
        raise
    except (LLMError, ValidationError, TypeError, ValueError) as exc:
        raise VisualPromptError(f"Visual prompt writer failed: {exc}") from exc


def _split_findings(result: TopicVisualPrompts) -> dict[str, tuple[str, ...]]:
    """Return split-composition findings per generated prompt value."""
    entries: list[tuple[str, str]] = [("cover_prompt", result.cover_prompt)]
    entries.extend(
        (f"artwork_prompts[{index}]", prompt)
        for index, prompt in enumerate(result.artwork_prompts, start=1)
    )
    if result.single_prompt:
        entries.append(("single_prompt", result.single_prompt))
    findings: dict[str, tuple[str, ...]] = {}
    for label, prompt in entries:
        hits = _split_language(prompt)
        if hits:
            findings[label] = hits
    return findings


async def write_topic_visual_prompts(
    draft: TopicDraft,
    pair_count: int,
    llm: LLMClient,
    *,
    has_single: bool = False,
    role: str = TOPIC_VISUAL_PROMPTS_ROLE,
) -> TopicVisualPrompts:
    """Generate the topic cover, pair and optional single prompts.

    ``pair_count`` is ``content_slides // 2``. The returned prompt set must
    contain exactly that many artwork prompts and, for an odd content slide
    count, a dedicated ``single_prompt``. A provider that returns a different
    shape is rejected at the step boundary.
    """
    if pair_count < 1:
        raise ValueError("pair_count must be at least 1")

    feedback: str | None = None
    for attempt in (1, 2):
        prompt = build_topic_visual_prompt(
            draft,
            pair_count,
            has_single=has_single,
            feedback=feedback,
        )
        try:
            response = await llm.generate_json(
                role=role, prompt=prompt, schema=TopicVisualPrompts
            )
            if isinstance(response, TopicVisualPrompts):
                result = response
            else:
                result = TopicVisualPrompts.model_validate(response)
        except LLMAuthenticationError:
            raise
        except (LLMError, ValidationError, TypeError, ValueError) as exc:
            error = VisualPromptError(f"Visual prompt writer failed: {exc}")
        else:
            if len(result.artwork_prompts) != pair_count:
                logger.warning(
                    "Topic visual prompt writer returned %s artwork prompts, "
                    "expected %s (single_prompt set: %s)",
                    len(result.artwork_prompts),
                    pair_count,
                    bool(result.single_prompt),
                )
                error = VisualPromptError(
                    "Visual prompt writer returned "
                    f"{len(result.artwork_prompts)} artwork prompts, expected "
                    f"{pair_count}"
                )
            elif has_single and not result.single_prompt:
                logger.warning(
                    "Topic visual prompt writer returned no single_prompt for "
                    "%s artwork prompts",
                    len(result.artwork_prompts),
                )
                error = VisualPromptError(
                    "Visual prompt writer did not return a single_prompt "
                    "for the unpaired last slide"
                )
            elif findings := _split_findings(result):
                error = VisualPromptError(
                    "Visual prompt writer described a split composition ("
                    + "; ".join(
                        f"{label}: {', '.join(hits)}"
                        for label, hits in findings.items()
                    )
                    + "). Describe one continuous photograph without seams, "
                    "panels, halves or left/right portions."
                )
            else:
                return result

        if attempt == 1:
            feedback = str(error)
            continue
        raise error

    raise AssertionError("unreachable")


__all__ = [
    "SUMMARY_VISUAL_PROMPTS_ROLE",
    "TOPIC_VISUAL_PROMPTS_ROLE",
    "VisualPromptError",
    "write_summary_visual_prompts",
    "write_topic_visual_prompts",
]
