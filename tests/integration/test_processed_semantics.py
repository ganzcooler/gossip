"""Terminal ``Protocol.processed`` semantics against PostgreSQL."""

from datetime import date

import pytest
from sqlalchemy import select

from app.core.post_models import (
    EditorialPlan,
    SummaryBrief,
    TopicBrief,
)
from app.models import EditorialPlan as EditorialPlanRow
from app.models import Post, Protocol
from app.services.post_pipeline import PostPipeline
from tests.support.fake_llm import FakeLLMClient

pytestmark = pytest.mark.integration

ANCHOR = "Der Rat beschließt den Haushalt einstimmig."


def _plan(topic_slugs: list[str] | None = None) -> EditorialPlan:
    slugs = topic_slugs if topic_slugs is not None else ["haushalt"]
    return EditorialPlan(
        summary_focus="Haushalt",
        summary_title="Was der Rat in Rosdorf entschieden hat",
        summary_briefs=[
            SummaryBrief(
                point="Der Haushalt wurde beschlossen.",
                relevance="Wichtig für alle Ortsteile.",
                source_anchors=[ANCHOR],
            ),
            SummaryBrief(
                point="Der Radweg wird gebaut.",
                relevance="Wichtig für alle Ortsteile.",
                source_anchors=[ANCHOR],
            ),
        ],
        topic_briefs=[
            TopicBrief(
                slug=slug,
                title=f"Thema {slug}",
                focus="Der Beschluss",
                relevance="Wichtig für alle Ortsteile.",
                source_anchors=[ANCHOR],
            )
            for slug in slugs
        ],
    )


async def _protocol(session) -> Protocol:
    protocol = Protocol(
        session_date=date(2024, 1, 15),
        title="Gemeinderat",
        getfile_id=81,
        pdf_text=f"TOP 1 Haushalt\n{ANCHOR}\n",
    )
    session.add(protocol)
    await session.flush()
    return protocol


async def _plan_row(
    session, protocol: Protocol, *, status: str = "ready", plan: EditorialPlan | None = None
) -> EditorialPlanRow:
    row = EditorialPlanRow(
        protocol_id=protocol.id,
        status=status,
        plan_json=(plan or _plan()).model_dump(mode="json")
        if status == "ready"
        else None,
        failed_step="planner" if status == "failed" else None,
        error="planner failed" if status == "failed" else None,
    )
    session.add(row)
    await session.flush()
    return row


async def _post(
    session,
    protocol: Protocol,
    *,
    post_type: str,
    slug: str,
    index: int,
    status: str,
) -> Post:
    post = Post(
        protocol_id=protocol.id,
        post_type=post_type,
        slug=slug,
        post_index=index,
        title=slug,
        status=status,
    )
    session.add(post)
    await session.flush()
    return post


async def _recompute(session, protocol: Protocol) -> bool:
    pipeline = PostPipeline(FakeLLMClient(), output_dir="/tmp/unused")
    return await pipeline.recompute_processed(protocol, session)


async def test_planner_failure_is_not_processed(postgres_session):
    protocol = await _protocol(postgres_session)
    await _plan_row(postgres_session, protocol, status="failed")

    assert await _recompute(postgres_session, protocol) is False


async def test_missing_plan_is_not_processed(postgres_session):
    protocol = await _protocol(postgres_session)

    assert await _recompute(postgres_session, protocol) is False


async def test_all_terminal_posts_are_processed_even_with_failed_topic(
    postgres_session,
):
    protocol = await _protocol(postgres_session)
    await _plan_row(postgres_session, protocol)
    await _post(
        postgres_session,
        protocol,
        post_type="summary",
        slug="summary",
        index=0,
        status="ready",
    )
    await _post(
        postgres_session,
        protocol,
        post_type="topic",
        slug="haushalt",
        index=1,
        status="failed",
    )

    assert await _recompute(postgres_session, protocol) is True


async def test_failed_summary_does_not_block_terminal_topics(postgres_session):
    protocol = await _protocol(postgres_session)
    await _plan_row(postgres_session, protocol)
    await _post(
        postgres_session,
        protocol,
        post_type="summary",
        slug="summary",
        index=0,
        status="failed",
    )
    await _post(
        postgres_session,
        protocol,
        post_type="topic",
        slug="haushalt",
        index=1,
        status="ready",
    )

    assert await _recompute(postgres_session, protocol) is True


async def test_draft_or_missing_post_blocks_processed(postgres_session):
    protocol = await _protocol(postgres_session)
    await _plan_row(postgres_session, protocol)
    summary = await _post(
        postgres_session,
        protocol,
        post_type="summary",
        slug="summary",
        index=0,
        status="ready",
    )

    assert await _recompute(postgres_session, protocol) is False

    topic = await _post(
        postgres_session,
        protocol,
        post_type="topic",
        slug="haushalt",
        index=1,
        status="draft",
    )
    assert await _recompute(postgres_session, protocol) is False

    topic.status = "failed"
    await postgres_session.flush()
    assert await _recompute(postgres_session, protocol) is True

    await postgres_session.delete(topic)
    await postgres_session.flush()
    assert await _recompute(postgres_session, protocol) is False
    assert summary.status == "ready"


async def test_draft_summary_blocks_processed(postgres_session):
    protocol = await _protocol(postgres_session)
    await _plan_row(postgres_session, protocol)
    await _post(
        postgres_session,
        protocol,
        post_type="summary",
        slug="summary",
        index=0,
        status="draft",
    )

    assert await _recompute(postgres_session, protocol) is False


async def test_recompute_persists_the_flag(postgres_session):
    protocol = await _protocol(postgres_session)
    await _plan_row(postgres_session, protocol)
    await _post(
        postgres_session,
        protocol,
        post_type="summary",
        slug="summary",
        index=0,
        status="failed",
    )
    await _post(
        postgres_session,
        protocol,
        post_type="topic",
        slug="haushalt",
        index=1,
        status="failed",
    )
    await postgres_session.commit()

    assert await _recompute(postgres_session, protocol) is True
    await postgres_session.commit()

    result = await postgres_session.execute(
        select(Protocol.processed).where(Protocol.id == protocol.id)
    )
    assert result.scalar_one() is True
