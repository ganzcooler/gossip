"""Stateless visual-prompt roles for the Summary and topic Beiträge.

Each writer receives only its validated draft (plus the number of artwork
prompts for a topic). It never sees the full protocol, source excerpts, other
posts, or any conversation history.
"""

from __future__ import annotations

from pydantic import ValidationError

from app.core.post_models import SummaryDraft, TopicDraft, VisualPrompts
from app.core.post_prompts import (
    build_summary_visual_prompt,
    build_topic_visual_prompt,
)
from app.services.llm_client import LLMAuthenticationError, LLMClient, LLMError

SUMMARY_VISUAL_PROMPTS_ROLE = "summary_visual_prompts"
TOPIC_VISUAL_PROMPTS_ROLE = "topic_visual_prompts"


class VisualPromptError(Exception):
    """The visual-prompt call did not produce a valid VisualPrompts object."""


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


async def write_topic_visual_prompts(
    draft: TopicDraft,
    pair_count: int,
    llm: LLMClient,
    *,
    role: str = TOPIC_VISUAL_PROMPTS_ROLE,
) -> VisualPrompts:
    """Generate the topic cover and pair artwork prompts from the draft only.

    ``pair_count`` is ``ceil(content_slides / 2)``. The returned prompt set must
    contain exactly that many artwork prompts; a provider that returns a
    different count is rejected at the step boundary instead of silently
    stretching the artwork grid.
    """
    if pair_count < 1:
        raise ValueError("pair_count must be at least 1")

    feedback: str | None = None
    for attempt in (1, 2):
        prompt = build_topic_visual_prompt(draft, pair_count, feedback=feedback)
        try:
            response = await llm.generate_json(
                role=role, prompt=prompt, schema=VisualPrompts
            )
            if isinstance(response, VisualPrompts):
                result = response
            else:
                result = VisualPrompts.model_validate(response)
        except LLMAuthenticationError:
            raise
        except (LLMError, ValidationError, TypeError, ValueError) as exc:
            error = VisualPromptError(f"Visual prompt writer failed: {exc}")
        else:
            if len(result.artwork_prompts) == pair_count:
                return result
            error = VisualPromptError(
                "Visual prompt writer returned "
                f"{len(result.artwork_prompts)} artwork prompts, expected "
                f"{pair_count}"
            )

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
