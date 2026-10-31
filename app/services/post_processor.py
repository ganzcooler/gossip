"""Orchestration for the two-post pipeline.

The summary is completed before topic work starts. Each post is resumable:
completed texts, slide plans, source images, and rendered slides are reused on
retry. ``Protocol.processed`` only becomes true when every planned post and
every required image is ready.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import ExitStack
from functools import partial
from pathlib import Path

from PIL import Image
from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import ARTICLES_DIR
from app.core.post_models import (
    ArticleDraft,
    EditorialPlan,
    SummaryBrief,
    SummarySlidePlan,
    TopicBrief,
    TopicSlidePlan,
)
from app.models import (
    EditorialPlan as EditorialPlanRecord,
    Post,
    PostAsset,
    PostSlide,
    PostStatus,
    PostType,
    Protocol,
)
from app.services.editorial_planner import plan_editorial
from app.services.errors import AuthenticationError, TextOverflowError
from app.services.fact_checker import fact_check_article
from app.services.post_image_generator import (
    generate_image_bytes,
    generate_summary_cover_prompt,
    generate_topic_artwork_prompt,
    generate_topic_caption,
    generate_topic_cover_prompt,
)
from app.services.post_renderer import render_summary_story, render_topic_carousel
from app.services.post_writer import (
    article_to_markdown,
    repair_article,
    write_summary_article,
    write_topic_article,
)
from app.services.slide_planner import (
    fallback_summary_slides,
    fallback_topic_slides,
    plan_summary_slides,
    plan_topic_slides,
    repair_summary_slides,
    repair_topic_slides,
)
from app.utils.folder_utils import create_protocol_folder, normalize_for_folder_name

logger = logging.getLogger(__name__)

RES_DIR = Path(__file__).parent.parent / "res"


async def _run_sync(func, *args, **kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(func, *args, **kwargs))


def _protocol_folder(protocol: Protocol) -> Path:
    try:
        return create_protocol_folder(ARTICLES_DIR, protocol.session_date, protocol.title)
    except FileExistsError:
        normalized = normalize_for_folder_name(protocol.title)
        return ARTICLES_DIR / f"{protocol.session_date.strftime('%y%m%d')}_{normalized}"


async def process_protocol_posts(protocol: Protocol, db_session: AsyncSession) -> None:
    """Generate and render every planned post for one protocol."""
    logger.debug("Processing protocol %s with the post pipeline", protocol.id)
    folder = _protocol_folder(protocol)
    plan = await _get_or_create_plan(protocol, db_session)

    await _ensure_summary_post(protocol, plan.summary, folder, db_session)
    logger.debug("Summary post is ready for protocol %s", protocol.id)

    for index, topic in enumerate(plan.topics, start=1):
        try:
            await _ensure_topic_post(protocol, topic, index, folder, db_session)
            logger.debug(
                "Topic post %s (%s) is ready for protocol %s",
                index,
                topic.slug,
                protocol.id,
            )
        except AuthenticationError:
            raise
        except Exception as exc:
            logger.error(
                "Topic %s failed for protocol %s: %s",
                topic.slug,
                protocol.id,
                exc,
                exc_info=True,
            )
            post = await _get_post(protocol, PostType.TOPIC, topic.slug, db_session)
            if post is not None:
                post.status = PostStatus.FAILED
                post.error = str(exc)
                await db_session.commit()

    all_ready = await _all_posts_ready(protocol, plan, db_session)
    protocol.processed = all_ready
    await db_session.commit()

    if not all_ready:
        logger.warning("Protocol %s remains unprocessed", protocol.id)


async def _get_or_create_plan(
    protocol: Protocol, db_session: AsyncSession
) -> EditorialPlan:
    result = await db_session.execute(
        select(EditorialPlanRecord).where(
            EditorialPlanRecord.protocol_id == protocol.id
        )
    )
    record = result.scalar_one_or_none()
    if record is not None:
        return EditorialPlan.model_validate(record.plan_json)

    plan = await _run_sync(plan_editorial, protocol.pdf_text)
    record = EditorialPlanRecord(
        protocol_id=protocol.id,
        plan_json=plan.model_dump(mode="json"),
    )
    db_session.add(record)
    await db_session.commit()
    return plan


async def _get_post(
    protocol: Protocol,
    post_type: PostType,
    slug: str,
    db_session: AsyncSession,
) -> Post | None:
    result = await db_session.execute(
        select(Post)
        .options(selectinload(Post.slides), selectinload(Post.assets))
        .where(
            Post.protocol_id == protocol.id,
            Post.post_type == post_type,
            Post.slug == slug,
        )
    )
    return result.scalar_one_or_none()


async def _create_post(
    protocol: Protocol,
    post_type: PostType,
    slug: str,
    post_index: int,
    title: str,
    kicker: str,
    db_session: AsyncSession,
) -> Post:
    post = Post(
        protocol_id=protocol.id,
        post_type=post_type,
        slug=slug,
        post_index=post_index,
        title=title,
        kicker=kicker,
        content_markdown="",
        content_json={},
        status=PostStatus.DRAFT,
    )
    db_session.add(post)
    await db_session.commit()
    created = await _get_post(protocol, post_type, slug, db_session)
    if created is None:
        raise RuntimeError(f"Could not reload created post {slug}")
    return created


async def _ensure_summary_post(
    protocol: Protocol,
    brief: SummaryBrief,
    folder: Path,
    db_session: AsyncSession,
) -> Post:
    post = await _get_post(protocol, PostType.SUMMARY, "summary", db_session)
    if post is not None and post.status == PostStatus.READY:
        return post
    if post is None:
        post = await _create_post(
            protocol,
            PostType.SUMMARY,
            "summary",
            0,
            brief.working_title,
            "SITZUNG KOMPAKT",
            db_session,
        )

    article = await _ensure_article(
        post, protocol, brief, write_summary_article, db_session
    )

    plan = _load_summary_plan(post)
    if plan is None:
        plan = await _run_sync(plan_summary_slides, article)
        await _persist_summary_slides(post, plan, db_session)

    cover_path, _ = await _ensure_asset_image(
        post,
        role="cover",
        prompt_factory=lambda: generate_summary_cover_prompt(article, plan.cover),
        aspect_ratio="9:16",
        folder=folder,
        filename="summary_cover_source.png",
        db_session=db_session,
    )

    paths, plan = await _render_summary_with_repair(
        post, article, plan, cover_path, folder, db_session
    )
    await _upsert_rendered_assets(post, paths, db_session)
    post.status = PostStatus.READY
    post.error = None
    await db_session.commit()
    return post


async def _ensure_topic_post(
    protocol: Protocol,
    brief: TopicBrief,
    post_index: int,
    folder: Path,
    db_session: AsyncSession,
) -> Post:
    post = await _get_post(protocol, PostType.TOPIC, brief.slug, db_session)
    if post is not None and post.status == PostStatus.READY:
        return post
    if post is None:
        post = await _create_post(
            protocol,
            PostType.TOPIC,
            brief.slug,
            post_index,
            brief.working_title,
            "THEMA IM FOKUS",
            db_session,
        )

    article = await _ensure_article(
        post, protocol, brief, write_topic_article, db_session
    )

    plan = _load_topic_plan(post)
    if plan is None:
        plan = await _run_sync(plan_topic_slides, article)
        await _persist_topic_slides(post, plan, db_session)

    cover_path, _ = await _ensure_asset_image(
        post,
        role="cover",
        prompt_factory=lambda: generate_topic_cover_prompt(article, plan.cover),
        aspect_ratio="4:5",
        folder=folder,
        filename=f"topic_{post_index:02d}_cover_source.png",
        db_session=db_session,
    )

    artwork_paths: list[Path] = []
    for pair_index, pair in enumerate(plan.pairs, start=1):
        path, _ = await _ensure_asset_image(
            post,
            role=f"artwork_{pair_index:02d}",
            prompt_factory=lambda pair=pair: generate_topic_artwork_prompt(article, pair),
            aspect_ratio="4:5",
            folder=folder,
            filename=f"topic_{post_index:02d}_artwork_{pair_index:02d}_source.png",
            db_session=db_session,
        )
        artwork_paths.append(path)

    if not post.caption:
        caption = await _run_sync(generate_topic_caption, article, plan)
        post.caption = caption.caption
        await db_session.commit()

    paths, plan = await _render_topic_with_repair(
        post,
        article,
        plan,
        cover_path,
        artwork_paths,
        folder,
        post_index,
        db_session,
    )
    await _upsert_rendered_assets(post, paths, db_session)
    post.status = PostStatus.READY
    post.error = None
    await db_session.commit()
    return post


async def _ensure_article(
    post: Post,
    protocol: Protocol,
    brief: SummaryBrief | TopicBrief,
    writer,
    db_session: AsyncSession,
) -> ArticleDraft:
    if post.content_json:
        try:
            return ArticleDraft.model_validate(post.content_json)
        except ValidationError:
            logger.warning("Stored article for post %s is invalid; rewriting", post.slug)

    article = await _run_sync(writer, protocol.pdf_text, brief)
    fact_check = await _run_sync(fact_check_article, protocol.pdf_text, article)

    if fact_check.issues or fact_check.verdict == "needs_repair":
        logger.info("Repairing article %s after fact-check", post.slug)
        article = await _run_sync(
            repair_article, protocol.pdf_text, article, fact_check
        )
        second_check = await _run_sync(fact_check_article, protocol.pdf_text, article)
        if second_check.issues:
            logger.warning(
                "Fact-check still reports %s issue(s) for post %s",
                len(second_check.issues),
                post.slug,
            )

    post.title = article.title
    post.kicker = article.kicker
    post.content_json = article.model_dump(mode="json")
    post.content_markdown = article_to_markdown(article)
    post.status = PostStatus.DRAFT
    post.error = None
    await db_session.commit()
    return article


def _load_summary_plan(post: Post) -> SummarySlidePlan | None:
    if not post.slide_plan_json:
        return None
    try:
        return SummarySlidePlan.model_validate(post.slide_plan_json)
    except ValidationError:
        return None


def _load_topic_plan(post: Post) -> TopicSlidePlan | None:
    if not post.slide_plan_json:
        return None
    try:
        return TopicSlidePlan.model_validate(post.slide_plan_json)
    except ValidationError:
        return None


async def _persist_summary_slides(
    post: Post, plan: SummarySlidePlan, db_session: AsyncSession
) -> None:
    await db_session.execute(delete(PostSlide).where(PostSlide.post_id == post.id))
    for index, slide in enumerate(plan.slides, start=1):
        db_session.add(
            PostSlide(
                post_id=post.id,
                slide_index=index,
                pair_index=None,
                label=slide.label,
                headline=slide.headline,
                body=slide.body,
            )
        )
    post.slide_plan_json = plan.model_dump(mode="json")
    await db_session.commit()


async def _persist_topic_slides(
    post: Post, plan: TopicSlidePlan, db_session: AsyncSession
) -> None:
    await db_session.execute(delete(PostSlide).where(PostSlide.post_id == post.id))
    slide_index = 0
    for pair_index, pair in enumerate(plan.pairs, start=1):
        for slide in pair.slides:
            slide_index += 1
            db_session.add(
                PostSlide(
                    post_id=post.id,
                    slide_index=slide_index,
                    pair_index=pair_index,
                    label=slide.label,
                    headline=slide.headline,
                    body=slide.body,
                )
            )
    post.slide_plan_json = plan.model_dump(mode="json")
    await db_session.commit()


async def _get_asset(
    post: Post, role: str, db_session: AsyncSession
) -> PostAsset | None:
    result = await db_session.execute(
        select(PostAsset).where(
            PostAsset.post_id == post.id,
            PostAsset.role == role,
        )
    )
    return result.scalar_one_or_none()


async def _ensure_asset_image(
    post: Post,
    *,
    role: str,
    prompt_factory,
    aspect_ratio: str,
    folder: Path,
    filename: str,
    db_session: AsyncSession,
) -> tuple[Path, PostAsset]:
    asset = await _get_asset(post, role, db_session)
    if asset is not None and asset.status == "ready" and asset.path:
        path = Path(asset.path)
        if path.exists():
            return path, asset

    prompt = asset.prompt if asset is not None and asset.prompt else await _run_sync(
        prompt_factory
    )
    image_bytes = await _run_sync(generate_image_bytes, prompt, aspect_ratio)
    path = folder / filename
    path.write_bytes(image_bytes)

    if asset is None:
        asset = PostAsset(post_id=post.id, role=role)
        db_session.add(asset)
    asset.prompt = prompt
    asset.path = str(path)
    asset.status = "ready"
    asset.error = None
    await db_session.commit()
    return path, asset


async def _upsert_rendered_assets(
    post: Post, paths: list[Path], db_session: AsyncSession
) -> None:
    for index, path in enumerate(paths):
        role = "rendered_cover" if index == 0 else f"slide_{index:02d}"
        asset = await _get_asset(post, role, db_session)
        if asset is None:
            asset = PostAsset(post_id=post.id, role=role)
            db_session.add(asset)
        asset.path = str(path)
        asset.status = "ready"
        asset.error = None
    await db_session.commit()


async def _render_summary_with_repair(
    post: Post,
    article: ArticleDraft,
    plan: SummarySlidePlan,
    cover_path: Path,
    folder: Path,
    db_session: AsyncSession,
) -> tuple[list[Path], SummarySlidePlan]:
    for attempt in range(2):
        try:
            with Image.open(cover_path) as cover_image:
                paths = await _run_sync(
                    render_summary_story,
                    cover_image=cover_image,
                    plan=plan,
                    output_dir=folder,
                    res_dir=RES_DIR,
                )
            return paths, plan
        except TextOverflowError as exc:
            overflow = (
                f"role: {exc.role}\ntext: {exc.text}\n"
                f"max_width: {exc.max_width}\nmax_height: {exc.max_height}"
            )
            logger.warning("Summary render overflow: %s", exc)
            if attempt == 0:
                plan = await _run_sync(
                    repair_summary_slides, article, plan, overflow
                )
            else:
                plan = fallback_summary_slides(article)
            await _persist_summary_slides(post, plan, db_session)

    with Image.open(cover_path) as cover_image:
        paths = await _run_sync(
            render_summary_story,
            cover_image=cover_image,
            plan=plan,
            output_dir=folder,
            res_dir=RES_DIR,
        )
    return paths, plan


async def _render_topic_with_repair(
    post: Post,
    article: ArticleDraft,
    plan: TopicSlidePlan,
    cover_path: Path,
    artwork_paths: list[Path],
    folder: Path,
    post_index: int,
    db_session: AsyncSession,
) -> tuple[list[Path], TopicSlidePlan]:
    for attempt in range(2):
        try:
            with ExitStack() as stack:
                cover_image = stack.enter_context(Image.open(cover_path))
                artworks = [
                    stack.enter_context(Image.open(path)) for path in artwork_paths
                ]
                paths = await _run_sync(
                    render_topic_carousel,
                    cover_image=cover_image,
                    artwork_images=artworks,
                    plan=plan,
                    output_dir=folder,
                    post_index=post_index,
                    res_dir=RES_DIR,
                )
            return paths, plan
        except TextOverflowError as exc:
            overflow = (
                f"role: {exc.role}\ntext: {exc.text}\n"
                f"max_width: {exc.max_width}\nmax_height: {exc.max_height}"
            )
            logger.warning("Topic render overflow: %s", exc)
            if attempt == 0:
                plan = await _run_sync(repair_topic_slides, article, plan, overflow)
            else:
                plan = fallback_topic_slides(article)
            await _persist_topic_slides(post, plan, db_session)

    with ExitStack() as stack:
        cover_image = stack.enter_context(Image.open(cover_path))
        artworks = [stack.enter_context(Image.open(path)) for path in artwork_paths]
        paths = await _run_sync(
            render_topic_carousel,
            cover_image=cover_image,
            artwork_images=artworks,
            plan=plan,
            output_dir=folder,
            post_index=post_index,
            res_dir=RES_DIR,
        )
    return paths, plan


async def _all_posts_ready(
    protocol: Protocol,
    plan: EditorialPlan,
    db_session: AsyncSession,
) -> bool:
    result = await db_session.execute(
        select(Post)
        .options(selectinload(Post.assets))
        .where(Post.protocol_id == protocol.id)
    )
    posts = result.scalars().all()
    if len(posts) < 1 + len(plan.topics):
        return False
    for post in posts:
        if post.status != PostStatus.READY:
            return False
        for asset in post.assets:
            if asset.status != "ready" or not asset.path:
                return False
            if not Path(asset.path).exists():
                return False
    return True
