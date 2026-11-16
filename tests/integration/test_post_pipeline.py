"""End-to-end ticket-03 behaviour against a real PostgreSQL schema."""

from datetime import date

import httpx
import pytest
from sqlalchemy import select

from app.core.post_models import EditorialPlan, SummaryBrief, TopicBrief
from app.database import get_db
from app.main import app
from app.models import EditorialPlan as EditorialPlanRow
from app.models import Post, Protocol
from app.services.llm_client import LLMAuthenticationError, LLMSchemaError
from app.services.post_pipeline import PostPipeline
from tests.support.fake_llm import FakeLLMClient

pytestmark = pytest.mark.integration

PROTOCOL_TEXT = (
    "TOP 1 Begrüßung\n"
    "Der Vorsitzende eröffnet die Sitzung.\n"
    "\n"
    "TOP 2 Haushalt\n"
    "Der Rat beschließt den Haushalt einstimmig.\n"
    "Die Verwaltung zahlt die Mittel im Frühjahr aus.\n"
    "\n"
    "TOP 3 Radweg\n"
    "Der Radweg an der Hauptstraße wird im Sommer gebaut.\n"
)

SUMMARY_ANCHOR_1 = "Der Rat beschließt den Haushalt einstimmig."
SUMMARY_ANCHOR_2 = "Der Radweg an der Hauptstraße wird im Sommer gebaut."


def _plan(
    *,
    summary_anchors: list[str] | None = None,
    topic_briefs: list[TopicBrief] | None = None,
) -> EditorialPlan:
    return EditorialPlan(
        summary_focus="Haushalt und Radweg",
        summary_title="Was der Rat in Rosdorf entschieden hat",
        summary_briefs=[
            SummaryBrief(
                point="Der Haushalt wurde einstimmig beschlossen.",
                relevance="Die Mittel sind für alle Ortsteile wichtig.",
                source_anchors=summary_anchors or [SUMMARY_ANCHOR_1],
            ),
            SummaryBrief(
                point="Der Radweg an der Hauptstraße wird gebaut.",
                relevance="Das verbessert die Verbindung im Ort.",
                source_anchors=[SUMMARY_ANCHOR_2],
            ),
        ],
        topic_briefs=topic_briefs
        if topic_briefs is not None
        else [
            TopicBrief(
                slug="haushalt",
                title="Haushalt beschlossen",
                focus="Die wichtigsten Posten",
                relevance="Die Entscheidung betrifft alle Ortsteile.",
                source_anchors=[SUMMARY_ANCHOR_1],
            ),
            TopicBrief(
                slug="radweg",
                title="Radweg kommt im Sommer",
                focus="Der neue Weg an der Hauptstraße",
                relevance="Bessere Verbindung für den Alltag.",
                source_anchors=[SUMMARY_ANCHOR_2],
            ),
        ],
    )


async def _add_protocol(
    session, *, title: str = "Gemeinderat", getfile_id: int = 1
) -> Protocol:
    protocol = Protocol(
        session_date=date(2024, 1, 15),
        title=title,
        getfile_id=getfile_id,
        pdf_text=PROTOCOL_TEXT,
    )
    session.add(protocol)
    await session.flush()
    return protocol


async def _run(
    session,
    tmp_path,
    *,
    plan: EditorialPlan | None = None,
    title: str = "Gemeinderat",
):
    fake = FakeLLMClient()
    if plan is not None:
        fake.script_json("planner", plan)
    protocol = await _add_protocol(session, title=title)
    pipeline = PostPipeline(fake, output_dir=tmp_path)
    result = await pipeline.run(protocol, session)
    return protocol, result, fake


async def _posts(session, protocol: Protocol) -> list[Post]:
    result = await session.execute(
        select(Post)
        .where(Post.protocol_id == protocol.id)
        .order_by(Post.post_index)
    )
    return list(result.scalars().all())


async def _plan_row(session, protocol: Protocol) -> EditorialPlanRow:
    result = await session.execute(
        select(EditorialPlanRow).where(EditorialPlanRow.protocol_id == protocol.id)
    )
    return result.scalar_one()


