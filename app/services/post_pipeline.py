"""Stateless post-pipeline orchestrator: plan, write and render Beiträge.

The pipeline plans first, persists the Redaktionsplan and one summary plus zero
to five topic posts, then resolves the finite Organ and retrieves the source
excerpts. The Summary branch writes its content once, then runs visual prompts,
cover image generation, the 9:16 renderer and the caption file. Later tickets
extend the topic branch and the retry/reprocess state machine.

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

from app.core import config
from app.core.config import ARTICLES_DIR
from app.core.post_models import (
    EditorialPlan,
    SourceExcerpt,
    SummaryBrief,
    SummaryDraft,
    TopicBrief,
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
from app.services.image_generation import generate_summary_cover
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
    compose_summary_slides,
    compose_topic_slides,
    render_summary_markdown,
)
from app.services.summary_writer import write_summary
from app.services.topic_writer import TopicWriterError, write_topic
from app.services.visual_prompts import write_summary_visual_prompts

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
        # ticket 08 owns the explicit reprocess/replace semantics.
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
            and not self._summary_excerpts_cached(summary_post)
        ):
            self._retrieve_summary_excerpts(protocol, plan, summary_post)

        topic_by_slug = {
            post.slug: post for post in posts if post.post_type == "topic"
        }
        for brief in plan.topic_briefs:
            post = topic_by_slug.get(brief.slug)
            if post is None or self._is_terminal(post):
                continue
            self._retrieve_topic_excerpts(protocol, brief, post)

        # The summary branch is independent: a failure there must not touch
        # topic drafts, and the topics remain planned for a later ticket.
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
        draft = self._stored_summary_draft(post)
        composition: SummaryComposition | None = None

        if draft is not None:
            if not post.caption:
                await self._fail_summary_post(
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
                    await self._fail_summary_post(db, post, "render", exc)
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
    def _summary_excerpts_cached(post: Post) -> bool:
        content = post.content_json or {}
        excerpts = content.get("excerpts") if isinstance(content, dict) else None
        return isinstance(excerpts, list) and bool(excerpts)

    @staticmethod
    def _stored_summary_draft(post: Post) -> SummaryDraft | None:
        content = post.content_json or {}
        raw_draft = content.get("draft") if isinstance(content, dict) else None
        if not isinstance(raw_draft, dict):
            return None
        try:
            return SummaryDraft.model_validate(raw_draft)
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

    async def _write_summary_content(
        self,
        protocol: Protocol,
        db: AsyncSession,
        plan: EditorialPlan,
        organ: str,
        post: Post,
    ) -> tuple[SummaryDraft, SummaryComposition] | None:
        """Run writer → compose → fact-check/repair → caption for one draft."""
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
            await self._fail_summary_post(
                db, post, "source_retrieval", exc
            )
            return None

        if not excerpts:
            await self._fail_summary_post(
                db,
                post,
                "source_retrieval",
                RuntimeError("No cached source excerpts for the Summary post"),
            )
            return None

        try:
            draft = await write_summary(briefs, excerpts, self.llm_client)
        except LLMAuthenticationError:
            raise
        except Exception as exc:
            await self._fail_summary_post(db, post, "writer", exc)
            return None

        post.content_json = {
            "draft": draft.model_dump(mode="json"),
            "excerpts": [
                excerpt.model_dump(mode="json") for excerpt in excerpts
            ],
        }

        try:
            composition = compose_summary_slides(draft)
        except Exception as exc:
            await self._fail_summary_post(db, post, "slide_composer", exc)
            return None

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
            await self._fail_summary_post(db, post, exc.step, exc)
            return None
        except LLMAuthenticationError:
            raise
        except Exception as exc:
            await self._fail_summary_post(db, post, "fact_check", exc)
            return None

        final_draft = outcome.draft
        if outcome.repaired:
            try:
                composition = compose_summary_slides(final_draft)
            except Exception as exc:
                await self._fail_summary_post(
                    db, post, "slide_composer", exc
                )
                return None

        try:
            caption_draft = await write_caption_body(
                final_draft,
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
            await self._fail_summary_post(db, post, "caption", exc)
            return None

        post.content_json = {
            "draft": final_draft.model_dump(mode="json"),
            "excerpts": [
                excerpt.model_dump(mode="json") for excerpt in excerpts
            ],
        }
        post.content_markdown = render_summary_markdown(final_draft)
        post.slide_plan_json = composition.slide_plan
        post.caption = caption
        post.alt_text_json = list(composition.alt_texts)
        post.fact_check_json = fact_check_json(
            passed=True,
            issues=outcome.issues,
            repaired=outcome.repaired,
        )
        post.status = "draft"  # visuals flip the post to ready
        post.failed_step = None
        post.error = None

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
                for slide in composition.slides
            ]
        )
        await db.flush()
        return final_draft, composition

    async def _render_summary_visuals(
        self,
        protocol: Protocol,
        db: AsyncSession,
        organ: str,
        post: Post,
        draft: SummaryDraft,
        composition: SummaryComposition,
    ) -> None:
        """Visual prompts → cover image → in-memory frames → caption file → ready."""
        try:
            visual_prompts = await write_summary_visual_prompts(
                draft, self.llm_client
            )
        except LLMAuthenticationError:
            raise
        except Exception as exc:
            await self._fail_summary_post(db, post, "visual_prompts", exc)
            return

        asset = await self._prepare_cover_asset(db, post, visual_prompts.cover_prompt)

        try:
            generated = await generate_summary_cover(
                self.llm_client, visual_prompts.cover_prompt
            )
        except LLMAuthenticationError:
            raise
        except Exception as exc:
            asset.status = "failed"
            asset.error = str(exc) or exc.__class__.__name__
            await self._fail_summary_post(db, post, "image_generation", exc)
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
            await self._fail_summary_post(db, post, "render", exc)
            return

        try:
            output = write_summary_output(
                frames,
                post=post,
                protocol=protocol,
                output_dir=self.output_dir,
            )
        except Exception as exc:
            await self._fail_summary_post(db, post, "render", exc)
            return

        asset.path = str(output.image_paths[0])
        post.status = "ready"
        post.failed_step = None
        post.error = None
        post.alt_text_json = list(composition.alt_texts)
        await db.flush()

    async def _prepare_cover_asset(
        self, db: AsyncSession, post: Post, prompt: str
    ) -> PostAsset:
        result = await db.execute(
            select(PostAsset).where(
                PostAsset.post_id == post.id, PostAsset.role == "cover"
            )
        )
        asset = result.scalar_one_or_none()
        if asset is None:
            asset = PostAsset(post_id=post.id, role="cover")
            db.add(asset)
        asset.prompt = prompt
        asset.status = "pending"
        asset.error = None
        asset.path = None
        asset.model = config.OPENROUTER_IMAGE_MODEL
        await db.flush()
        return asset

    async def _fail_summary_post(
        self,
        db: AsyncSession,
        post: Post,
        step: str,
        exc: Exception,
    ) -> None:
        post.status = "failed"
        post.failed_step = step
        post.error = str(exc) or exc.__class__.__name__
        await db.commit()

    async def _process_topic_branch(
        self,
        protocol: Protocol,
        db: AsyncSession,
        organ: str,
        brief: TopicBrief,
        post: Post,
    ) -> None:
        """Run writer+composition → fact-check/repair → caption for one topic."""
        content = post.content_json or {}
        try:
            excerpts = [
                SourceExcerpt.model_validate(excerpt)
                for excerpt in content.get("excerpts", [])
            ]
        except (TypeError, ValueError) as exc:
            await self._fail_topic_post(db, post, "source_retrieval", exc)
            return

        if not excerpts:
            await self._fail_topic_post(
                db,
                post,
                "source_retrieval",
                RuntimeError("No cached source excerpts for the topic post"),
            )
            return

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
            await self._fail_topic_post(db, post, exc.step, exc)
            return
        except Exception as exc:
            await self._fail_topic_post(db, post, "writer", exc)
            return

        post.content_json = {
            "draft": draft.model_dump(mode="json"),
            "excerpts": [
                excerpt.model_dump(mode="json") for excerpt in excerpts
            ],
        }

        try:
            composition = compose_topic_slides(draft)
        except Exception as exc:
            await self._fail_topic_post(db, post, "slide_composer", exc)
            return

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
            await self._fail_topic_post(db, post, exc.step, exc)
            return
        except LLMAuthenticationError:
            raise
        except Exception as exc:
            await self._fail_topic_post(db, post, "fact_check", exc)
            return

        final_draft = outcome.draft
        if outcome.repaired:
            try:
                composition = compose_topic_slides(final_draft)
            except Exception as exc:
                await self._fail_topic_post(
                    db, post, "slide_composer", exc
                )
                return

        try:
            caption_draft = await write_caption_body(
                final_draft,
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
            await self._fail_topic_post(db, post, "caption", exc)
            return

        post.content_json = {
            "draft": final_draft.model_dump(mode="json"),
            "excerpts": [
                excerpt.model_dump(mode="json") for excerpt in excerpts
            ],
        }
        post.content_markdown = composition.markdown
        post.slide_plan_json = composition.slide_plan
        post.caption = caption
        post.alt_text_json = list(composition.alt_texts)
        post.fact_check_json = fact_check_json(
            passed=True,
            issues=outcome.issues,
            repaired=outcome.repaired,
        )
        post.status = "draft"  # ticket 07 renders and flips to ready
        post.failed_step = None
        post.error = None

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
                for slide in composition.slides
            ]
        )
        await db.flush()
        await db.commit()

    async def _fail_topic_post(
        self,
        db: AsyncSession,
        post: Post,
        step: str,
        exc: Exception,
    ) -> None:
        post.status = "failed"
        post.failed_step = step
        post.error = str(exc) or exc.__class__.__name__
        await db.commit()

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
