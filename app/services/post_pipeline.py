"""Stateless post-pipeline orchestrator: plan, write and render Beiträge.

The pipeline plans first, persists the Redaktionsplan and one Summary-Beitrag
plus zero to five Themenbeiträge, then resolves the finite Organ and retrieves
the source excerpts. The Summary branch writes its content once, then runs
visual prompts, cover image generation, the 9:16 renderer and the caption
file. Each topic
branch writes its own article, then runs topic visual prompts, cover/pair/single
image generation, the 4:5 renderer and the caption file. Manual retry and
protocol reprocess reuse cached upstream artifacts and enforce the terminal
``Protocol.processed`` state.

Safe commit boundaries are deliberate: the plan and draft posts are committed
before Organ/excerpt processing, and each post's outcome is committed before
the next branch continues. A caller or API can therefore read visible work even
when a later step fails.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import config
from app.core.config import ARTICLES_DIR
from app.core.post_models import (
    EditorialPlan,
    SourceExcerpt,
    SummaryBrief,
    SummaryDraft,
    TopicBrief,
    TopicDraft,
)
from app.models import EditorialPlan as EditorialPlanRow
from app.models import Post, PostAsset, PostSlide, Protocol
from app.services.caption_writer import (
    compose_caption,
    write_caption_body,
)
from app.services.editorial_planner import plan_protocol
from app.services.fact_checker import (
    FactCheckError,
    FactCheckFailedError,
    fact_check_json,
    enforce_fact_check,
)
from app.services.output_cleanup import (
    cleanup_protocol_output,
    cleanup_summary_output,
    cleanup_topic_output,
)
from app.services.image_generation import (
    generate_summary_cover,
    generate_topic_cover,
    generate_topic_pair_art,
    generate_topic_single_art,
)
from app.services.llm_client import LLMAuthenticationError, LLMClient
from app.services.organs import UnknownOrganError, resolve_organ
from app.services.post_renderer import (
    render_summary_frames,
    summary_composition_from_stored,
    write_summary_output,
)
from app.services.protocol_excerpts import (
    MissingSourceAnchor,
    retrieve_source_excerpts,
)
from app.services.slide_composer import (
    SummaryComposition,
    TopicComposition,
    compose_summary_slides,
    compose_topic_slides,
    render_summary_markdown,
)
from app.services.summary_writer import write_summary
from app.services.topic_renderer import (
    render_topic_frames,
    topic_composition_from_stored,
    write_topic_output,
)
from app.services.topic_writer import TopicWriterError, write_topic
from app.services.visual_prompts import (
    write_summary_visual_prompts,
    write_topic_visual_prompts,
)

logger = logging.getLogger(__name__)

GENERATOR_VERSION = "post-pipeline-v1"


@dataclass(frozen=True)
class PostRunResult:
    """Outcome for one planned Beitrag after a pipeline run."""

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
        # present and let _process_posts continue any still-draft branches;
        # explicit reprocess and replace semantics live in the retry methods.
        if plan_row is not None and plan_row.status == "ready" and plan_row.plan_json:
            plan = self._load_plan(plan_row)
            posts = await self._load_posts(db, protocol.id)
            if plan is not None and self._posts_match_plan(plan, posts):
                return await self._process_posts(protocol, db, plan, posts)

            if plan is not None:
                posts = await self._replace_posts(db, protocol, plan)
                return await self._process_posts(protocol, db, plan, posts)

        plan = await self._plan_protocol(protocol, db, plan_row)
        if plan is None:
            await self.recompute_processed(protocol, db)
            await db.commit()
            return self._result(protocol, "failed", [])

        # _plan_protocol already added/filled the row; flush plan + posts
        # together so the API never sees a plan without its planned posts.
        await db.flush()
        posts = await self._replace_posts(db, protocol, plan)
        return await self._process_posts(protocol, db, plan, posts)

    # ------------------------------------------------------------------
    # Manual retry and reprocess state machine.
    # ------------------------------------------------------------------

    async def retry_post(
        self, post: Post, db: AsyncSession, *, force: bool = False
    ) -> PostRunResult:
        """Reset one Beitrag and rerun it from its ``failed_step``.

        Cached drafts, compositions, fact-check results, captions and visual
        prompts are reused. ``force=True`` clears only this post's generated
        content and output and restarts at the writer, keeping the
        Redaktionsplan, briefs and source excerpts.
        """
        protocol = await self._load_protocol(db, post.protocol_id)
        if protocol is None:
            raise ValueError(f"Protocol {post.protocol_id} does not exist")

        plan_row = await self._load_plan_row(db, protocol.id)
        plan = (
            self._load_plan(plan_row)
            if plan_row is not None and plan_row.status == "ready"
            else None
        )
        if plan is None:
            post.status = "failed"
            post.failed_step = "planner"
            post.error = "No ready editorial plan for this post"
            await self._commit_post_outcome(db, post)
            return self._result(protocol, "failed", [post]).posts[0]

        if force:
            self._keep_post_inputs(post, plan)
            await self._delete_post_artifacts(db, post)
            if post.post_type == "summary":
                cleanup_summary_output(self.output_dir, protocol)
            else:
                cleanup_topic_output(self.output_dir, protocol, post.slug)
            stage = "writer"
        else:
            stage = self._stage_from_failed_step(post)

        post.status = "draft"
        post.failed_step = None
        post.error = None
        await db.flush()

        try:
            await self._retry_post_from_stage(
                protocol, db, plan, post, stage
            )
        except LLMAuthenticationError:
            raise

        if post.status == "draft":
            post.status = "failed"
            post.failed_step = post.failed_step or "render"
            post.error = post.error or "Retry ended without a terminal outcome"

        await self.recompute_processed(protocol, db)
        await db.commit()
        return self._result(protocol, "ready", [post]).posts[0]

    async def reprocess_protocol(
        self, protocol: Protocol, db: AsyncSession
    ) -> PostPipelineResult:
        """Delete the plan, posts and generated output, then rebuild them."""
        cleanup_protocol_output(self.output_dir, protocol)

        post_ids = select(Post.id).where(Post.protocol_id == protocol.id)
        await db.execute(
            delete(PostAsset)
            .where(PostAsset.post_id.in_(post_ids))
            .execution_options(synchronize_session=False)
        )
        await db.execute(
            delete(PostSlide)
            .where(PostSlide.post_id.in_(post_ids))
            .execution_options(synchronize_session=False)
        )
        await db.execute(
            delete(Post)
            .where(Post.protocol_id == protocol.id)
            .execution_options(synchronize_session=False)
        )
        plan_row = await self._load_plan_row(db, protocol.id)
        if plan_row is not None:
            await db.delete(plan_row)
        protocol.processed = False
        await db.commit()

        result = await self.run(protocol, db)
        await self.recompute_processed(protocol, db)
        await db.commit()
        return result

    @staticmethod
    def _stage_from_failed_step(post: Post) -> str:
        step = post.failed_step
        if step == "repair":
            return "fact_check"
        if step in {
            "writer",
            "slide_composer",
            "fact_check",
            "caption",
            "visual_prompts",
            "image_generation",
            "render",
            "organ",
            "source_retrieval",
        }:
            return step
        return "auto"

    async def _retry_post_from_stage(
        self,
        protocol: Protocol,
        db: AsyncSession,
        plan: EditorialPlan,
        post: Post,
        stage: str,
    ) -> None:
        prepared = await self._prepare_retry_stage(
            protocol, db, plan, post, stage
        )
        if prepared is None:
            return
        stage, organ = prepared

        if post.post_type == "summary":
            await self._retry_summary_post(
                protocol, db, plan, organ, post, stage
            )
        else:
            await self._retry_topic_post(
                protocol, db, plan, organ, post, stage
            )

    async def _prepare_retry_stage(
        self,
        protocol: Protocol,
        db: AsyncSession,
        plan: EditorialPlan,
        post: Post,
        stage: str,
    ) -> tuple[str, str] | None:
        try:
            organ = resolve_organ(protocol.title)
        except UnknownOrganError as exc:
            await self._fail_post(db, post, "organ", exc)
            return None

        for _ in range(2):
            if stage in {"organ", "auto"}:
                stage = await self._earliest_missing_stage(db, post)
            if stage != "source_retrieval":
                break
            if not await self._retrieve_post_excerpts(
                protocol, db, plan, post
            ):
                return None
            stage = await self._earliest_missing_stage(db, post)
            if stage != "source_retrieval":
                break

        return stage, organ

    async def _retrieve_post_excerpts(
        self,
        protocol: Protocol,
        db: AsyncSession,
        plan: EditorialPlan,
        post: Post,
    ) -> bool:
        if post.post_type == "summary":
            self._retrieve_summary_excerpts(protocol, plan, post)
        else:
            brief = self._brief_for_post(plan, post)
            if brief is None:
                await self._fail_post(
                    db,
                    post,
                    "planner",
                    RuntimeError(
                        f"Plan has no topic brief for {post.slug!r}"
                    ),
                )
                return False
            self._retrieve_topic_excerpts(protocol, brief, post)
        if post.status == "failed":
            await db.commit()
            return False
        return True

    async def _earliest_missing_stage(
        self, db: AsyncSession, post: Post
    ) -> str:
        if not self._excerpts_cached(post):
            return "source_retrieval"

        draft = self._stored_draft(
            post,
            SummaryDraft if post.post_type == "summary" else TopicDraft,
        )
        if draft is None:
            return "writer"

        slides = await self._load_slides(db, post.id)
        if not slides or not post.slide_plan_json:
            return "slide_composer"
        if not self._fact_check_passed(post):
            return "fact_check"
        if not post.caption:
            return "caption"

        assets = await self._load_assets(db, post.id)
        if not assets or any(not asset.prompt for asset in assets):
            return "visual_prompts"
        return "image_generation"

    async def _retry_summary_post(
        self,
        protocol: Protocol,
        db: AsyncSession,
        plan: EditorialPlan,
        organ: str,
        post: Post,
        stage: str,
    ) -> None:
        if stage in {"writer", "slide_composer", "fact_check", "caption"}:
            written = await self._run_summary_content(
                protocol, db, plan, organ, post, start=stage
            )
            if written is None:
                return
            draft, composition = written
            await self._render_summary_visuals(
                protocol, db, organ, post, draft, composition
            )
            return

        draft = self._stored_draft(post, SummaryDraft)
        if draft is None:
            await self._fail_post(
                db,
                post,
                "writer",
                RuntimeError("No cached Summary draft for a visual retry"),
            )
            return
        self._sync_post_title(post, draft)
        composition = await self._stored_summary_composition(
            db, post, draft
        )
        if composition is None:
            await self._fail_post(
                db,
                post,
                "slide_composer",
                RuntimeError("No cached Summary composition for a visual retry"),
            )
            return

        await self._render_summary_visuals(
            protocol,
            db,
            organ,
            post,
            draft,
            composition,
            reuse_prompts=stage in {"image_generation", "render"},
        )

    async def _retry_topic_post(
        self,
        protocol: Protocol,
        db: AsyncSession,
        plan: EditorialPlan,
        organ: str,
        post: Post,
        stage: str,
    ) -> None:
        brief = self._brief_for_post(plan, post)
        if brief is None:
            await self._fail_post(
                db,
                post,
                "planner",
                RuntimeError(f"Plan has no topic brief for {post.slug!r}"),
            )
            return

        if stage in {"writer", "slide_composer", "fact_check", "caption"}:
            written = await self._run_topic_content(
                protocol, db, organ, brief, post, start=stage
            )
            if written is None:
                return
            draft, composition = written
            await self._render_topic_visuals(
                protocol, db, organ, post, draft, composition
            )
            return

        draft = self._stored_draft(post, TopicDraft)
        if draft is None:
            await self._fail_post(
                db,
                post,
                "writer",
                RuntimeError("No cached topic draft for a visual retry"),
            )
            return
        self._sync_post_title(post, draft)
        composition = await self._stored_topic_composition(
            db, post, draft
        )
        if composition is None:
            await self._fail_post(
                db,
                post,
                "slide_composer",
                RuntimeError("No cached topic composition for a visual retry"),
            )
            return

        await self._render_topic_visuals(
            protocol,
            db,
            organ,
            post,
            draft,
            composition,
            reuse_prompts=stage in {"image_generation", "render"},
        )

    def _keep_post_inputs(self, post: Post, plan: EditorialPlan) -> None:
        content = post.content_json or {}
        excerpts = content.get("excerpts", [])
        if post.post_type == "summary":
            briefs = content.get("briefs")
            post.content_json = {
                "briefs": briefs
                or [
                    brief.model_dump(mode="json")
                    for brief in plan.summary_briefs
                ],
                "excerpts": excerpts,
            }
        else:
            brief = self._brief_for_post(plan, post)
            post.content_json = {
                "brief": content.get("brief")
                or (
                    brief.model_dump(mode="json")
                    if brief is not None
                    else None
                ),
                "excerpts": excerpts,
            }
        post.content_markdown = None
        post.slide_plan_json = None
        post.caption = None
        post.alt_text_json = None
        post.fact_check_json = None

    async def _delete_post_artifacts(
        self, db: AsyncSession, post: Post
    ) -> None:
        await db.execute(
            delete(PostSlide)
            .where(PostSlide.post_id == post.id)
            .execution_options(synchronize_session=False)
        )
        await db.execute(
            delete(PostAsset)
            .where(PostAsset.post_id == post.id)
            .execution_options(synchronize_session=False)
        )
        await db.flush()

    @staticmethod
    def _brief_for_post(
        plan: EditorialPlan, post: Post
    ) -> TopicBrief | None:
        return next(
            (
                brief
                for brief in plan.topic_briefs
                if brief.slug == post.slug
            ),
            None,
        )

    # ------------------------------------------------------------------
    # Planning and persistence helpers.
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
            organ = resolve_organ(protocol.title)
        except UnknownOrganError as exc:
            for post in posts:
                post.status = "failed"
                post.failed_step = "organ"
                post.error = str(exc)
            return await self._commit_and_result(protocol, db, "ready", posts)

        summary_post = next(
            (post for post in posts if post.post_type == "summary"), None
        )
        if (
            summary_post is not None
            and not self._is_terminal(summary_post)
            and not self._excerpts_cached(summary_post)
        ):
            self._retrieve_summary_excerpts(protocol, plan, summary_post)

        topic_by_slug = {
            post.slug: post for post in posts if post.post_type == "topic"
        }
        for brief in plan.topic_briefs:
            post = topic_by_slug.get(brief.slug)
            if (
                post is None
                or self._is_terminal(post)
                or self._excerpts_cached(post)
            ):
                continue
            self._retrieve_topic_excerpts(protocol, brief, post)

        # The summary branch is independent: a failure there must not touch
        # topic drafts, and the topics remain planned for their own branch.
        if (
            summary_post is not None
            and summary_post.status == "draft"
            and summary_post.failed_step is None
        ):
            await self._process_summary_branch(
                protocol, db, plan, organ, summary_post
            )

        # Each topic is its own branch. A failed topic never blocks the
        # Summary or the other topics, and a failed Summary above never
        # prevents these branches from running.
        for brief in plan.topic_briefs:
            post = topic_by_slug.get(brief.slug)
            if (
                post is None
                or post.status != "draft"
                or post.failed_step is not None
            ):
                continue
            await self._process_topic_branch(
                protocol, db, organ, brief, post
            )

        return await self._commit_and_result(protocol, db, "ready", posts)

    @staticmethod
    def _is_terminal(post: Post) -> bool:
        return post.status in {"ready", "failed"}

    async def _process_summary_branch(
        self,
        protocol: Protocol,
        db: AsyncSession,
        plan: EditorialPlan,
        organ: str,
        post: Post,
    ) -> None:
        """Write content once, then always run visuals on top of the cached draft."""
        draft = self._stored_draft(post, SummaryDraft)
        composition: SummaryComposition | None = None

        if draft is not None:
            self._sync_post_title(post, draft)
            if not post.caption:
                await self._fail_post(
                    db,
                    post,
                    "caption",
                    RuntimeError("Cached Summary draft has no composed caption"),
                )
                return
            slides = await self._load_slides(db, post.id)
            if slides:
                try:
                    composition = summary_composition_from_stored(
                        draft, post.slide_plan_json, slides
                    )
                except Exception as exc:
                    await self._fail_post(db, post, "render", exc)
                    return

        if draft is None or composition is None:
            written = await self._write_summary_content(
                protocol, db, plan, organ, post
            )
            if written is None:
                return
            draft, composition = written

        await self._render_summary_visuals(protocol, db, organ, post, draft, composition)

    @staticmethod
    def _excerpts_cached(post: Post) -> bool:
        content = post.content_json or {}
        excerpts = content.get("excerpts") if isinstance(content, dict) else None
        return isinstance(excerpts, list) and bool(excerpts)

    @staticmethod
    def _stored_draft(
        post: Post,
        model: type[SummaryDraft] | type[TopicDraft],
    ) -> SummaryDraft | TopicDraft | None:
        content = post.content_json or {}
        raw_draft = content.get("draft") if isinstance(content, dict) else None
        if not isinstance(raw_draft, dict):
            return None
        try:
            return model.model_validate(raw_draft)
        except (ValidationError, TypeError, ValueError):
            return None

    async def _load_slides(
        self, db: AsyncSession, post_id: int
    ) -> list[PostSlide]:
        result = await db.execute(
            select(PostSlide)
            .where(PostSlide.post_id == post_id)
            .order_by(PostSlide.slide_index)
        )
        return list(result.scalars().all())

    async def _load_assets(
        self, db: AsyncSession, post_id: int
    ) -> list[PostAsset]:
        result = await db.execute(
            select(PostAsset)
            .where(PostAsset.post_id == post_id)
            .order_by(PostAsset.id)
        )
        return list(result.scalars().all())

    async def _write_summary_content(
        self,
        protocol: Protocol,
        db: AsyncSession,
        plan: EditorialPlan,
        organ: str,
        post: Post,
    ) -> tuple[SummaryDraft, SummaryComposition] | None:
        """Run writer → compose → fact-check/repair → caption for one draft."""
        return await self._run_summary_content(
            protocol, db, plan, organ, post, start="writer"
        )

    @staticmethod
    def _fact_check_passed(post: Post) -> bool:
        data = post.fact_check_json or {}
        return isinstance(data, dict) and bool(data.get("passed"))

    @staticmethod
    def _sync_post_title(post: Post, draft: SummaryDraft | TopicDraft) -> None:
        if post.post_type == "summary":
            post.title = draft.cover_title
        else:
            post.title = draft.title

    async def _summary_briefs_and_excerpts(
        self,
        protocol: Protocol,
        db: AsyncSession,
        plan: EditorialPlan,
        post: Post,
    ) -> tuple[list[SummaryBrief], list[SourceExcerpt]] | None:
        content = post.content_json or {}
        try:
            raw_briefs = content.get("briefs")
            briefs = (
                [SummaryBrief.model_validate(brief) for brief in raw_briefs]
                if raw_briefs
                else list(plan.summary_briefs)
            )
            excerpts = [
                SourceExcerpt.model_validate(excerpt)
                for excerpt in content.get("excerpts", [])
            ]
        except (TypeError, ValueError) as exc:
            await self._fail_post(db, post, "source_retrieval", exc)
            return None

        if not excerpts:
            self._retrieve_summary_excerpts(protocol, plan, post)
            if post.status == "failed":
                return None
            content = post.content_json or {}
            raw_briefs = content.get("briefs")
            briefs = (
                [SummaryBrief.model_validate(brief) for brief in raw_briefs]
                if raw_briefs
                else list(plan.summary_briefs)
            )
            excerpts = [
                SourceExcerpt.model_validate(excerpt)
                for excerpt in content.get("excerpts", [])
            ]

        if not excerpts:
            await self._fail_post(
                db,
                post,
                "source_retrieval",
                RuntimeError("No cached source excerpts for the Summary-Beitrag"),
            )
            return None
        return briefs, excerpts

    async def _replace_slides(
        self,
        db: AsyncSession,
        post: Post,
        slides: Sequence[Any],
    ) -> None:
        await db.execute(
            delete(PostSlide)
            .where(PostSlide.post_id == post.id)
            .execution_options(synchronize_session=False)
        )
        db.add_all(
            [
                PostSlide(
                    post_id=post.id,
                    slide_index=slide.slide_index,
                    slide_type=slide.slide_type,
                    pair_index=slide.pair_index,
                    label=slide.label,
                    headline=slide.headline,
                    body=slide.body,
                    alt_text=slide.alt_text,
                )
                for slide in slides
            ]
        )
        await db.flush()

    async def _persist_post_content_state(
        self,
        db: AsyncSession,
        post: Post,
        *,
        draft: SummaryDraft | TopicDraft,
        composition: SummaryComposition | TopicComposition,
        markdown: str,
    ) -> None:
        content = post.content_json or {}
        post.content_json = {
            "draft": draft.model_dump(mode="json"),
            "excerpts": list(content.get("excerpts", [])),
        }
        post.content_markdown = markdown
        post.slide_plan_json = composition.slide_plan
        post.alt_text_json = list(composition.alt_texts)
        await self._replace_slides(db, post, composition.slides)

    async def _stored_summary_composition(
        self, db: AsyncSession, post: Post, draft: SummaryDraft
    ) -> SummaryComposition | None:
        slides = await self._load_slides(db, post.id)
        if not slides or not post.slide_plan_json:
            return None
        try:
            return summary_composition_from_stored(
                draft, post.slide_plan_json, slides
            )
        except Exception:
            return None

    async def _run_summary_content(
        self,
        protocol: Protocol,
        db: AsyncSession,
        plan: EditorialPlan,
        organ: str,
        post: Post,
        *,
        start: str = "writer",
    ) -> tuple[SummaryDraft, SummaryComposition] | None:
        """Run the Summary content stages from ``start`` with cached inputs.

        ``start`` is one of ``writer``, ``slide_composer``, ``fact_check`` or
        ``caption``. The fact-check gate is only skipped for a caption retry
        when the stored fact-check result already passed.
        """
        inputs = await self._summary_briefs_and_excerpts(
            protocol, db, plan, post
        )
        if inputs is None:
            return None
        briefs, excerpts = inputs

        draft = None if start == "writer" else self._stored_draft(
            post, SummaryDraft
        )
        if draft is None:
            start = "writer"
        else:
            self._sync_post_title(post, draft)

        composition: SummaryComposition | None = None
        if start in {"fact_check", "caption"}:
            composition = await self._stored_summary_composition(
                db, post, draft
            )

        if start == "writer":
            try:
                draft = await write_summary(
                    briefs, excerpts, self.llm_client
                )
            except LLMAuthenticationError:
                raise
            except Exception as exc:
                await self._fail_post(db, post, "writer", exc)
                return None

            self._sync_post_title(post, draft)
            post.content_json = {
                "draft": draft.model_dump(mode="json"),
                "excerpts": [
                    excerpt.model_dump(mode="json")
                    for excerpt in excerpts
                ],
            }
            await db.flush()
            composition = None

        if composition is None:
            try:
                composition = compose_summary_slides(draft)
            except Exception as exc:
                await self._fail_post(db, post, "slide_composer", exc)
                return None
            await self._persist_post_content_state(
                db,
                post,
                draft=draft,
                composition=composition,
                markdown=render_summary_markdown(draft),
            )

        skip_gate = start == "caption" and self._fact_check_passed(post)
        if not skip_gate:
            try:
                outcome = await enforce_fact_check(
                    draft,
                    excerpts,
                    self.llm_client,
                    draft_schema=type(draft),
                    fact_check_role="summary_fact_check",
                    repair_role="summary_repair",
                )
            except FactCheckError as exc:
                post.fact_check_json = fact_check_json(
                    passed=False,
                    issues=exc.issues or [str(exc)],
                    repaired=isinstance(exc, FactCheckFailedError)
                    or exc.step == "repair",
                )
                await self._fail_post(db, post, exc.step, exc)
                return None
            except LLMAuthenticationError:
                raise
            except Exception as exc:
                await self._fail_post(db, post, "fact_check", exc)
                return None

            draft = outcome.draft
            self._sync_post_title(post, draft)
            if outcome.repaired:
                try:
                    composition = compose_summary_slides(draft)
                except Exception as exc:
                    await self._fail_post(db, post, "slide_composer", exc)
                    return None
            post.fact_check_json = fact_check_json(
                passed=True,
                issues=outcome.issues,
                repaired=outcome.repaired,
            )
            await self._persist_post_content_state(
                db,
                post,
                draft=draft,
                composition=composition,
                markdown=render_summary_markdown(draft),
            )

        try:
            caption_draft = await write_caption_body(
                draft,
                self.llm_client,
                organ=organ,
                session_date=protocol.session_date,
            )
            caption = compose_caption(
                body=caption_draft.body,
                organ=organ,
                session_date=protocol.session_date,
                protocol=protocol,
            )
        except LLMAuthenticationError:
            raise
        except Exception as exc:
            await self._fail_post(db, post, "caption", exc)
            return None

        post.caption = caption
        post.status = "draft"  # visuals flip the post to ready
        post.failed_step = None
        post.error = None
        await db.flush()
        return draft, composition

    async def _render_summary_visuals(
        self,
        protocol: Protocol,
        db: AsyncSession,
        organ: str,
        post: Post,
        draft: SummaryDraft,
        composition: SummaryComposition,
        *,
        reuse_prompts: bool = False,
    ) -> None:
        """Visual prompts → cover image → in-memory frames → caption file → ready."""
        self._sync_post_title(post, draft)
        if reuse_prompts:
            cached = await self._load_post_asset(db, post.id, "cover")
            if cached is None or not cached.prompt:
                await self._fail_post(
                    db,
                    post,
                    "visual_prompts",
                    RuntimeError(
                        "No cached Summary cover prompt for a render retry"
                    ),
                )
                return
            cover_prompt = cached.prompt
        else:
            try:
                visual_prompts = await write_summary_visual_prompts(
                    draft, self.llm_client
                )
            except LLMAuthenticationError:
                raise
            except Exception as exc:
                await self._fail_post(db, post, "visual_prompts", exc)
                return
            cover_prompt = visual_prompts.cover_prompt

        asset = await self._prepare_cover_asset(db, post, cover_prompt)

        try:
            generated = await generate_summary_cover(
                self.llm_client, cover_prompt
            )
        except LLMAuthenticationError:
            raise
        except Exception as exc:
            asset.status = "failed"
            asset.error = str(exc) or exc.__class__.__name__
            await self._fail_post(db, post, "image_generation", exc)
            return

        asset.status = generated.status
        asset.error = generated.error
        asset.path = None
        await db.flush()

        try:
            frames = render_summary_frames(
                draft,
                composition,
                cover_art=generated.image,
                organ=organ,
            )
        except Exception as exc:
            await self._fail_post(db, post, "render", exc)
            return

        try:
            output = write_summary_output(
                frames,
                post=post,
                protocol=protocol,
                output_dir=self.output_dir,
            )
        except Exception as exc:
            await self._fail_post(db, post, "render", exc)
            return

        asset.path = str(output.image_paths[0])
        post.status = "ready"
        post.failed_step = None
        post.error = None
        post.alt_text_json = list(composition.alt_texts)
        await self.recompute_processed(protocol, db)
        await db.commit()

    async def _load_post_asset(
        self, db: AsyncSession, post_id: int, role: str
    ) -> PostAsset | None:
        result = await db.execute(
            select(PostAsset).where(
                PostAsset.post_id == post_id, PostAsset.role == role
            )
        )
        return result.scalar_one_or_none()

    async def _prepare_cover_asset(
        self, db: AsyncSession, post: Post, prompt: str
    ) -> PostAsset:
        asset = await self._load_post_asset(db, post.id, "cover")
        if asset is None:
            asset = PostAsset(post_id=post.id, role="cover")
            db.add(asset)
        asset.prompt = prompt
        asset.status = "pending"
        asset.error = None
        asset.path = None
        asset.model = self._asset_image_model()
        await db.flush()
        return asset

    def _asset_image_model(self) -> str:
        """Use the injected client's image model when it exposes one."""
        return (
            getattr(self.llm_client, "image_model", None)
            or config.OPENROUTER_IMAGE_MODEL
        )

    async def _fail_post(
        self,
        db: AsyncSession,
        post: Post,
        step: str,
        exc: Exception,
    ) -> None:
        post.status = "failed"
        post.failed_step = step
        post.error = str(exc) or exc.__class__.__name__
        if step == "render":
            for asset in await self._load_assets(db, post.id):
                asset.status = "failed"
                asset.error = post.error
                asset.path = None
        await self._commit_post_outcome(db, post)

    async def _commit_post_outcome(self, db: AsyncSession, post: Post) -> None:
        protocol = await self._load_protocol(db, post.protocol_id)
        if protocol is not None:
            await self.recompute_processed(protocol, db)
        else:
            await db.flush()
        await db.commit()

    async def _process_topic_branch(
        self,
        protocol: Protocol,
        db: AsyncSession,
        organ: str,
        brief: TopicBrief,
        post: Post,
    ) -> None:
        """Resume at visuals when content is cached, else run the content stages first."""
        draft = self._stored_draft(post, TopicDraft)
        composition: TopicComposition | None = None

        if draft is not None and post.caption:
            self._sync_post_title(post, draft)
            slides = await self._load_slides(db, post.id)
            if slides and post.slide_plan_json:
                try:
                    composition = topic_composition_from_stored(
                        draft, post.slide_plan_json, slides
                    )
                except Exception as exc:
                    await self._fail_post(db, post, "render", exc)
                    return

        if draft is None or composition is None:
            written = await self._write_topic_content(
                protocol, db, organ, brief, post
            )
            if written is None:
                return
            draft, composition = written

        await self._render_topic_visuals(
            protocol, db, organ, post, draft, composition
        )

    async def _write_topic_content(
        self,
        protocol: Protocol,
        db: AsyncSession,
        organ: str,
        brief: TopicBrief,
        post: Post,
    ) -> tuple[TopicDraft, TopicComposition] | None:
        """Run writer+composition → fact-check/repair → caption for one topic."""
        return await self._run_topic_content(
            protocol, db, organ, brief, post, start="writer"
        )

    async def _topic_excerpts(
        self,
        protocol: Protocol,
        db: AsyncSession,
        brief: TopicBrief,
        post: Post,
    ) -> list[SourceExcerpt] | None:
        content = post.content_json or {}
        try:
            excerpts = [
                SourceExcerpt.model_validate(excerpt)
                for excerpt in content.get("excerpts", [])
            ]
        except (TypeError, ValueError) as exc:
            await self._fail_post(db, post, "source_retrieval", exc)
            return None

        if not excerpts:
            self._retrieve_topic_excerpts(protocol, brief, post)
            if post.status == "failed":
                return None
            content = post.content_json or {}
            excerpts = [
                SourceExcerpt.model_validate(excerpt)
                for excerpt in content.get("excerpts", [])
            ]

        if not excerpts:
            await self._fail_post(
                db,
                post,
                "source_retrieval",
                RuntimeError("No cached source excerpts for the Themenbeitrag"),
            )
            return None
        return excerpts

    async def _stored_topic_composition(
        self, db: AsyncSession, post: Post, draft: TopicDraft
    ) -> TopicComposition | None:
        slides = await self._load_slides(db, post.id)
        if not slides or not post.slide_plan_json:
            return None
        try:
            return topic_composition_from_stored(
                draft, post.slide_plan_json, slides
            )
        except Exception:
            return None

    async def _run_topic_content(
        self,
        protocol: Protocol,
        db: AsyncSession,
        organ: str,
        brief: TopicBrief,
        post: Post,
        *,
        start: str = "writer",
    ) -> tuple[TopicDraft, TopicComposition] | None:
        """Run the topic content stages from ``start`` with cached inputs."""
        excerpts = await self._topic_excerpts(protocol, db, brief, post)
        if excerpts is None:
            return None

        draft = None if start == "writer" else self._stored_draft(
            post, TopicDraft
        )
        if draft is None:
            start = "writer"
        else:
            self._sync_post_title(post, draft)

        composition: TopicComposition | None = None
        if start in {"fact_check", "caption"}:
            composition = await self._stored_topic_composition(
                db, post, draft
            )

        if start == "writer":
            try:
                draft = await write_topic(
                    brief,
                    excerpts,
                    self.llm_client,
                    compose=compose_topic_slides,
                )
            except LLMAuthenticationError:
                raise
            except TopicWriterError as exc:
                await self._fail_post(db, post, exc.step, exc)
                return None
            except Exception as exc:
                await self._fail_post(db, post, "writer", exc)
                return None

            self._sync_post_title(post, draft)
            post.content_json = {
                "draft": draft.model_dump(mode="json"),
                "excerpts": [
                    excerpt.model_dump(mode="json")
                    for excerpt in excerpts
                ],
            }
            await db.flush()
            composition = None

        if composition is None:
            try:
                composition = compose_topic_slides(draft)
            except Exception as exc:
                await self._fail_post(db, post, "slide_composer", exc)
                return None
            await self._persist_post_content_state(
                db,
                post,
                draft=draft,
                composition=composition,
                markdown=composition.markdown,
            )

        skip_gate = start == "caption" and self._fact_check_passed(post)
        if not skip_gate:
            try:
                outcome = await enforce_fact_check(
                    draft,
                    excerpts,
                    self.llm_client,
                    draft_schema=type(draft),
                    fact_check_role="topic_fact_check",
                    repair_role="topic_repair",
                )
            except FactCheckError as exc:
                post.fact_check_json = fact_check_json(
                    passed=False,
                    issues=exc.issues or [str(exc)],
                    repaired=isinstance(exc, FactCheckFailedError)
                    or exc.step == "repair",
                )
                await self._fail_post(db, post, exc.step, exc)
                return None
            except LLMAuthenticationError:
                raise
            except Exception as exc:
                await self._fail_post(db, post, "fact_check", exc)
                return None

            draft = outcome.draft
            self._sync_post_title(post, draft)
            if outcome.repaired:
                try:
                    composition = compose_topic_slides(draft)
                except Exception as exc:
                    await self._fail_post(db, post, "slide_composer", exc)
                    return None
            post.fact_check_json = fact_check_json(
                passed=True,
                issues=outcome.issues,
                repaired=outcome.repaired,
            )
            await self._persist_post_content_state(
                db,
                post,
                draft=draft,
                composition=composition,
                markdown=composition.markdown,
            )

        try:
            caption_draft = await write_caption_body(
                draft,
                self.llm_client,
                organ=organ,
                session_date=protocol.session_date,
            )
            caption = compose_caption(
                body=caption_draft.body,
                organ=organ,
                session_date=protocol.session_date,
                protocol=protocol,
            )
        except LLMAuthenticationError:
            raise
        except Exception as exc:
            await self._fail_post(db, post, "caption", exc)
            return None

        post.caption = caption
        post.status = "draft"  # visuals flip the post to ready
        post.failed_step = None
        post.error = None
        await db.flush()
        await db.commit()
        return draft, composition

    async def _render_topic_visuals(
        self,
        protocol: Protocol,
        db: AsyncSession,
        organ: str,
        post: Post,
        draft: TopicDraft,
        composition: TopicComposition,
        *,
        reuse_prompts: bool = False,
    ) -> None:
        """Visual prompts → assets → in-memory frames → caption file → ready."""
        self._sync_post_title(post, draft)
        content_slides = len(composition.slides) - 1
        pair_count = content_slides // 2
        has_single = content_slides % 2 == 1
        artwork_count = pair_count + (1 if has_single else 0)

        role_names = ["cover"]
        role_names.extend(f"pair_{index}" for index in range(1, pair_count + 1))
        if has_single:
            role_names.append("single_last")

        if reuse_prompts:
            result = await db.execute(
                select(PostAsset).where(PostAsset.post_id == post.id)
            )
            existing = {asset.role: asset for asset in result.scalars().all()}
            prompts: dict[str, str] = {}
            for role in role_names:
                asset = existing.get(role)
                if asset is None or not asset.prompt:
                    await self._fail_post(
                        db,
                        post,
                        "visual_prompts",
                        RuntimeError(
                            "No cached topic visual prompt for a render retry"
                        ),
                    )
                    return
                prompts[role] = asset.prompt
        else:
            try:
                visual_prompts = await write_topic_visual_prompts(
                    draft, artwork_count, self.llm_client
                )
            except LLMAuthenticationError:
                raise
            except Exception as exc:
                await self._fail_post(db, post, "visual_prompts", exc)
                return

            prompts = {"cover": visual_prompts.cover_prompt}
            for index in range(1, pair_count + 1):
                prompts[f"pair_{index}"] = (
                    visual_prompts.artwork_prompts[index - 1]
                )
            if has_single:
                prompts["single_last"] = visual_prompts.artwork_prompts[-1]

        assets = await self._prepare_topic_assets(
            db, post, list(prompts.items())
        )

        try:
            generated_cover = await generate_topic_cover(
                self.llm_client, prompts["cover"]
            )
        except LLMAuthenticationError:
            raise
        except Exception as exc:
            await self._fail_topic_asset(db, post, assets["cover"], exc)
            return

        generated_pairs: dict[int, Any] = {}
        for index in range(1, pair_count + 1):
            try:
                generated = await generate_topic_pair_art(
                    self.llm_client, prompts[f"pair_{index}"]
                )
            except LLMAuthenticationError:
                raise
            except Exception as exc:
                await self._fail_topic_asset(
                    db, post, assets[f"pair_{index}"], exc
                )
                return
            generated_pairs[index] = generated

        generated_single = None
        if has_single:
            try:
                generated_single = await generate_topic_single_art(
                    self.llm_client, prompts["single_last"]
                )
            except LLMAuthenticationError:
                raise
            except Exception as exc:
                await self._fail_topic_asset(
                    db, post, assets["single_last"], exc
                )
                return

        generated_by_role = {"cover": generated_cover}
        generated_by_role.update(
            {
                f"pair_{index}": generated
                for index, generated in generated_pairs.items()
            }
        )
        if generated_single is not None:
            generated_by_role["single_last"] = generated_single
        for role, generated in generated_by_role.items():
            asset = assets[role]
            asset.status = generated.status
            asset.error = generated.error
            asset.path = None
        await db.flush()

        try:
            frames = render_topic_frames(
                draft,
                composition,
                cover_art=generated_cover.image,
                pair_art={
                    index: generated.image
                    for index, generated in generated_pairs.items()
                },
                single_art=(
                    generated_single.image
                    if generated_single is not None
                    else None
                ),
                organ=organ,
            )
        except Exception as exc:
            await self._fail_post(db, post, "render", exc)
            return

        try:
            output = write_topic_output(
                frames,
                post=post,
                protocol=protocol,
                output_dir=self.output_dir,
            )
        except Exception as exc:
            await self._fail_post(db, post, "render", exc)
            return

        assets["cover"].path = str(output.image_paths[0])
        for index in range(1, pair_count + 1):
            first_content_position = 2 * index - 1
            assets[f"pair_{index}"].path = str(
                output.image_paths[first_content_position]
            )
        if has_single:
            assets["single_last"].path = str(
                output.image_paths[content_slides]
            )

        post.status = "ready"
        post.failed_step = None
        post.error = None
        post.alt_text_json = list(composition.alt_texts)
        await self.recompute_processed(protocol, db)
        await db.commit()

    async def _prepare_topic_assets(
        self,
        db: AsyncSession,
        post: Post,
        roles: Sequence[tuple[str, str]],
    ) -> dict[str, PostAsset]:
        result = await db.execute(
            select(PostAsset).where(PostAsset.post_id == post.id)
        )
        existing = {asset.role: asset for asset in result.scalars().all()}
        wanted = {role for role, _ in roles}
        for role, asset in existing.items():
            if role not in wanted:
                await db.delete(asset)
        assets: dict[str, PostAsset] = {}
        for role, prompt in roles:
            asset = existing.get(role)
            if asset is None:
                asset = PostAsset(post_id=post.id, role=role)
                db.add(asset)
            asset.prompt = prompt
            asset.status = "pending"
            asset.error = None
            asset.path = None
            asset.model = self._asset_image_model()
            assets[role] = asset
        await db.flush()
        return assets

    async def _fail_topic_asset(
        self,
        db: AsyncSession,
        post: Post,
        asset: PostAsset,
        exc: Exception,
    ) -> None:
        asset.status = "failed"
        asset.error = str(exc) or exc.__class__.__name__
        await self._fail_post(db, post, "image_generation", exc)

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
        await self.recompute_processed(protocol, db)
        result = self._result(protocol, plan_status, posts)
        await db.commit()
        return result

    # ------------------------------------------------------------------
    # Terminal state and result/read helpers.
    # ------------------------------------------------------------------

    async def recompute_processed(
        self, protocol: Protocol, db: AsyncSession
    ) -> bool:
        """Set ``Protocol.processed`` from the persisted plan and posts.

        True only when a valid ready plan exists, the Summary and every
        planned Themenbeitrag exist, and all of them are terminal
        (``ready`` or ``failed``). A failed Summary or Themenbeitrag therefore
        does not block the protocol forever.
        """
        await db.flush()
        plan_row = await self._load_plan_row(db, protocol.id)
        processed = False
        if plan_row is not None and plan_row.status == "ready":
            plan = self._load_plan(plan_row)
            if plan is not None:
                posts = await self._load_posts(db, protocol.id)
                by_key = {
                    (post.post_type, post.slug): post for post in posts
                }
                summary = by_key.get(("summary", "summary"))
                if summary is not None and self._is_terminal(summary):
                    processed = all(
                        (
                            topic := by_key.get(("topic", brief.slug))
                        )
                        is not None
                        and self._is_terminal(topic)
                        for brief in plan.topic_briefs
                    )
        protocol.processed = processed
        await db.flush()
        return processed

    async def _load_protocol(
        self, db: AsyncSession, protocol_id: int
    ) -> Protocol | None:
        result = await db.execute(
            select(Protocol).where(Protocol.id == protocol_id)
        )
        return result.scalar_one_or_none()

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
