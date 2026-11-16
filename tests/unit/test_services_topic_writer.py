"""Behaviour tests for the stateless Themen-Writer role."""

import pytest

from app.core.post_models import SourceExcerpt, TopicBrief, TopicDraft
from app.services.llm_client import LLMAuthenticationError, LLMSchemaError
from app.services.slide_composer import TopicCompositionError
from app.services.topic_writer import TopicWriterError, write_topic
from tests.support.fake_llm import FakeLLMClient

PROTOCOL_TEXT = (
    "TOP 1 Begrüßung\n"
    "Der Vorsitzende eröffnet die Sitzung.\n"
    "\n"
    "TOP 5 Haushalt\n"
    "Der Rat beschließt den Haushalt einstimmig.\n"
)

BRIEF = TopicBrief(
    slug="haushalt",
    title="Haushalt beschlossen",
    focus="Die wichtigsten Posten im Gemeindehaushalt",
    relevance="Die Entscheidung betrifft alle Ortsteile.",
    source_anchors=["Der Rat beschließt den Haushalt einstimmig."],
)

EXCERPTS = [
    SourceExcerpt(
        anchor="Der Rat beschließt den Haushalt einstimmig.",
        excerpt="Der Rat beschließt den Haushalt einstimmig.",
    )
]


def _draft(title: str = "Haushalt: Was der Rat jetzt entschieden hat") -> TopicDraft:
    return TopicDraft(
        title=title,
        sections=[
            {
                "h2": "Der Rat hat den Haushalt beschlossen",
                "paragraphs": [
                    "Der Rat hat den Haushalt einstimmig beschlossen. "
                    "Die Mittel sind für alle Ortsteile wichtig."
                ],
            },
            {
                "h2": "Die Verwaltung zahlt die Mittel aus",
                "paragraphs": [
                    "Die Verwaltung zahlt die Mittel im Frühjahr aus."
                ],
            },
        ],
    )


async def test_writer_gets_only_its_brief_and_excerpts():
    expected = _draft()
    fake = FakeLLMClient(json_responses={"topic_writer": [expected]})

    result = await write_topic(BRIEF, EXCERPTS, fake)

    assert result == expected
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call.role == "topic_writer"
    assert call.schema is TopicDraft
    assert BRIEF.focus in call.prompt
    assert BRIEF.source_anchors[0] in call.prompt
    assert EXCERPTS[0].excerpt in call.prompt
    assert PROTOCOL_TEXT not in call.prompt
    assert "TOP 5 Haushalt" not in call.prompt


async def test_writer_retries_once_with_validation_feedback_then_succeeds():
    expected = _draft()
    fake = FakeLLMClient(
        json_responses={
            "topic_writer": [
                LLMSchemaError("h2 must contain 20 to 60 characters"),
                expected,
            ]
        }
    )

    result = await write_topic(BRIEF, EXCERPTS, fake)

    assert result == expected
    assert len(fake.calls) == 2
    assert "Korrekturhinweis" not in fake.calls[0].prompt
    assert "Korrekturhinweis" in fake.calls[1].prompt
    assert "h2 must contain 20 to 60 characters" in fake.calls[1].prompt
    assert PROTOCOL_TEXT not in fake.calls[1].prompt


async def test_writer_retries_invalid_structure_once_and_then_fails():
    invalid = {"title": "Zu kurz", "sections": []}
    fake = FakeLLMClient(json_responses={"topic_writer": [invalid, invalid]})

    with pytest.raises(TopicWriterError, match="after retry") as error:
        await write_topic(BRIEF, EXCERPTS, fake)

    assert error.value.step == "writer"
    assert len(fake.calls) == 2
    assert "Korrekturhinweis" in fake.calls[1].prompt


async def test_composition_failure_gets_one_retry_with_its_feedback():
    attempts = []

    def compose(draft: TopicDraft) -> None:
        attempts.append(draft)
        if len(attempts) == 1:
            raise TopicCompositionError(
                "Themenbeitrag ergibt nur 3 Content-Slides; 4 bis 7 sind nötig"
            )

    expected = _draft()
    fake = FakeLLMClient(json_responses={"topic_writer": [_draft(), expected]})

    result = await write_topic(BRIEF, EXCERPTS, fake, compose=compose)

    assert result == expected
    assert len(fake.calls) == 2
    assert len(attempts) == 2
    assert "Korrekturhinweis" in fake.calls[1].prompt
    assert "3 Content-Slides" in fake.calls[1].prompt
    assert PROTOCOL_TEXT not in fake.calls[1].prompt


async def test_persistent_composition_failure_fails_at_slide_composer():
    def compose(draft: TopicDraft) -> None:
        raise TopicCompositionError("Themenbeitrag ergibt 8 Content-Slides")

    fake = FakeLLMClient(json_responses={"topic_writer": [_draft(), _draft()]})

    with pytest.raises(TopicWriterError, match="after retry") as error:
        await write_topic(BRIEF, EXCERPTS, fake, compose=compose)

    assert error.value.step == "slide_composer"
    assert "8 Content-Slides" in str(error.value)
    assert len(fake.calls) == 2


async def test_writer_does_not_retry_authentication_failures():
    fake = FakeLLMClient(
        json_responses={
            "topic_writer": [LLMAuthenticationError("Insufficient credits")]
        }
    )

    with pytest.raises(LLMAuthenticationError, match="Insufficient credits"):
        await write_topic(BRIEF, EXCERPTS, fake)

    assert len(fake.calls) == 1
