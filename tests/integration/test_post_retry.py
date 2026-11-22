"""Per-post retry state machine against a real PostgreSQL schema."""

import io
from datetime import date

import pytest
from PIL import Image
from sqlalchemy import select

from app.core.post_models import (
    CaptionDraft,
    EditorialPlan,
    FactCheckResult,
    SummaryBrief,
    SummaryDraft,
    TopicBrief,
    TopicDraft,
    VisualPrompts,
)
from app.models import EditorialPlan as EditorialPlanRow
from app.models import Post, PostAsset, PostSlide, Protocol
from app.services.caption_writer import CAPTION_FIRST_LINE
from app.services.llm_client import LLMAuthenticationError, LLMSchemaError
from app.services.output_cleanup import (
    cleanup_summary_output,
    cleanup_topic_output,
)
from app.services.post_pipeline import PostPipeline
from app.services.slide_composer import compose_topic_slides
from tests.support.fake_llm import FakeLLMClient

pytestmark = pytest.mark.integration

PROTOCOL_TEXT = (
    "TOP 1 Haushalt\n"
    "Der Rat beschließt den Haushalt einstimmig.\n"
    "\n"
    "TOP 2 Radweg\n"
    "Der Radweg an der Hauptstraße wird im Sommer gebaut.\n"
)
ANCHOR_HAUSHALT = "Der Rat beschließt den Haushalt einstimmig."
ANCHOR_RADWEG = "Der Radweg an der Hauptstraße wird im Sommer gebaut."

SUMMARY_STAGE_ROLES = {
    "writer": [
        "summary_writer",
        "summary_fact_check",
        "caption_writer",
        "summary_visual_prompts",
        "summary_cover",
    ],
    "slide_composer": [
        "summary_fact_check",
        "caption_writer",
        "summary_visual_prompts",
        "summary_cover",
    ],
    "fact_check": [
        "summary_fact_check",
        "caption_writer",
        "summary_visual_prompts",
        "summary_cover",
    ],
    "repair": [
        "summary_fact_check",
        "summary_repair",
        "summary_fact_check",
        "caption_writer",
        "summary_visual_prompts",
        "summary_cover",
    ],
    "caption": [
        "caption_writer",
        "summary_visual_prompts",
        "summary_cover",
    ],
    "visual_prompts": ["summary_visual_prompts", "summary_cover"],
    "image_generation": ["summary_cover"],
    "render": ["summary_cover"],
}

TOPIC_STAGE_ROLES = {
    "writer": [
        "topic_writer",
        "topic_fact_check",
        "caption_writer",
        "topic_visual_prompts",
        "topic_cover",
        "topic_pair_art",
        "topic_pair_art",
    ],
    "slide_composer": [
        "topic_fact_check",
        "caption_writer",
        "topic_visual_prompts",
        "topic_cover",
        "topic_pair_art",
        "topic_pair_art",
    ],
    "fact_check": [
        "topic_fact_check",
        "caption_writer",
        "topic_visual_prompts",
        "topic_cover",
        "topic_pair_art",
        "topic_pair_art",
    ],
    "repair": [
        "topic_fact_check",
        "topic_repair",
        "topic_fact_check",
        "caption_writer",
        "topic_visual_prompts",
        "topic_cover",
        "topic_pair_art",
        "topic_pair_art",
    ],
    "caption": [
        "caption_writer",
        "topic_visual_prompts",
        "topic_cover",
        "topic_pair_art",
        "topic_pair_art",
    ],
    "visual_prompts": [
        "topic_visual_prompts",
        "topic_cover",
        "topic_pair_art",
        "topic_pair_art",
    ],
    "image_generation": [
        "topic_cover",
        "topic_pair_art",
        "topic_pair_art",
    ],
    "render": [
        "topic_cover",
        "topic_pair_art",
        "topic_pair_art",
    ],
}


def _plan() -> EditorialPlan:
    return EditorialPlan(
        summary_focus="Haushalt und Radweg",
        summary_title="Was der Rat in Rosdorf entschieden hat",
        summary_briefs=[
            SummaryBrief(
                point="Der Haushalt wurde einstimmig beschlossen.",
                relevance="Die Mittel sind für alle Ortsteile wichtig.",
                source_anchors=[ANCHOR_HAUSHALT],
            ),
            SummaryBrief(
                point="Der Radweg an der Hauptstraße wird gebaut.",
                relevance="Das verbessert die Verbindung im Ort.",
                source_anchors=[ANCHOR_RADWEG],
            ),
        ],
        topic_briefs=[
            TopicBrief(
                slug="haushalt",
                title="Haushalt beschlossen",
                focus="Die wichtigsten Posten",
                relevance="Die Entscheidung betrifft alle Ortsteile.",
                source_anchors=[ANCHOR_HAUSHALT],
            )
        ],
    )


