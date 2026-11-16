"""Scheduler selection and stop behavior against a real PostgreSQL schema."""

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.scheduler as scheduler_module
from app.core.post_models import (
    EditorialPlan,
    SummaryBrief,
    TopicBrief,
)
from app.models import EditorialPlan as EditorialPlanRow
from app.models import Post, Protocol
from app.services.llm_client import LLMAuthenticationError
from app.services.post_pipeline import PostPipeline
from tests.support.fake_llm import FakeLLMClient

pytestmark = pytest.mark.integration

ANCHOR = "Der Rat beschließt den Haushalt einstimmig."


def _plan() -> EditorialPlan:
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
                slug="haushalt",
                title="Haushalt beschlossen",
                focus="Der Beschluss",
                relevance="Wichtig für alle Ortsteile.",
                source_anchors=[ANCHOR],
            )
        ],
    )


async def _add_protocol(session, getfile_id: int, *, processed=False):
    protocol = Protocol(
        session_date=date(2024, 1, 15),
        title="Gemeinderat",
        getfile_id=getfile_id,
        pdf_text=f"TOP 1 Haushalt\n{ANCHOR}\n",
        processed=processed,
    )
    session.add(protocol)
    await session.flush()
    return protocol


async def _add_terminal_posts(session, protocol, *, topic_status="ready"):
    session.add_all(
        [
            Post(
                protocol_id=protocol.id,
                post_type="summary",
                slug="summary",
                post_index=0,
                title="Summary",
                status="ready",
            ),
            Post(
                protocol_id=protocol.id,
                post_type="topic",
                slug="haushalt",
                post_index=1,
                title="Haushalt",
                status=topic_status,
                failed_step="fact_check"
                if topic_status == "failed"
                else None,
                error="unsupported claim"
                if topic_status == "failed"
                else None,
            ),
        ]
    )
    await session.flush()


async def _add_ready_plan(session, protocol, status="ready"):
    session.add(
        EditorialPlanRow(
            protocol_id=protocol.id,
            status=status,
            plan_json=_plan().model_dump(mode="json")
            if status == "ready"
            else None,
            failed_step="planner" if status == "failed" else None,
            error="planner broke" if status == "failed" else None,
        )
    )
    await session.flush()


class _RecordingPipeline(PostPipeline):
    runs: list[int] = []

    async def run(self, protocol, db):
        type(self).runs.append(protocol.id)
        return await super().run(protocol, db)


async def _run_job(monkeypatch, engine, fake):
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(
        scheduler_module, "AsyncSessionLocal", session_factory
    )
    monkeypatch.setattr(
        scheduler_module, "OpenRouterLLMClient", lambda: fake
    )
    _RecordingPipeline.runs = []
    monkeypatch.setattr(
        scheduler_module, "PostPipeline", _RecordingPipeline
    )
    await scheduler_module.process_protocols_wrapper()
    return list(_RecordingPipeline.runs)


async def test_job_selects_unprocessed_protocols_and_skips_failed_plans(
    postgres_engine, monkeypatch
):
    session_factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with session_factory() as session:
        terminal = await _add_protocol(session, 1)
        await _add_ready_plan(session, terminal)
        await _add_terminal_posts(session, terminal, topic_status="failed")
        failed_plan = await _add_protocol(session, 2)
        await _add_ready_plan(session, failed_plan, status="failed")
        already_processed = await _add_protocol(session, 3, processed=True)
        await session.commit()
        terminal_id = terminal.id
        failed_plan_id = failed_plan.id
        processed_id = already_processed.id

    fake = FakeLLMClient()
    runs = await _run_job(monkeypatch, postgres_engine, fake)

    assert runs == [terminal_id]

    async with session_factory() as session:
        terminal = await session.get(Protocol, terminal_id)
        failed_plan = await session.get(Protocol, failed_plan_id)
        already = await session.get(Protocol, processed_id)
        failed_post = (
            await session.execute(
                select(Post).where(
                    Post.protocol_id == terminal_id,
                    Post.post_type == "topic",
                )
            )
        ).scalar_one()
        failed_plan_row = (
            await session.execute(
                select(EditorialPlanRow).where(
                    EditorialPlanRow.protocol_id == failed_plan_id
                )
            )
        ).scalar_one()

    assert terminal.processed is True
    assert failed_post.status == "failed"
    assert failed_post.failed_step == "fact_check"
    assert failed_plan.processed is False
    assert failed_plan_row.status == "failed"
    assert already.processed is True
    assert fake.calls == []

    # A second run selects nothing: the terminal protocol is now processed and
    # the failed plan is skipped instead of being replanned automatically.
    assert await _run_job(monkeypatch, postgres_engine, fake) == []


async def test_job_stops_immediately_on_authentication_error(
    postgres_engine, monkeypatch
):
    session_factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with session_factory() as session:
        first = await _add_protocol(session, 11)
        second = await _add_protocol(session, 12)
        await session.commit()
        first_id = first.id
        second_id = second.id

    fake = FakeLLMClient(
        json_responses={
            "planner": [LLMAuthenticationError("Insufficient credits")]
        }
    )
    runs = await _run_job(monkeypatch, postgres_engine, fake)

    assert runs == [first_id]
    assert len(fake.calls_for("planner")) == 1

    async with session_factory() as session:
        first = await session.get(Protocol, first_id)
        second = await session.get(Protocol, second_id)
        plan_rows = list(
            (
                await session.execute(select(EditorialPlanRow))
            ).scalars().all()
        )

    assert first.processed is False
    assert second.processed is False
    assert plan_rows == []
