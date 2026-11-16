"""Behaviour tests for the shared fact-check and repair gate."""

import pytest

from app.core.post_models import FactCheckResult, SourceExcerpt, SummaryDraft
from app.services.fact_checker import (
    FactCheckError,
    FactCheckFailedError,
    enforce_fact_check,
)
from app.services.llm_client import LLMAuthenticationError, LLMSchemaError
from tests.support.fake_llm import FakeLLMClient

PROTOCOL_TEXT = (
    "TOP 1 Begrüßung\n"
    "Der Vorsitzende eröffnet die Sitzung.\n"
    "\n"
    "TOP 5 Haushalt\n"
    "Der Rat beschließt den Haushalt einstimmig.\n"
)

EXCERPTS = [
    SourceExcerpt(
        anchor="Der Rat beschließt den Haushalt einstimmig.",
        excerpt="Der Rat beschließt den Haushalt einstimmig.",
    )
]


def _draft(body: str = "x" * 120) -> SummaryDraft:
    return SummaryDraft(
        cover_title="Was der Rat in Rosdorf entschieden hat",
        points=[
            {
                "kicker": "Haushalt",
                "heading": "Der Rat hat den Haushalt beschlossen",
                "body": body,
            },
            {
                "kicker": "Radweg",
                "heading": "Der Radweg kommt im Sommer",
                "body": "y" * 120,
            },
        ],
    )


async def _gate(draft, fake, **overrides):
    arguments = {
        "draft_schema": SummaryDraft,
        "fact_check_role": "summary_fact_check",
        "repair_role": "summary_repair",
    }
    arguments.update(overrides)
    return await enforce_fact_check(draft, EXCERPTS, fake, **arguments)


async def test_empty_issue_list_passes_without_a_repair_call():
    draft = _draft()
    fake = FakeLLMClient(
        json_responses={"summary_fact_check": [FactCheckResult(issues=[])]}
    )

    outcome = await _gate(draft, fake)

    assert outcome.draft == draft
    assert outcome.repaired is False
    assert outcome.issues == ()
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call.role == "summary_fact_check"
    assert call.schema is FactCheckResult
    assert draft.cover_title in call.prompt
    assert EXCERPTS[0].excerpt in call.prompt
    assert PROTOCOL_TEXT not in call.prompt


async def test_issues_trigger_one_repair_and_a_second_check():
    draft = _draft()
    repaired = _draft(body="z" * 120)
    issues = ["Die Zahl 12 ist in den Quellen nicht belegt."]
    fake = FakeLLMClient(
        json_responses={
            "summary_fact_check": [
                FactCheckResult(issues=issues),
                FactCheckResult(issues=[]),
            ],
            "summary_repair": [repaired],
        }
    )

    outcome = await _gate(draft, fake)

    assert outcome.draft == repaired
    assert outcome.repaired is True
    assert outcome.issues == ()
    assert [call.role for call in fake.calls] == [
        "summary_fact_check",
        "summary_repair",
        "summary_fact_check",
    ]
    assert fake.calls[1].schema is SummaryDraft
    assert issues[0] in fake.calls[1].prompt
    assert EXCERPTS[0].excerpt in fake.calls[1].prompt
    assert PROTOCOL_TEXT not in fake.calls[1].prompt
    assert repaired.cover_title in fake.calls[2].prompt


async def test_remaining_issues_after_repair_are_a_hard_failure():
    issues = ["Die Zahl 12 ist in den Quellen nicht belegt."]
    fake = FakeLLMClient(
        json_responses={
            "summary_fact_check": [
                FactCheckResult(issues=issues),
                FactCheckResult(issues=issues),
            ],
            "summary_repair": [_draft()],
        }
    )

    with pytest.raises(FactCheckFailedError) as error:
        await _gate(_draft(), fake)

    assert error.value.step == "fact_check"
    assert error.value.issues == issues
    assert len(fake.calls) == 3


async def test_repair_call_failure_reports_the_repair_step():
    fake = FakeLLMClient(
        json_responses={
            "summary_fact_check": [FactCheckResult(issues=["Ein Problem"])],
            "summary_repair": [LLMSchemaError("repair returned bad JSON")],
        }
    )

    with pytest.raises(FactCheckError) as error:
        await _gate(_draft(), fake)

    assert error.value.step == "repair"
    assert "repair returned bad JSON" in str(error.value)
    assert len(fake.calls) == 2


async def test_second_check_failure_reports_the_fact_check_step():
    fake = FakeLLMClient(
        json_responses={
            "summary_fact_check": [
                FactCheckResult(issues=["Ein Problem"]),
                LLMSchemaError("second check failed"),
            ],
            "summary_repair": [_draft()],
        }
    )

    with pytest.raises(FactCheckError) as error:
        await _gate(_draft(), fake)

    assert error.value.step == "fact_check"
    assert "second check failed" in str(error.value)


async def test_authentication_failures_propagate_immediately():
    fake = FakeLLMClient(
        json_responses={
            "summary_fact_check": [LLMAuthenticationError("Insufficient credits")]
        }
    )

    with pytest.raises(LLMAuthenticationError, match="Insufficient credits"):
        await _gate(_draft(), fake)

    assert len(fake.calls) == 1
