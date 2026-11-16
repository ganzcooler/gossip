"""Behaviour tests for the stateless summary visual-prompt role."""

import pytest

from app.core.post_models import SummaryDraft, TopicDraft, VisualPrompts
from app.services.llm_client import LLMAuthenticationError, LLMSchemaError
from app.services.visual_prompts import (
    SUMMARY_VISUAL_PROMPTS_ROLE,
    TOPIC_VISUAL_PROMPTS_ROLE,
    VisualPromptError,
    write_summary_visual_prompts,
    write_topic_visual_prompts,
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


def _topic_draft() -> TopicDraft:
    return TopicDraft(
        title="Was der Rat zum Haushalt in Rosdorf entschieden hat",
        sections=[
            {
                "h2": "Der Rat hat den Haushalt einstimmig beschlossen",
                "paragraphs": ["Der Rat hat den Haushalt beschlossen."],
            },
            {
                "h2": "Was jetzt mit den Mitteln für die Ortsteile passiert",
                "paragraphs": ["Die Verwaltung setzt die Mittel im Frühjahr um."],
            },
        ],
    )


async def test_topic_visual_prompt_writer_gets_only_its_draft_and_pair_count():
    fake = FakeLLMClient(
        json_responses={
            TOPIC_VISUAL_PROMPTS_ROLE: [
                VisualPrompts(
                    cover_prompt="Weite, ruhige Szene am Ortsrand.",
                    artwork_prompts=["Paar eins", "Paar zwei"],
                )
            ]
        }
    )

    result = await write_topic_visual_prompts(_topic_draft(), 2, fake)

    assert result.cover_prompt == "Weite, ruhige Szene am Ortsrand."
    assert result.artwork_prompts == ["Paar eins", "Paar zwei"]
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call.role == "topic_visual_prompts"
    assert call.schema is VisualPrompts
    assert _topic_draft().title in call.prompt
    assert _topic_draft().sections[0].h2 in call.prompt
    assert "genau 2 Prompts" in call.prompt
    assert PROTOCOL_TEXT not in call.prompt
    assert "Summary" not in call.prompt
    assert "Themenbrief" not in call.prompt


async def test_topic_visual_prompt_writer_rejects_the_wrong_artwork_count():
    fake = FakeLLMClient(
        json_responses={
            TOPIC_VISUAL_PROMPTS_ROLE: [
                VisualPrompts(
                    cover_prompt="Cover", artwork_prompts=["Nur ein Paar"]
                )
            ]
        }
    )

    with pytest.raises(VisualPromptError, match="expected 2"):
        await write_topic_visual_prompts(_topic_draft(), 2, fake)


async def test_topic_visual_prompt_writer_leaves_authentication_errors_to_the_pipeline():
    fake = FakeLLMClient(
        json_responses={
            TOPIC_VISUAL_PROMPTS_ROLE: [
                LLMAuthenticationError("Insufficient credits")
            ]
        }
    )

    with pytest.raises(LLMAuthenticationError, match="Insufficient credits"):
        await write_topic_visual_prompts(_topic_draft(), 2, fake)
