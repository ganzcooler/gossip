"""Behaviour tests for the stateless Summary-Writer role."""

import pytest

from app.core.post_models import SummaryBrief, SummaryDraft, SourceExcerpt
from app.services.llm_client import LLMAuthenticationError, LLMSchemaError
from app.services.summary_writer import SummaryWriterError, write_summary
from tests.support.fake_llm import FakeLLMClient

PROTOCOL_TEXT = (
    "TOP 1 Begrüßung\n"
    "Der Vorsitzende eröffnet die Sitzung.\n"
    "\n"
    "TOP 5 Haushalt\n"
    "Der Rat beschließt den Haushalt einstimmig.\n"
)

BRIEFS = [
    SummaryBrief(
        point="Der Haushalt wurde einstimmig beschlossen.",
        relevance="Die Mittel sind für alle Ortsteile wichtig.",
        source_anchors=["Der Rat beschließt den Haushalt einstimmig."],
    ),
    SummaryBrief(
        point="Der Radweg an der Hauptstraße wird gebaut.",
        relevance="Das verbessert die Verbindung im Ort.",
        source_anchors=["Der Radweg wird im Sommer gebaut."],
    ),
]

EXCERPTS = [
    SourceExcerpt(
        anchor="Der Rat beschließt den Haushalt einstimmig.",
        excerpt="Der Rat beschließt den Haushalt einstimmig.",
    ),
    SourceExcerpt(
        anchor="Der Radweg wird im Sommer gebaut.",
        excerpt="Der Radweg an der Hauptstraße wird im Sommer gebaut.",
    ),
]


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


async def test_writer_gets_only_the_summary_briefs_and_excerpts():
    expected = _draft()
    fake = FakeLLMClient(json_responses={"summary_writer": [expected]})

    result = await write_summary(BRIEFS, EXCERPTS, fake)

    assert result == expected
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call.role == "summary_writer"
    assert call.schema is SummaryDraft
    assert BRIEFS[0].point in call.prompt
    assert EXCERPTS[0].excerpt in call.prompt
    assert PROTOCOL_TEXT not in call.prompt
    assert "TOP 5 Haushalt" not in call.prompt


async def test_writer_retries_once_with_validation_feedback_then_succeeds():
    expected = _draft()
    fake = FakeLLMClient(
        json_responses={
            "summary_writer": [
                LLMSchemaError("body must contain 120 to 320 characters"),
                expected,
            ]
        }
    )

    result = await write_summary(BRIEFS, EXCERPTS, fake)

    assert result == expected
    assert len(fake.calls) == 2
    first_prompt = fake.calls[0].prompt
    retry_prompt = fake.calls[1].prompt
    assert "Correction Note" not in first_prompt
    assert "Correction Note" in retry_prompt
    assert "body must contain 120 to 320 characters" in retry_prompt
    assert BRIEFS[0].point in retry_prompt
    assert PROTOCOL_TEXT not in retry_prompt


async def test_writer_accepts_a_short_summary_cover_title():
    expected = _draft()
    expected.cover_title = "Haushalt"
    fake = FakeLLMClient(json_responses={"summary_writer": [expected]})

    result = await write_summary(BRIEFS, EXCERPTS, fake)

    assert result.cover_title == "Haushalt"


async def test_writer_retries_invalid_structure_once_and_then_fails():
    invalid = {
        "cover_title": "   ",
        "points": [],
    }
    fake = FakeLLMClient(json_responses={"summary_writer": [invalid, invalid]})

    with pytest.raises(SummaryWriterError, match="after retry"):
        await write_summary(BRIEFS, EXCERPTS, fake)

    assert len(fake.calls) == 2
    assert "Correction Note" in fake.calls[1].prompt


async def test_writer_does_not_retry_authentication_failures():
    fake = FakeLLMClient(
        json_responses={
            "summary_writer": [LLMAuthenticationError("Insufficient credits")]
        }
    )

    with pytest.raises(LLMAuthenticationError, match="Insufficient credits"):
        await write_summary(BRIEFS, EXCERPTS, fake)

    assert len(fake.calls) == 1