def _summary_draft(plan: EditorialPlan) -> SummaryDraft:
    return SummaryDraft(
        cover_title=plan.summary_title,
        points=[
            {
                "kicker": f"Thema{index}",
                "heading": brief.point,
                "body": (
                    f"Zum Punkt {index} hat der Rat beraten und entschieden. "
                    "Die Verwaltung setzt die Mittel im Frühjahr um."
                )[:120].ljust(120, "x"),
            }
            for index, brief in enumerate(plan.summary_briefs, start=1)
        ],
    )


def _topic_draft(brief: TopicBrief) -> TopicDraft:
    seed = (
        "Der Rat hat zu diesem Thema beraten und eine Entscheidung getroffen. "
        "Die Verwaltung setzt die Mittel im Frühjahr um."
    )
    text = ""
    while len(text) < 700:
        text = f"{text} {seed}".strip()
    text = text[:700].rsplit(" ", 1)[0].rstrip(" ,;") + "."
    return TopicDraft(
        title=f"{brief.title}: Was der Rat in Rosdorf entschieden hat"[:100],
        sections=[
            {
                "h2": f"Der Rat hat zu {brief.slug} entschieden",
                "paragraphs": [text],
            },
            {
                "h2": f"Was jetzt für {brief.slug} passiert",
                "paragraphs": [text],
            },
        ],
    )


def _cover_png_bytes() -> bytes:
    image = Image.new("RGB", (540, 960), (80, 120, 100))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _script_full_success(fake: FakeLLMClient, plan: EditorialPlan) -> None:
    fake.script_json("planner", plan)
    fake.script_json("summary_writer", _summary_draft(plan))
    fake.script_json("summary_fact_check", FactCheckResult(issues=[]))
    fake.script_json("caption_writer", CaptionDraft(body="Caption"))
    fake.script_json(
        "summary_visual_prompts",
        VisualPrompts(cover_prompt="Weite, ruhige Szene am Ortsrand."),
    )
    fake.script_image("summary_cover", _cover_png_bytes())
    for index, brief in enumerate(plan.topic_briefs, start=1):
        draft = _topic_draft(brief)
        composition = compose_topic_slides(draft)
        content_count = len(composition.slides) - 1
        pair_count = content_count // 2
        artwork_count = pair_count + (1 if content_count % 2 else 0)
        fake.script_json("topic_writer", draft)
        fake.script_json("topic_fact_check", FactCheckResult(issues=[]))
        fake.script_json(
            "caption_writer", CaptionDraft(body=f"Topic caption {index}")
        )
        fake.script_json(
            "topic_visual_prompts",
            VisualPrompts(
                cover_prompt=f"Cover für {brief.slug}",
                artwork_prompts=[
                    f"Paar {number} für {brief.slug}"
                    for number in range(1, artwork_count + 1)
                ],
            ),
        )
        fake.script_image("topic_cover", _cover_png_bytes())
        fake.script_image(
            "topic_pair_art",
            *[_cover_png_bytes() for _ in range(pair_count)],
        )
        if content_count % 2:
            fake.script_image("topic_single_art", _cover_png_bytes())


def _plan_with_slugs(slugs: list[str]) -> EditorialPlan:
    return EditorialPlan(
        summary_focus="Haushalt und Radweg",
        summary_title="Was der Rat in Rosdorf entschieden hat",
        summary_briefs=_plan().summary_briefs,
        topic_briefs=[
            TopicBrief(
                slug=slug,
                title=f"Thema {slug}",
                focus=f"Fokus {slug}",
                relevance="Die Entscheidung betrifft alle Ortsteile.",
                source_anchors=[ANCHOR_HAUSHALT],
            )
            for slug in slugs
        ],
    )