async def test_pipeline_persists_plan_and_draft_posts_with_briefs_and_excerpts(
    postgres_session, tmp_path
):
    plan = _plan()
    protocol, result, fake = await _run(postgres_session, tmp_path, plan=plan)

    plan_row = await _plan_row(postgres_session, protocol)
    posts = await _posts(postgres_session, protocol)

    assert plan_row.status == "ready"
    assert plan_row.failed_step is None
    assert plan_row.error is None
    assert plan_row.generator_version == "post-pipeline-v1"
    assert plan_row.plan_json["summary_title"] == plan.summary_title
    assert len(plan_row.plan_json["topic_briefs"]) == 2

    assert [(post.post_type, post.slug, post.post_index) for post in posts] == [
        ("summary", "summary", 0),
        ("topic", "haushalt", 1),
        ("topic", "radweg", 2),
    ]
    assert [post.title for post in posts] == [
        "Was der Rat in Rosdorf entschieden hat",
        "Haushalt beschlossen",
        "Radweg kommt im Sommer",
    ]
    assert [post.status for post in posts] == ["draft", "draft", "draft"]
    assert [post.failed_step for post in posts] == [None, None, None]
    assert {post.generator_version for post in posts} == {"post-pipeline-v1"}

    summary = posts[0]
    assert len(summary.content_json["briefs"]) == 2
    assert summary.content_json["excerpts"]
    assert any(
        "Der Rat beschließt den Haushalt" in excerpt["excerpt"]
        for excerpt in summary.content_json["excerpts"]
    )

    haushalt = posts[1]
    assert haushalt.content_json["brief"]["slug"] == "haushalt"
    assert haushalt.content_json["excerpts"][0]["anchor"] == SUMMARY_ANCHOR_1

    assert result.plan_status == "ready"
    assert [post.status for post in result.posts] == ["draft", "draft", "draft"]
    assert protocol.processed is False

    assert len(fake.calls) == 1
    assert fake.calls[0].role == "planner"
    assert PROTOCOL_TEXT in fake.calls[0].prompt

    # The planned posts are visible through the ticket-02 read API.
    async def override_get_db():
        yield postgres_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            list_response = await client.get(f"/api/protocols/{protocol.id}/posts")
            detail_response = await client.get(f"/api/posts/{haushalt.id}")
    finally:
        app.dependency_overrides.clear()

    assert list_response.status_code == 200
    listed = list_response.json()
    assert [post["slug"] for post in listed] == ["summary", "haushalt", "radweg"]
    assert [post["status"] for post in listed] == ["draft", "draft", "draft"]

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["title"] == "Haushalt beschlossen"
    assert detail["content_json"]["brief"]["slug"] == "haushalt"
    assert detail["content_json"]["excerpts"][0]["anchor"] == SUMMARY_ANCHOR_1


async def test_unknown_organ_fails_every_planned_post_but_keeps_the_plan(
    postgres_session, tmp_path
):
    protocol, result, _ = await _run(
        postgres_session, tmp_path, plan=_plan(), title="Jugendausschuss"
    )

    plan_row = await _plan_row(postgres_session, protocol)
    posts = await _posts(postgres_session, protocol)

    assert plan_row.status == "ready"
    assert plan_row.failed_step is None
    assert [post.status for post in posts] == ["failed", "failed", "failed"]
    assert [post.failed_step for post in posts] == ["organ", "organ", "organ"]
    assert all("Unknown organ" in post.error for post in posts)
    assert [post.status for post in result.posts] == ["failed", "failed", "failed"]


async def test_missing_summary_anchor_fails_only_the_summary(
    postgres_session, tmp_path
):
    plan = _plan(summary_anchors=["Dieser Satz steht nicht im Protokoll"])
    protocol, result, _ = await _run(postgres_session, tmp_path, plan=plan)

    summary, haushalt, radweg = await _posts(postgres_session, protocol)

    assert summary.status == "failed"
    assert summary.failed_step == "source_retrieval"
    assert "Quellenanker" in summary.error
    assert len(summary.content_json["briefs"]) == 2
    assert summary.content_json["excerpts"] == []
    assert haushalt.status == "draft"
    assert radweg.status == "draft"
    assert [post.status for post in result.posts] == ["failed", "draft", "draft"]


async def test_missing_topic_anchor_fails_only_that_topic(postgres_session, tmp_path):
    plan = _plan(
        topic_briefs=[
            TopicBrief(
                slug="haushalt",
                title="Haushalt beschlossen",
                focus="Die wichtigsten Posten",
                relevance="Relevanz für alle Ortsteile.",
                source_anchors=["Dieser Satz steht nicht im Protokoll"],
            ),
            TopicBrief(
                slug="radweg",
                title="Radweg kommt im Sommer",
                focus="Der neue Weg",
                relevance="Bessere Verbindung.",
                source_anchors=[SUMMARY_ANCHOR_2],
            ),
        ]
    )
    protocol, result, _ = await _run(postgres_session, tmp_path, plan=plan)

    summary, haushalt, radweg = await _posts(postgres_session, protocol)

    assert summary.status == "draft"
    assert haushalt.status == "failed"
    assert haushalt.failed_step == "source_retrieval"
    assert radweg.status == "draft"
    assert radweg.content_json["brief"]["slug"] == "radweg"
    assert [post.status for post in result.posts] == ["draft", "failed", "draft"]


async def test_planner_schema_failure_marks_the_plan_failed_without_posts(
    postgres_session, tmp_path
):
    fake = FakeLLMClient(
        json_responses={"planner": [LLMSchemaError("planner returned bad JSON")]}
    )
    protocol = await _add_protocol(postgres_session)
    pipeline = PostPipeline(fake, output_dir=tmp_path)

    result = await pipeline.run(protocol, postgres_session)

    plan_row = await _plan_row(postgres_session, protocol)
    assert plan_row.status == "failed"
    assert plan_row.failed_step == "planner"
    assert "planner returned bad JSON" in plan_row.error
    assert await _posts(postgres_session, protocol) == []
    assert result.plan_status == "failed"
    assert result.posts == []
    assert protocol.processed is False


async def test_planner_auth_failure_propagates_immediately(postgres_session, tmp_path):
    fake = FakeLLMClient(
        json_responses={"planner": [LLMAuthenticationError("Insufficient credits")]}
    )
    protocol = await _add_protocol(postgres_session)
    pipeline = PostPipeline(fake, output_dir=tmp_path)

    with pytest.raises(LLMAuthenticationError, match="Insufficient credits"):
        await pipeline.run(protocol, postgres_session)

    assert len(fake.calls) == 1
