"""Ticket-03 orchestrator: plan a protocol into persisted draft Beiträge.

The pipeline plans first, persists the Redaktionsplan and one summary plus zero
to five topic posts, then resolves the finite Organ and retrieves the source
excerpts. Later tickets extend the processing helpers with writers, fact-check,
captions, visuals and rendering.

Safe commit boundaries are deliberate: the plan and draft posts are committed
before Organ/excerpt processing, and the per-post outcome is committed before
``run`` returns. A caller or API can therefore read visible work even when a
later step fails.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import ARTICLES_DIR
from app.core.post_models import EditorialPlan, TopicBrief
from app.models import EditorialPlan as EditorialPlanRow
from app.models import Post, Protocol
from app.services.editorial_planner import plan_protocol
from app.services.llm_client import LLMAuthenticationError, LLMClient
from app.services.organs import UnknownOrganError, resolve_organ
from app.services.protocol_excerpts import (
    MissingSourceAnchor,
    retrieve_source_excerpts,
)

logger = logging.getLogger(__name__)

GENERATOR_VERSION = "post-pipeline-v1"


@dataclass(frozen=True)
class PostRunResult:
    """Outcome for one planned Beitrag after ticket-03 processing."""

    post_id: int
    post_type: str
    slug: str
    status: str
    failed_step: str | None
    error: str | None


@dataclass(frozen=True)
class PostPipelineResult:
    """Lightweight result returned by ``PostPipeline.run``."""

    protocol_id: int
    plan_status: str
    posts: list[PostRunResult] = field(default_factory=list)


class PostPipeline:
    """Stateless planning stage with an injected LLM port and database session."""

    def __init__(
        self,
        llm_client: LLMClient,
        output_dir: Path | str = ARTICLES_DIR,
        generator_version: str = GENERATOR_VERSION,
    ):
        self.llm_client = llm_client
        self.output_dir = Path(output_dir)
        self.generator_version = generator_version

    async def run(self, protocol: Protocol, db: AsyncSession) -> PostPipelineResult:
        plan_row = await self._load_plan_row(db, protocol.id)

        # A ready plan is expensive to rebuild. Reuse it when its posts are
        # present; ticket 08 owns the explicit reprocess/replace semantics.
        if plan_row is not None and plan_row.status == "ready" and plan_row.plan_json:
            plan = self._load_plan(plan_row)
            posts = await self._load_posts(db, protocol.id)
            if plan is not None and self._posts_match_plan(plan, posts):
                return self._result(protocol, plan_row.status, posts)

            if plan is not None:
                posts = await self._replace_posts(db, protocol, plan)
                return await self._process_posts(protocol, db, plan, posts)

        plan = await self._plan_protocol(protocol, db, plan_row)
        if plan is None:
            return self._result(protocol, "failed", [])

        await self._persist_plan(plan_row, protocol, plan, db)
        posts = await self._replace_posts(db, protocol, plan)
        return await self._process_posts(protocol, db, plan, posts)

    # ------------------------------------------------------------------
    # Planning and persistence helpers, reused by later tickets.
    # ------------------------------------------------------------------

    async def _load_plan_row(
        self, db: AsyncSession, protocol_id: int
    ) -> EditorialPlanRow | None:
        result = await db.execute(
            select(EditorialPlanRow).where(
                EditorialPlanRow.protocol_id == protocol_id
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _load_plan(plan_row: EditorialPlanRow) -> EditorialPlan | None:
        try:
            return EditorialPlan.model_validate(plan_row.plan_json)
        except (ValidationError, TypeError, ValueError):
            logger.warning(
                "Stored editorial plan %s is invalid; replanning", plan_row.id
            )
            return None

    async def _plan_protocol(
        self,
        protocol: Protocol,
        db: AsyncSession,
        plan_row: EditorialPlanRow | None,
    ) -> EditorialPlan | None:
        if plan_row is None:
            plan_row = EditorialPlanRow(protocol_id=protocol.id)
            db.add(plan_row)
        plan_row.generator_version = self.generator_version

        try:
            plan = await plan_protocol(protocol, self.llm_client)
        except LLMAuthenticationError:
            raise
        except Exception as exc:
            logger.error("Editorial planner failed for protocol %s: %s", protocol.id, exc)
            plan_row.status = "failed"
            plan_row.failed_step = "planner"
            plan_row.error = str(exc) or exc.__class__.__name__
            plan_row.plan_json = None
            await db.commit()
            return None

        plan_row.status = "ready"
        plan_row.failed_step = None
        plan_row.error = None
        plan_row.plan_json = plan.model_dump(mode="json")
        return plan

    async def _persist_plan(
        self,
        plan_row: EditorialPlanRow | None,
        protocol: Protocol,
        plan: EditorialPlan,
        db: AsyncSession,
    ) -> None:
        # _plan_protocol already added/filled the row; commit plan + posts
        # together so the API never sees a plan without its planned posts.
        await db.flush()

    async def _replace_posts(
        self, db: AsyncSession, protocol: Protocol, plan: EditorialPlan
    ) -> list[Post]:
        await db.execute(
            delete(Post)
            .where(Post.protocol_id == protocol.id)
            .execution_options(synchronize_session=False)
        )
        posts = self._build_posts(protocol, plan)
        db.add_all(posts)
        await db.flush()
        await db.commit()
        return posts

    def _build_posts(self, protocol: Protocol, plan: EditorialPlan) -> list[Post]:
        summary_content = {
            "briefs": [brief.model_dump(mode="json") for brief in plan.summary_briefs],
            "excerpts": [],
        }
        posts = [
            Post(
                protocol_id=protocol.id,
                post_type="summary",
                slug="summary",
                post_index=0,
                title=plan.summary_title,
                content_json=summary_content,
                status="draft",
                generator_version=self.generator_version,
            )
        ]
        for index, brief in enumerate(plan.topic_briefs, start=1):
            posts.append(
                Post(
                    protocol_id=protocol.id,
                    post_type="topic",
                    slug=brief.slug,
                    post_index=index,
                    title=brief.title,
                    content_json={
                        "brief": brief.model_dump(mode="json"),
                        "excerpts": [],
                    },
                    status="draft",
                    generator_version=self.generator_version,
                )
            )
        return posts

    # ------------------------------------------------------------------
    # Organ resolution, deterministic retrieval and per-post outcomes.
    # ------------------------------------------------------------------

    async def _process_posts(
        self,
        protocol: Protocol,
        db: AsyncSession,
        plan: EditorialPlan,
        posts: list[Post],
    ) -> PostPipelineResult:
        try:
            resolve_organ(protocol.title)
        except UnknownOrganError as exc:
            for post in posts:
                post.status = "failed"
                post.failed_step = "organ"
                post.error = str(exc)
            return await self._commit_and_result(protocol, db, "ready", posts)

        summary_post = next(
            (post for post in posts if post.post_type == "summary"), None
        )
        if summary_post is not None:
            self._retrieve_summary_excerpts(protocol, plan, summary_post)

        topic_by_slug = {
            post.slug: post for post in posts if post.post_type == "topic"
        }
        for brief in plan.topic_briefs:
            post = topic_by_slug.get(brief.slug)
            if post is None:
                continue
            self._retrieve_topic_excerpts(protocol, brief, post)

        return await self._commit_and_result(protocol, db, "ready", posts)

    @staticmethod
    def _retrieve_summary_excerpts(
        protocol: Protocol, plan: EditorialPlan, post: Post
    ) -> None:
        anchors = [
            anchor
            for brief in plan.summary_briefs
            for anchor in brief.source_anchors
        ]
        try:
            excerpts = retrieve_source_excerpts(protocol.pdf_text, anchors)
        except MissingSourceAnchor as exc:
            post.status = "failed"
            post.failed_step = "source_retrieval"
            post.error = str(exc)
            return

        post.content_json = {
            "briefs": [brief.model_dump(mode="json") for brief in plan.summary_briefs],
            "excerpts": [excerpt.model_dump(mode="json") for excerpt in excerpts],
        }

    @staticmethod
    def _retrieve_topic_excerpts(
        protocol: Protocol, brief: TopicBrief, post: Post
    ) -> None:
        try:
            excerpts = retrieve_source_excerpts(
                protocol.pdf_text, brief.source_anchors
            )
        except MissingSourceAnchor as exc:
            post.status = "failed"
            post.failed_step = "source_retrieval"
            post.error = str(exc)
            return

        post.content_json = {
            "brief": brief.model_dump(mode="json"),
            "excerpts": [excerpt.model_dump(mode="json") for excerpt in excerpts],
        }

    async def _commit_and_result(
        self,
        protocol: Protocol,
        db: AsyncSession,
        plan_status: str,
        posts: list[Post],
    ) -> PostPipelineResult:
        await db.flush()
        result = self._result(protocol, plan_status, posts)
        await db.commit()
        return result

    # ------------------------------------------------------------------
    # Result/read helpers.
    # ------------------------------------------------------------------

    async def _load_posts(self, db: AsyncSession, protocol_id: int) -> list[Post]:
        result = await db.execute(
            select(Post)
            .where(Post.protocol_id == protocol_id)
            .order_by(Post.post_index)
        )
        return list(result.scalars().all())

    @staticmethod
    def _posts_match_plan(plan: EditorialPlan, posts: list[Post]) -> bool:
        expected = {("summary", "summary")}
        expected.update(("topic", brief.slug) for brief in plan.topic_briefs)
        present = {(post.post_type, post.slug) for post in posts}
        return present == expected and len(posts) == len(expected)

    @staticmethod
    def _result(
        protocol: Protocol, plan_status: str, posts: list[Post]
    ) -> PostPipelineResult:
        return PostPipelineResult(
            protocol_id=protocol.id,
            plan_status=plan_status,
            posts=[
                PostRunResult(
                    post_id=post.id,
                    post_type=post.post_type,
                    slug=post.slug,
                    status=post.status,
                    failed_step=post.failed_step,
                    error=post.error,
                )
                for post in sorted(posts, key=lambda item: item.post_index)
            ],
        )