def _script_summary_retry(
    fake: FakeLLMClient, plan: EditorialPlan, stage: str
) -> None:
    draft = _summary_draft(plan)
    if stage == "writer":
        fake.script_json("summary_writer", draft)
    if stage in {"writer", "slide_composer", "fact_check"}:
        fake.script_json("summary_fact_check", FactCheckResult(issues=[]))
    if stage == "repair":
        fake.script_json(
            "summary_fact_check",
            FactCheckResult(issues=["Eine unbelegte Zahl."]),
            FactCheckResult(issues=[]),
        )
        fake.script_json("summary_repair", draft)
    if stage in {"writer", "slide_composer", "fact_check", "repair", "caption"}:
        fake.script_json("caption_writer", CaptionDraft(body="Neue Caption"))
    if stage in {
        "writer",
        "slide_composer",
        "fact_check",
        "repair",
        "caption",
        "visual_prompts",
    }:
        fake.script_json(
            "summary_visual_prompts",
            VisualPrompts(cover_prompt="Neue ruhige Szene."),
        )
    fake.script_image("summary_cover", _cover_png_bytes())


def _script_topic_retry(
    fake: FakeLLMClient, plan: EditorialPlan, stage: str
) -> None:
    brief = plan.topic_briefs[0]
    draft = _topic_draft(brief)
    composition = compose_topic_slides(draft)
    content_count = len(composition.slides) - 1
    pair_count = content_count // 2
    artwork_count = pair_count + (1 if content_count % 2 else 0)
    if stage == "writer":
        fake.script_json("topic_writer", draft)
    if stage in {"writer", "slide_composer", "fact_check"}:
        fake.script_json("topic_fact_check", FactCheckResult(issues=[]))
    if stage == "repair":
        fake.script_json(
            "topic_fact_check",
            FactCheckResult(issues=["Eine unbelegte Zahl."]),
            FactCheckResult(issues=[]),
        )
        fake.script_json("topic_repair", draft)
    if stage in {"writer", "slide_composer", "fact_check", "repair", "caption"}:
        fake.script_json("caption_writer", CaptionDraft(body="Neue Caption"))
    if stage in {
        "writer",
        "slide_composer",
        "fact_check",
        "repair",
        "caption",
        "visual_prompts",
    }:
        fake.script_json(
            "topic_visual_prompts",
            VisualPrompts(
                cover_prompt="Neues Cover",
                artwork_prompts=[
                    f"Neues Paar {index}"
                    for index in range(1, artwork_count + 1)
                ],
            ),
        )
    fake.script_image("topic_cover", _cover_png_bytes())
    fake.script_image(
        "topic_pair_art", *[_cover_png_bytes() for _ in range(pair_count)]
    )
    if content_count % 2:
        fake.script_image("topic_single_art", _cover_png_bytes())


async def _protocol(session) -> Protocol:
    protocol = Protocol(
        session_date=date(2024, 1, 15),
        title="Gemeinderat",
        getfile_id=123,
        pdf_text=PROTOCOL_TEXT,
    )
    session.add(protocol)
    await session.flush()
    return protocol


async def _posts(session, protocol: Protocol) -> list[Post]:
    result = await session.execute(
        select(Post)
        .where(Post.protocol_id == protocol.id)
        .order_by(Post.post_index)
    )
    return list(result.scalars().all())


