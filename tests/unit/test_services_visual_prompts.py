"""Behaviour tests for the stateless summary visual-prompt role."""

import pytest

from app.core.post_models import SummaryDraft, VisualPrompts
from app.services.llm_client import LLMAuthenticationError, LLMSchemaError
from app.services.visual_prompts import (
    SUMMARY_VISUAL_PROMPTS_ROLE,
    VisualPromptError,
    write_summary_visual_prompts,
)
from tests.support.fake_llm import FakeLLMClient

PROTOCOL_TEXT = "TOP 5 Haushalt\nDer Rat beschließt den Haushalt einstimmig.\n"


def _draft() -> SummaryDraft:
    return SummaryDraft(
        cover_title="Was der Rat in Rosdorf entschieden hat",
        points=[
            {
                "kicker": "Haushalt",
                "heading": "Der Rat hat den Haushalt beschlossen",
                "body": "x" * 120,
            },
            {
                "kicker": "Radweg",
                "heading": "Der Radweg kommt im Sommer",
                "body": "y" * 120,
            },
        ],
    )


async def test_visual_prompt_writer_gets_only_the_summary_draft():
    fake = FakeLLMClient(
        json_responses={
            SUMMARY_VISUAL_PROMPTS_ROLE: [
                VisualPrompts(cover_prompt="Weite, ruhige Szene am Ortsrand.")
            ]
        }
    )

    result = await write_summary_visual_prompts(_draft(), fake)

    assert result.cover_prompt == "Weite, ruhige Szene am Ortsrand."
    assert result.artwork_prompts == []
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call.role == "summary_visual_prompts"
    assert call.schema is VisualPrompts
    assert _draft().cover_title in call.prompt
    assert _draft().points[0].heading in call.prompt
    assert PROTOCOL_TEXT not in call.prompt
    assert "Themenbrief" not in call.prompt


async def test_visual_prompt_writer_raises_a_clear_error_on_schema_failure():
    fake = FakeLLMClient(
        json_responses={
            SUMMARY_VISUAL_PROMPTS_ROLE: [LLMSchemaError("bad visual JSON")]
        }
    )

    with pytest.raises(VisualPromptError, match="visual"):
        await write_summary_visual_prompts(_draft(), fake)


async def test_visual_prompt_writer_leaves_authentication_errors_to_the_pipeline():
    fake = FakeLLMClient(
        json_responses={
            SUMMARY_VISUAL_PROMPTS_ROLE: [
                LLMAuthenticationError("Insufficient credits")
            ]
        }
    )

    with pytest.raises(LLMAuthenticationError, match="Insufficient credits"):
        await write_summary_visual_prompts(_draft(), fake)
