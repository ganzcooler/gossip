"""Stateless visual-prompt role for the Summary-Beitrag.

The writer receives only the validated Summary draft. It never sees the full
protocol, source excerpts, topic briefs, or any conversation history.
"""

from __future__ import annotations

from pydantic import ValidationError

from app.core.post_models import SummaryDraft, VisualPrompts
from app.core.post_prompts import build_summary_visual_prompt
from app.services.llm_client import LLMAuthenticationError, LLMClient, LLMError

SUMMARY_VISUAL_PROMPTS_ROLE = "summary_visual_prompts"


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


__all__ = [
    "SUMMARY_VISUAL_PROMPTS_ROLE",
    "VisualPromptError",
    "write_summary_visual_prompts",
]