async def _reload_post(session, post_id: int) -> Post:
    result = await session.execute(
        select(Post)
        .where(Post.id == post_id)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one()


async def _slides(session, post: Post) -> list[PostSlide]:
    result = await session.execute(
        select(PostSlide)
        .where(PostSlide.post_id == post.id)
        .order_by(PostSlide.slide_index)
    )
    return list(result.scalars().all())


async def _assets(session, post: Post) -> list[PostAsset]:
    result = await session.execute(
        select(PostAsset)
        .where(PostAsset.post_id == post.id)
        .order_by(PostAsset.id)
    )
    return list(result.scalars().all())


def _input_content(post: Post, plan: EditorialPlan) -> dict:
    content = post.content_json or {}
    if post.post_type == "summary":
        return {
            "briefs": content.get("briefs")
            or [brief.model_dump(mode="json") for brief in plan.summary_briefs],
            "excerpts": content.get("excerpts", []),
        }
    return {
        "brief": content.get("brief")
        or plan.topic_briefs[0].model_dump(mode="json"),
        "excerpts": content.get("excerpts", []),
    }


async def _delete_downstream(
    session,
    post: Post,
    *,
    clear_slides: bool = True,
    clear_assets: bool = True,
) -> None:
    if clear_slides:
        for slide in await _slides(session, post):
            await session.delete(slide)
    if clear_assets:
        for asset in await _assets(session, post):
            await session.delete(asset)
    await session.flush()


async def _simulate_failure(
    session,
    tmp_path,
    protocol: Protocol,
    post: Post,
    plan: EditorialPlan,
    stage: str,
) -> None:
    if post.post_type == "summary":
        cleanup_summary_output(tmp_path, protocol)
    else:
        cleanup_topic_output(tmp_path, protocol, post.slug)

    if stage in {"organ", "writer"}:
        post.content_json = _input_content(post, plan)
        post.content_markdown = None
        post.slide_plan_json = None
        post.caption = None
        post.alt_text_json = None
        post.fact_check_json = None
        await _delete_downstream(session, post)
    elif stage == "slide_composer":
        post.content_markdown = None
        post.slide_plan_json = None
        post.caption = None
        post.alt_text_json = None
        post.fact_check_json = None
        await _delete_downstream(session, post)
    elif stage in {"fact_check", "repair"}:
        post.caption = None
        post.alt_text_json = None
        post.fact_check_json = None
        await _delete_downstream(session, post, clear_slides=False)
    elif stage == "caption":
        post.caption = None
        post.alt_text_json = None
        await _delete_downstream(session, post)
    elif stage == "visual_prompts":
        await _delete_downstream(session, post, clear_slides=False)
    elif stage in {"image_generation", "render"}:
        for asset in await _assets(session, post):
            asset.status = "pending"
            asset.path = None
            asset.error = None
    elif stage == "source_retrieval":
        content = _input_content(post, plan)
        content["excerpts"] = []
        post.content_json = content
        post.content_markdown = None
        post.slide_plan_json = None
        post.caption = None
        post.alt_text_json = None
        post.fact_check_json = None
        await _delete_downstream(session, post)
    elif stage == "unknown":
        post.content_json = _input_content(post, plan)
        post.content_markdown = None
        post.slide_plan_json = None
        post.caption = None
        post.alt_text_json = None
        post.fact_check_json = None
        await _delete_downstream(session, post)

    post.status = "failed"
    post.failed_step = None if stage == "unknown" else stage
    post.error = "simulierter Fehler"
    await session.commit()


async def _run_success(session, tmp_path, fake: FakeLLMClient, plan: EditorialPlan):
    _script_full_success(fake, plan)
    protocol = await _protocol(session)
    pipeline = PostPipeline(fake, output_dir=tmp_path)
    await pipeline.run(protocol, session)
    posts = await _posts(session, protocol)
    return protocol, pipeline, posts


@pytest.mark.parametrize("stage", list(SUMMARY_STAGE_ROLES))
async def test_summary_retry_resumes_from_failed_step(
    postgres_session, tmp_path, stage
):
    plan = _plan()
    protocol, pipeline, posts = await _run_success(
        postgres_session, tmp_path, FakeLLMClient(), plan
    )
    summary, topic = posts
    assert summary.status == "ready"
    assert protocol.processed is True

    await _simulate_failure(
        postgres_session, tmp_path, protocol, summary, plan, stage
    )
    fake = pipeline.llm_client
    _script_summary_retry(fake, plan, stage)
    start = len(fake.calls)

    result = await pipeline.retry_post(summary, postgres_session)

    retry_roles = [call.role for call in fake.calls[start:]]
    assert retry_roles == SUMMARY_STAGE_ROLES[stage]
    assert "planner" not in retry_roles

    summary = await _reload_post(postgres_session, summary.id)
    topic = await _reload_post(postgres_session, topic.id)
    assert result.status == "ready"
    assert summary.status == "ready"
    assert summary.failed_step is None
    assert summary.title == _summary_draft(plan).cover_title
    assert summary.caption.startswith(CAPTION_FIRST_LINE)
    assert summary.fact_check_json["passed"] is True
    assert await _slides(postgres_session, summary)
    assert await _assets(postgres_session, summary)
    assert topic.status == "ready"
    assert protocol.processed is True


@pytest.mark.parametrize("stage", list(TOPIC_STAGE_ROLES))
async def test_topic_retry_resumes_from_failed_step(
    postgres_session, tmp_path, stage
):
    plan = _plan()
    protocol, pipeline, posts = await _run_success(
        postgres_session, tmp_path, FakeLLMClient(), plan
    )
    summary, topic = posts
    assert topic.status == "ready"
    assert protocol.processed is True
    summary_content = summary.content_json
    summary_caption = summary.caption

    await _simulate_failure(
        postgres_session, tmp_path, protocol, topic, plan, stage
    )
    fake = pipeline.llm_client
    _script_topic_retry(fake, plan, stage)
    start = len(fake.calls)

    result = await pipeline.retry_post(topic, postgres_session)

    retry_roles = [call.role for call in fake.calls[start:]]
    assert retry_roles == TOPIC_STAGE_ROLES[stage]
    assert "planner" not in retry_roles
    assert "summary_writer" not in retry_roles

    topic = await _reload_post(postgres_session, topic.id)
    summary = await _reload_post(postgres_session, summary.id)
    assert result.status == "ready"
    assert topic.status == "ready"
    assert topic.failed_step is None
    assert topic.title == _topic_draft(plan.topic_briefs[0]).title
    assert topic.caption.startswith(CAPTION_FIRST_LINE)
    assert topic.fact_check_json["passed"] is True
    assert await _slides(postgres_session, topic)
    assert await _assets(postgres_session, topic)
    assert summary.status == "ready"
    assert summary.content_json == summary_content
    assert summary.caption == summary_caption
    assert protocol.processed is True


async def test_retry_organ_resolves_again_and_resumes_at_writer(
    postgres_session, tmp_path
):
    plan = _plan()
    protocol, pipeline, posts = await _run_success(
        postgres_session, tmp_path, FakeLLMClient(), plan
    )
    summary, _ = posts
    await _simulate_failure(
        postgres_session, tmp_path, protocol, summary, plan, "organ"
    )
    _script_summary_retry(pipeline.llm_client, plan, "writer")
    start = len(pipeline.llm_client.calls)

    result = await pipeline.retry_post(summary, postgres_session)

    roles = [call.role for call in pipeline.llm_client.calls[start:]]
    assert roles == SUMMARY_STAGE_ROLES["writer"]
    assert result.status == "ready"


async def test_retry_source_retrieval_retrieves_anchors_then_writes(
    postgres_session, tmp_path
):
    plan = _plan()
    protocol, pipeline, posts = await _run_success(
        postgres_session, tmp_path, FakeLLMClient(), plan
    )
    summary, _ = posts
    await _simulate_failure(
        postgres_session, tmp_path, protocol, summary, plan, "source_retrieval"
    )
    _script_summary_retry(pipeline.llm_client, plan, "writer")
    start = len(pipeline.llm_client.calls)

    result = await pipeline.retry_post(summary, postgres_session)

    roles = [call.role for call in pipeline.llm_client.calls[start:]]
    assert roles == SUMMARY_STAGE_ROLES["writer"]
    summary = await _reload_post(postgres_session, summary.id)
    assert summary.content_json["excerpts"]
    assert result.status == "ready"


async def test_retry_unknown_step_with_draft_resumes_at_earliest_missing_artifact(
    postgres_session, tmp_path
):
    plan = _plan()
    protocol, pipeline, posts = await _run_success(
        postgres_session, tmp_path, FakeLLMClient(), plan
    )
    summary, _ = posts
    await _simulate_failure(
        postgres_session, tmp_path, protocol, summary, plan, "unknown"
    )
    _script_summary_retry(pipeline.llm_client, plan, "writer")
    start = len(pipeline.llm_client.calls)

    result = await pipeline.retry_post(summary, postgres_session)

    roles = [call.role for call in pipeline.llm_client.calls[start:]]
    assert roles == SUMMARY_STAGE_ROLES["writer"]
    assert result.status == "ready"


async def test_retry_after_writer_failure_reaches_ready(postgres_session, tmp_path):
    plan = _plan()
    fake = FakeLLMClient(
        json_responses={
            "planner": [plan],
            "summary_writer": [
                LLMSchemaError("first writer failure"),
                LLMSchemaError("second writer failure"),
            ],
        }
    )
    topic_draft = _topic_draft(plan.topic_briefs[0])
    fake.script_json("topic_writer", topic_draft)
    fake.script_json("topic_fact_check", FactCheckResult(issues=[]))
    fake.script_json("caption_writer", CaptionDraft(body="Topic caption"))
    fake.script_json(
        "topic_visual_prompts",
        VisualPrompts(
            cover_prompt="Cover",
            artwork_prompts=["Paar 1", "Paar 2"],
        ),
    )
    fake.script_image("topic_cover", _cover_png_bytes())
    fake.script_image("topic_pair_art", _cover_png_bytes(), _cover_png_bytes())
    protocol = await _protocol(postgres_session)
    pipeline = PostPipeline(fake, output_dir=tmp_path)
    await pipeline.run(protocol, postgres_session)

    summary, topic = await _posts(postgres_session, protocol)
    assert summary.status == "failed"
    assert summary.failed_step == "writer"
    assert protocol.processed is True

    _script_summary_retry(fake, plan, "writer")
    start = len(fake.calls)
    result = await pipeline.retry_post(summary, postgres_session)

    roles = [call.role for call in fake.calls[start:]]
    assert roles == SUMMARY_STAGE_ROLES["writer"]
    assert result.status == "ready"
    summary = await _reload_post(postgres_session, summary.id)
    assert summary.status == "ready"
    assert summary.failed_step is None
    assert protocol.processed is True


async def test_force_retry_updates_the_title_from_the_new_draft(
    postgres_session, tmp_path
):
    plan = _plan()
    protocol, pipeline, posts = await _run_success(
        postgres_session, tmp_path, FakeLLMClient(), plan
    )
    summary, _ = posts

    new_draft = _summary_draft(plan)
    new_draft.cover_title = "Haushalt"
    fake = pipeline.llm_client
    fake.script_json("summary_writer", new_draft)
    fake.script_json("summary_fact_check", FactCheckResult(issues=[]))
    fake.script_json("caption_writer", CaptionDraft(body="Neue Caption"))
    fake.script_json(
        "summary_visual_prompts",
        VisualPrompts(cover_prompt="Neue ruhige Szene."),
    )
    fake.script_image("summary_cover", _cover_png_bytes())

    result = await pipeline.retry_post(
        summary, postgres_session, force=True
    )

    summary = await _reload_post(postgres_session, summary.id)
    assert result.status == "ready"
    assert summary.title == "Haushalt"
    assert summary.content_json["draft"]["cover_title"] == "Haushalt"


async def test_second_failure_keeps_failed_with_the_new_step(
    postgres_session, tmp_path
):
    plan = _plan()
    fake = FakeLLMClient(
        json_responses={
            "planner": [plan],
            "summary_writer": [
                LLMSchemaError("first writer failure"),
                LLMSchemaError("second writer failure"),
            ],
        }
    )
    topic_draft = _topic_draft(plan.topic_briefs[0])
    fake.script_json("topic_writer", topic_draft)
    fake.script_json("topic_fact_check", FactCheckResult(issues=[]))
    fake.script_json("caption_writer", CaptionDraft(body="Topic caption"))
    fake.script_json(
        "topic_visual_prompts",
        VisualPrompts(cover_prompt="Cover", artwork_prompts=["Paar 1", "Paar 2"]),
    )
    fake.script_image("topic_cover", _cover_png_bytes())
    fake.script_image("topic_pair_art", _cover_png_bytes(), _cover_png_bytes())
    protocol = await _protocol(postgres_session)
    pipeline = PostPipeline(fake, output_dir=tmp_path)
    await pipeline.run(protocol, postgres_session)
    summary, _ = await _posts(postgres_session, protocol)
    assert summary.failed_step == "writer"

    fake.script_json("summary_writer", _summary_draft(plan))
    fake.script_json("summary_fact_check", FactCheckResult(issues=[]))
    fake.script_json("caption_writer", LLMSchemaError("caption broke"))
    result = await pipeline.retry_post(summary, postgres_session)

    summary = await _reload_post(postgres_session, summary.id)
    assert result.status == "failed"
    assert summary.status == "failed"
    assert summary.failed_step == "caption"
    assert "caption broke" in summary.error
    assert summary.content_json["draft"]["cover_title"] == plan.summary_title
    assert summary.fact_check_json["passed"] is True
    assert protocol.processed is True


async def test_force_retry_clears_only_that_post_and_reuses_plan_and_excerpts(
    postgres_session, tmp_path
):
    plan = _plan()
    protocol, pipeline, posts = await _run_success(
        postgres_session, tmp_path, FakeLLMClient(), plan
    )
    summary, topic = posts
    old_summary_slides = [slide.id for slide in await _slides(postgres_session, summary)]
    old_summary_assets = [asset.id for asset in await _assets(postgres_session, summary)]
    old_excerpts = summary.content_json["excerpts"]
    topic_draft = topic.content_json["draft"]
    topic_caption = topic.caption
    topic_slide_ids = [slide.id for slide in await _slides(postgres_session, topic)]
    plan_row = (
        await postgres_session.execute(
            select(EditorialPlanRow).where(
                EditorialPlanRow.protocol_id == protocol.id
            )
        )
    ).scalar_one()
    plan_id = plan_row.id
    plan_json = plan_row.plan_json

    folder = tmp_path / "240115_gemeinderat"
    unrelated = folder / "keep.txt"
    unrelated.write_text("keep", encoding="utf-8")
    topic_files_before = sorted(
        path.name for path in (folder / "topic-haushalt").iterdir()
    )

    fake = pipeline.llm_client
    _script_summary_retry(fake, plan, "writer")
    start = len(fake.calls)
    result = await pipeline.retry_post(summary, postgres_session, force=True)

    roles = [call.role for call in fake.calls[start:]]
    assert roles == SUMMARY_STAGE_ROLES["writer"]
    assert "planner" not in roles
    assert "topic_writer" not in roles
    assert result.status == "ready"

    summary = await _reload_post(postgres_session, summary.id)
    topic = await _reload_post(postgres_session, topic.id)
    assert summary.status == "ready"
    assert summary.content_json["excerpts"] == old_excerpts
    assert summary.fact_check_json["passed"] is True
    assert summary.caption.startswith(CAPTION_FIRST_LINE)
    new_slides = await _slides(postgres_session, summary)
    new_assets = await _assets(postgres_session, summary)
    assert new_slides and new_assets
    assert not ({slide.id for slide in new_slides} & set(old_summary_slides))
    assert not ({asset.id for asset in new_assets} & set(old_summary_assets))

    plan_row = (
        await postgres_session.execute(
            select(EditorialPlanRow).where(EditorialPlanRow.id == plan_id)
        )
    ).scalar_one()
    assert plan_row.plan_json == plan_json

    assert topic.content_json["draft"] == topic_draft
    assert topic.caption == topic_caption
    assert [slide.id for slide in await _slides(postgres_session, topic)] == (
        topic_slide_ids
    )
    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert sorted(
        path.name for path in (folder / "topic-haushalt").iterdir()
    ) == topic_files_before
    assert protocol.processed is True


async def test_reprocess_rebuilds_plan_posts_and_removes_stale_output(
    postgres_session, tmp_path
):
    plan = _plan_with_slugs(["haushalt"])
    protocol, pipeline, posts = await _run_success(
        postgres_session, tmp_path, FakeLLMClient(), plan
    )
    old_post_ids = [post.id for post in posts]
    assert protocol.processed is True

    folder = tmp_path / "240115_gemeinderat"
    stale_summary = folder / "summary-2024-01-15-story-09.png"
    stale_summary.write_text("stale", encoding="utf-8")
    stale_topic = folder / "topic-old"
    stale_topic.mkdir()
    (stale_topic / "topic-2024-01-15-01.png").write_text(
        "stale", encoding="utf-8"
    )
    keep = folder / "keep.txt"
    keep.write_text("keep", encoding="utf-8")

    new_plan = _plan_with_slugs(["radweg", "schule"])
    _script_full_success(pipeline.llm_client, new_plan)
    start = len(pipeline.llm_client.calls)

    result = await pipeline.reprocess_protocol(protocol, postgres_session)

    roles = [call.role for call in pipeline.llm_client.calls[start:]]
    assert roles[0] == "planner"
    assert result.plan_status == "ready"

    posts = await _posts(postgres_session, protocol)
    assert [post.slug for post in posts] == ["summary", "radweg", "schule"]
    assert [post.status for post in posts] == ["ready", "ready", "ready"]
    assert not ({post.id for post in posts} & set(old_post_ids))

    plan_row = (
        await postgres_session.execute(
            select(EditorialPlanRow).where(
                EditorialPlanRow.protocol_id == protocol.id
            )
        )
    ).scalar_one()
    assert plan_row.status == "ready"
    assert [
        brief["slug"] for brief in plan_row.plan_json["topic_briefs"]
    ] == ["radweg", "schule"]

    assert not stale_summary.exists()
    assert not stale_topic.exists()
    assert keep.read_text(encoding="utf-8") == "keep"
    assert sorted(
        path.name
        for path in folder.iterdir()
        if path.name.startswith("topic-")
    ) == ["topic-radweg", "topic-schule"]
    assert protocol.processed is True


async def test_reprocess_planner_failure_stays_unprocessed_then_recovers(
    postgres_session, tmp_path
):
    plan = _plan_with_slugs(["haushalt"])
    protocol, pipeline, posts = await _run_success(
        postgres_session, tmp_path, FakeLLMClient(), plan
    )
    assert protocol.processed is True
    folder = tmp_path / "240115_gemeinderat"
    assert folder.exists()

    pipeline.llm_client.script_json(
        "planner", LLMSchemaError("planner broke")
    )
    result = await pipeline.reprocess_protocol(protocol, postgres_session)

    plan_row = (
        await postgres_session.execute(
            select(EditorialPlanRow).where(
                EditorialPlanRow.protocol_id == protocol.id
            )
        )
    ).scalar_one()
    assert result.plan_status == "failed"
    assert plan_row.status == "failed"
    assert plan_row.failed_step == "planner"
    assert await _posts(postgres_session, protocol) == []
    assert protocol.processed is False
    assert not any(folder.iterdir())

    _script_full_success(pipeline.llm_client, plan)
    second = await pipeline.reprocess_protocol(protocol, postgres_session)

    posts = await _posts(postgres_session, protocol)
    assert second.plan_status == "ready"
    assert [post.status for post in posts] == ["ready", "ready"]
    assert protocol.processed is True


async def test_force_retry_topic_leaves_the_summary_and_other_files_alone(
    postgres_session, tmp_path
):
    plan = _plan()
    protocol, pipeline, posts = await _run_success(
        postgres_session, tmp_path, FakeLLMClient(), plan
    )
    summary, topic = posts
    summary_content = summary.content_json
    summary_caption = summary.caption
    summary_slide_ids = [
        slide.id for slide in await _slides(postgres_session, summary)
    ]
    folder = tmp_path / "240115_gemeinderat"
    summary_files = sorted(
        path.name for path in folder.iterdir() if path.is_file()
    )
    unrelated = folder / "keep.txt"
    unrelated.write_text("keep", encoding="utf-8")

    _script_topic_retry(pipeline.llm_client, plan, "writer")
    start = len(pipeline.llm_client.calls)
    result = await pipeline.retry_post(topic, postgres_session, force=True)

    roles = [call.role for call in pipeline.llm_client.calls[start:]]
    assert roles == TOPIC_STAGE_ROLES["writer"]
    assert result.status == "ready"

    summary = await _reload_post(postgres_session, summary.id)
    topic = await _reload_post(postgres_session, topic.id)
    assert summary.content_json == summary_content
    assert summary.caption == summary_caption
    assert [slide.id for slide in await _slides(postgres_session, summary)] == (
        summary_slide_ids
    )
    assert topic.status == "ready"
    assert sorted(
        path.name for path in folder.iterdir() if path.is_file()
    ) == sorted(summary_files + ["keep.txt"])
    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert (folder / "topic-haushalt" / "caption-topic-haushalt.txt").exists()
    assert protocol.processed is True


async def test_retry_authentication_error_propagates(postgres_session, tmp_path):
    plan = _plan()
    fake = FakeLLMClient(
        json_responses={
            "planner": [plan],
            "summary_writer": [
                LLMSchemaError("first writer failure"),
                LLMSchemaError("second writer failure"),
            ],
        }
    )
    topic_draft = _topic_draft(plan.topic_briefs[0])
    fake.script_json("topic_writer", topic_draft)
    fake.script_json("topic_fact_check", FactCheckResult(issues=[]))
    fake.script_json("caption_writer", CaptionDraft(body="Topic caption"))
    fake.script_json(
        "topic_visual_prompts",
        VisualPrompts(cover_prompt="Cover", artwork_prompts=["Paar 1", "Paar 2"]),
    )
    fake.script_image("topic_cover", _cover_png_bytes())
    fake.script_image("topic_pair_art", _cover_png_bytes(), _cover_png_bytes())
    protocol = await _protocol(postgres_session)
    pipeline = PostPipeline(fake, output_dir=tmp_path)
    await pipeline.run(protocol, postgres_session)
    summary, _ = await _posts(postgres_session, protocol)

    fake.script_json(
        "summary_writer", LLMAuthenticationError("Insufficient credits")
    )
    with pytest.raises(LLMAuthenticationError, match="Insufficient credits"):
        await pipeline.retry_post(summary, postgres_session)
