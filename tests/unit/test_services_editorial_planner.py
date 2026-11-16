"""Tests for the stateless editorial planner role."""

from datetime import date
from types import SimpleNamespace

import pytest

from app.core.post_models import EditorialPlan, SummaryBrief, TopicBrief
from app.services.editorial_planner import plan_protocol
from tests.support.fake_llm import FakeLLMClient


def _plan() -> EditorialPlan:
    return EditorialPlan(
        summary_focus="Haushalt",
        summary_title="Was der Rat entschieden hat",
        summary_briefs=[
            SummaryBrief(
                point="Der Haushalt wurde beschlossen.",
                relevance="Wichtig für alle Ortsteile.",
                source_anchors=["Der Rat beschließt den Haushalt"],
            ),
            SummaryBrief(
                point="Der Radweg kommt.",
                relevance="Bessere Verbindung.",
                source_anchors=["Der Radweg wird gebaut"],
            ),
        ],
        topic_briefs=[
            TopicBrief(
                slug="haushalt",
                title="Haushalt beschlossen",
                focus="Die wichtigsten Posten",
                relevance="Relevanz für alle Ortsteile",
                source_anchors=["Der Rat beschließt den Haushalt"],
            )
        ],
    )


async def test_planner_gets_the_full_protocol_and_returns_the_validated_plan():
    protocol_text = "TOP 1 Begrüßung\n" + ("Sehr langer Protokolltext. " * 500)
    protocol = SimpleNamespace(
        title="Gemeinderat",
        session_date=date(2024, 1, 15),
        pdf_text=protocol_text,
    )
    expected = _plan()
    fake = FakeLLMClient(json_responses={"planner": [expected]})

    result = await plan_protocol(protocol, fake)

    assert result == expected
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call.role == "planner"
    assert call.schema is EditorialPlan
    assert protocol_text in call.prompt
    assert "Gemeinderat" in call.prompt
    assert "2024-01-15" in call.prompt


async def test_planner_propagates_llm_errors():
    from app.services.llm_client import LLMSchemaError

    protocol = SimpleNamespace(
        title="Gemeinderat",
        session_date=date(2024, 1, 15),
        pdf_text="TOP 1 Test",
    )
    fake = FakeLLMClient(json_responses={"planner": [LLMSchemaError("bad schema")]})

    with pytest.raises(LLMSchemaError, match="bad schema"):
        await plan_protocol(protocol, fake)
