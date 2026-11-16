"""End-to-end ticket-03/04/05 behaviour against a real PostgreSQL schema."""

import io
from datetime import date

import httpx
import pytest
from PIL import Image
from sqlalchemy import select

from app.core.config import OPENROUTER_IMAGE_MODEL
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
from app.database import get_db
from app.main import app
from app.models import EditorialPlan as EditorialPlanRow
from app.models import Post, PostAsset, PostSlide, Protocol
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


def _summary_draft(plan: EditorialPlan) -> SummaryDraft:
    points = []
    for index, brief in enumerate(plan.summary_briefs, start=1):
        body = (
            f"Zum Punkt {index} hat der Rat beraten und entschieden. "
            "Die Verwaltung setzt die Mittel im Frühjahr um. "
            "Das betrifft alle Ortsteile gleichermaßen."
        )
        points.append(
            {
                "kicker": f"Thema{index}",
                "heading": brief.point,
                "body": body[:120].ljust(120, "x"),
            }
        )
    return SummaryDraft(cover_title=plan.summary_title, points=points)


def _cover_png_bytes() -> bytes:
    image = Image.new("RGB", (540, 960), (80, 120, 100))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _topic_paragraph(
    seed: str = (
        "Der Rat hat zu diesem Thema beraten und eine Entscheidung getroffen. "
        "Die Verwaltung setzt die Mittel im Frühjahr um."
    ),
    length: int = 700,
) -> str:
    text = ""
    while len(text) < length:
        text = f"{text} {seed}".strip()
    if len(text) > length:
        text = text[:length].rsplit(" ", 1)[0]
    return text.rstrip(" ,;") + "."


def _topic_draft(brief: TopicBrief, *, short: bool = False) -> TopicDraft:
    title = f"{brief.title}: Was der Rat in Rosdorf entschieden hat"[:100]
    if short:
        return TopicDraft(
            title=title,
            sections=[
                {
                    "h2": f"Der Rat hat zu {brief.slug} entschieden",
                    "paragraphs": ["Kurz."],
                },
                {
                    "h2": f"Was jetzt für {brief.slug} passiert",
                    "paragraphs": ["Auch kurz."],
                },
            ],
        )
    return TopicDraft(
        title=title,
        sections=[
            {
                "h2": f"Der Rat hat zu {brief.slug} entschieden",
                "paragraphs": [_topic_paragraph()],
            },
            {
                "h2": f"Was jetzt für {brief.slug} passiert",
                "paragraphs": [_topic_paragraph()],
            },
        ],
    )


def _script_summary_success(
    fake: FakeLLMClient,
    *,
    plan: EditorialPlan,
    fact_checks: list[object] | None = None,
) -> None:
    fake.script_json("summary_writer", _summary_draft(plan))
    fake.script_json(
        "summary_fact_check",
        *(fact_checks or [FactCheckResult(issues=[])]),
    )
    fake.script_json(
        "caption_writer",
        CaptionDraft(body="Der Rat hat wichtige Entscheidungen getroffen."),
    )
    fake.script_json(
        "summary_visual_prompts",
        VisualPrompts(cover_prompt="Weite, ruhige Szene am Ortsrand."),
    )
    fake.script_image("summary_cover", _cover_png_bytes())


def _script_topics_success(
    fake: FakeLLMClient,
    *,
    plan: EditorialPlan,
    drafts: list[TopicDraft] | None = None,
) -> None:
    fake.script_json(
        "topic_writer",
        *(drafts or [_topic_draft(brief) for brief in plan.topic_briefs]),
    )
    fake.script_json(
        "topic_fact_check",
        *[FactCheckResult(issues=[]) for _ in plan.topic_briefs],
    )
    fake.script_json(
        "caption_writer",
        *[
            CaptionDraft(body=f"Thema {index} im Überblick")
            for index in range(1, len(plan.topic_briefs) + 1)
        ],
    )


async def _run(
    session,
    tmp_path,
    *,
    plan: EditorialPlan | None = None,
    title: str = "Gemeinderat",
    fake: FakeLLMClient | None = None,
    script_summary: bool = True,
    script_topics: bool = True,
):
    fake = fake or FakeLLMClient()
    if plan is not None:
        fake.script_json("planner", plan)
        if script_summary:
            _script_summary_success(fake, plan=plan)
        if script_topics:
            _script_topics_success(fake, plan=plan)
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


async def test_pipeline_persists_summary_content_slides_caption_and_alt_texts(
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
    assert [post.status for post in posts] == ["ready", "draft", "draft"]
    assert [post.failed_step for post in posts] == [None, None, None]
    assert {post.generator_version for post in posts} == {"post-pipeline-v1"}

    summary = posts[0]
    draft = summary.content_json["draft"]
    assert draft["cover_title"] == plan.summary_title
    assert len(draft["points"]) == 2
    assert summary.content_json["excerpts"]
    assert any(
        "Der Rat beschließt den Haushalt" in excerpt["excerpt"]
        for excerpt in summary.content_json["excerpts"]
    )
    assert summary.content_markdown.startswith(f"# {plan.summary_title}")
    assert summary.slide_plan_json["family"] == "summary"
    assert summary.slide_plan_json["body_size"] in (42, 39, 36)
    assert len(summary.slide_plan_json["cards"]) == 2
    assert len(summary.alt_text_json) == 3
    assert all(summary.alt_text_json)

    assert summary.caption.startswith("Illustration: KI-generiert.\n")
    assert "Gemeinderat Rosdorf" in summary.caption
    assert "15.01.2024" in summary.caption
    assert "Ratsprotokoll vom 15.01.2024" in summary.caption
    assert "getfile.asp?id=1" in summary.caption
    assert summary.fact_check_json == {
        "passed": True,
        "issues": [],
        "repaired": False,
    }

    slides = await _slides(postgres_session, summary)
    assert [(slide.slide_index, slide.slide_type) for slide in slides] == [
        (1, "cover"),
        (2, "heading"),
        (3, "heading"),
    ]
    assert slides[0].label == "SITZUNG KOMPAKT"
    assert slides[0].headline == plan.summary_title
    assert slides[0].body is None
    assert slides[1].label == draft["points"][0]["kicker"]
    assert slides[1].headline == draft["points"][0]["heading"]
    assert slides[1].body == draft["points"][0]["body"]
    assert slides[1].pair_index is None
    assert all(slide.alt_text for slide in slides)

    assets = await _assets(postgres_session, summary)
    assert len(assets) == 1
    cover_asset = assets[0]
    assert cover_asset.role == "cover"
    assert cover_asset.status == "ready"
    assert cover_asset.error is None
    assert cover_asset.model == OPENROUTER_IMAGE_MODEL
    assert cover_asset.prompt == "Weite, ruhige Szene am Ortsrand."
    assert cover_asset.path is not None
    assert cover_asset.path.endswith("summary-2024-01-15-story-01.png")
    output_folder = tmp_path / "240115_gemeinderat"
    assert sorted(path.name for path in output_folder.iterdir()) == [
        "caption-summary-summary.txt",
        "summary-2024-01-15-story-01.png",
        "summary-2024-01-15-story-02.png",
        "summary-2024-01-15-story-03.png",
    ]
    assert (
        output_folder / "caption-summary-summary.txt"
    ).read_text(encoding="utf-8") == summary.caption

    haushalt = posts[1]
    assert haushalt.content_json["draft"]["title"]
    assert haushalt.content_json["draft"]["sections"]
    assert haushalt.content_json["excerpts"][0]["anchor"] == SUMMARY_ANCHOR_1
    assert haushalt.content_markdown.startswith("# ")
    assert haushalt.slide_plan_json["family"] == "topic"
    assert haushalt.caption.startswith("Illustration: KI-generiert.\n")
    assert all(haushalt.alt_text_json)
    haushalt_slides = await _slides(postgres_session, haushalt)
    assert haushalt_slides[0].slide_type == "cover"
    assert haushalt_slides[0].label == "THEMA IM FOKUS"
    assert haushalt_slides[1].slide_type == "heading"
    assert haushalt_slides[1].pair_index == 1
    assert [slide.slide_index for slide in haushalt_slides] == list(
        range(1, len(haushalt_slides) + 1)
    )

    assert result.plan_status == "ready"
    assert [post.status for post in result.posts] == ["ready", "draft", "draft"]
    assert protocol.processed is False

    assert [call.role for call in fake.calls] == [
        "planner",
        "summary_writer",
        "summary_fact_check",
        "caption_writer",
        "summary_visual_prompts",
        "summary_cover",
        "topic_writer",
        "topic_fact_check",
        "caption_writer",
        "topic_writer",
        "topic_fact_check",
        "caption_writer",
    ]
    assert PROTOCOL_TEXT in fake.calls[0].prompt
    for call in fake.calls[1:]:
        assert PROTOCOL_TEXT not in call.prompt
    assert "Die wichtigsten Posten" not in fake.calls[1].prompt
    visual_prompt_calls = fake.calls_for("summary_visual_prompts")
    assert len(visual_prompt_calls) == 1
    assert PROTOCOL_TEXT not in visual_prompt_calls[0].prompt
    assert "Die wichtigsten Posten" not in visual_prompt_calls[0].prompt
    assert SUMMARY_ANCHOR_1 not in visual_prompt_calls[0].prompt
    assert fake.image_calls[0].aspect_ratio == "9:16"

    # The summary content is visible through the ticket-02 read API.
    async def override_get_db():
        yield postgres_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            list_response = await client.get(f"/api/protocols/{protocol.id}/posts")
            summary_response = await client.get(f"/api/posts/{summary.id}")
            detail_response = await client.get(f"/api/posts/{haushalt.id}")
    finally:
        app.dependency_overrides.clear()

    assert list_response.status_code == 200
    listed = list_response.json()
    assert [post["slug"] for post in listed] == ["summary", "haushalt", "radweg"]
    assert [post["status"] for post in listed] == ["ready", "draft", "draft"]

    assert summary_response.status_code == 200
    summary_detail = summary_response.json()
    assert summary_detail["content_json"]["draft"]["cover_title"] == plan.summary_title
    assert summary_detail["content_markdown"].startswith(f"# {plan.summary_title}")
    assert summary_detail["slide_plan_json"]["body_size"] in (42, 39, 36)
    assert summary_detail["caption"].startswith("Illustration: KI-generiert.")
    assert summary_detail["fact_check_json"]["passed"] is True
    assert len(summary_detail["slides"]) == 3
    assert [slide["slide_index"] for slide in summary_detail["slides"]] == [1, 2, 3]
    assert summary_detail["alt_text_json"] == [
        slide["alt_text"] for slide in summary_detail["slides"]
    ]
    assert len(summary_detail["assets"]) == 1
    assert summary_detail["assets"][0]["role"] == "cover"
    assert summary_detail["assets"][0]["status"] == "ready"
    assert summary_detail["assets"][0]["path"] == cover_asset.path
    assert (
        summary_detail["assets"][0]["model"] == OPENROUTER_IMAGE_MODEL
    )

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["title"] == "Haushalt beschlossen"
    assert detail["content_json"]["draft"]["sections"]
    assert detail["content_json"]["excerpts"][0]["anchor"] == SUMMARY_ANCHOR_1
    assert detail["content_markdown"].startswith("# ")
    assert detail["slide_plan_json"]["family"] == "topic"
    assert detail["caption"].startswith("Illustration: KI-generiert.")
    assert len(detail["slides"]) == len(detail["alt_text_json"])


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
    assert haushalt.content_json["draft"]["sections"]
    assert radweg.status == "draft"
    assert radweg.content_json["draft"]["sections"]
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

    assert summary.status == "ready"
    assert haushalt.status == "failed"
    assert haushalt.failed_step == "source_retrieval"
    assert radweg.status == "draft"
    assert radweg.content_json["draft"]["sections"]
    assert radweg.content_json["excerpts"][0]["anchor"] == SUMMARY_ANCHOR_2
    assert [post.status for post in result.posts] == ["ready", "failed", "draft"]


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


async def test_summary_writer_failure_marks_only_the_summary_failed(
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
    _script_topics_success(fake, plan=plan)
    protocol = await _add_protocol(postgres_session)
    result = await PostPipeline(fake, output_dir=tmp_path).run(
        protocol, postgres_session
    )

    summary, haushalt, radweg = await _posts(postgres_session, protocol)

    assert summary.status == "failed"
    assert summary.failed_step == "writer"
    assert "second writer failure" in summary.error
    assert haushalt.status == "draft"
    assert haushalt.content_json["draft"]["sections"]
    assert radweg.status == "draft"
    assert radweg.content_json["draft"]["sections"]
    assert [post.status for post in result.posts] == ["failed", "draft", "draft"]

    plan_row = await _plan_row(postgres_session, protocol)
    assert plan_row.status == "ready"
    assert protocol.processed is False
    assert [call.role for call in fake.calls] == [
        "planner",
        "summary_writer",
        "summary_writer",
        "topic_writer",
        "topic_fact_check",
        "caption_writer",
        "topic_writer",
        "topic_fact_check",
        "caption_writer",
    ]


async def test_remaining_fact_check_issues_fail_at_fact_check_after_one_repair(
    postgres_session, tmp_path
):
    plan = _plan()
    draft = _summary_draft(plan)
    issues = ["Die Zahl 12 ist in den Quellen nicht belegt."]
    fake = FakeLLMClient(
        json_responses={
            "planner": [plan],
            "summary_writer": [draft],
            "summary_fact_check": [
                FactCheckResult(issues=issues),
                FactCheckResult(issues=issues),
            ],
            "summary_repair": [draft],
        }
    )
    _script_topics_success(fake, plan=plan)
    protocol = await _add_protocol(postgres_session)
    result = await PostPipeline(fake, output_dir=tmp_path).run(
        protocol, postgres_session
    )

    summary, haushalt, radweg = await _posts(postgres_session, protocol)

    assert summary.status == "failed"
    assert summary.failed_step == "fact_check"
    assert issues[0] in summary.error
    assert summary.fact_check_json["passed"] is False
    assert summary.fact_check_json["issues"] == issues
    assert haushalt.status == "draft"
    assert radweg.status == "draft"
    assert [post.status for post in result.posts] == ["failed", "draft", "draft"]
    assert [call.role for call in fake.calls] == [
        "planner",
        "summary_writer",
        "summary_fact_check",
        "summary_repair",
        "summary_fact_check",
        "topic_writer",
        "topic_fact_check",
        "caption_writer",
        "topic_writer",
        "topic_fact_check",
        "caption_writer",
    ]
    assert issues[0] in fake.calls[3].prompt


async def test_repair_call_failure_records_the_repair_step(
    postgres_session, tmp_path
):
    plan = _plan()
    draft = _summary_draft(plan)
    fake = FakeLLMClient(
        json_responses={
            "planner": [plan],
            "summary_writer": [draft],
            "summary_fact_check": [FactCheckResult(issues=["Ein Problem"])],
            "summary_repair": [LLMSchemaError("repair returned bad JSON")],
        }
    )
    _script_topics_success(fake, plan=plan)
    protocol = await _add_protocol(postgres_session)
    await PostPipeline(fake, output_dir=tmp_path).run(protocol, postgres_session)

    summary, haushalt, radweg = await _posts(postgres_session, protocol)

    assert summary.status == "failed"
    assert summary.failed_step == "repair"
    assert "repair returned bad JSON" in summary.error
    assert haushalt.status == "draft"
    assert radweg.status == "draft"


async def test_caption_failure_records_the_caption_step(postgres_session, tmp_path):
    plan = _plan()
    fake = FakeLLMClient(
        json_responses={
            "planner": [plan],
            "summary_writer": [_summary_draft(plan)],
            "summary_fact_check": [FactCheckResult(issues=[])],
            "caption_writer": [LLMSchemaError("caption returned bad JSON")],
        }
    )
    _script_topics_success(fake, plan=plan)
    protocol = await _add_protocol(postgres_session)
    await PostPipeline(fake, output_dir=tmp_path).run(protocol, postgres_session)

    summary, haushalt, radweg = await _posts(postgres_session, protocol)

    assert summary.status == "failed"
    assert summary.failed_step == "caption"
    assert "caption returned bad JSON" in summary.error
    assert summary.content_json["draft"]["cover_title"] == plan.summary_title
    assert haushalt.status == "draft"
    assert haushalt.content_json["draft"]["sections"]
    assert radweg.status == "draft"
    assert radweg.content_json["draft"]["sections"]


async def test_unfittable_summary_layout_records_the_slide_composer_step(
    postgres_session, tmp_path
):
    plan = _plan()
    draft = _summary_draft(plan)
    draft.points[0].heading = (
        "Donaudampfschifffahrtsgesellschaft "
        "Donaudampfschifffahrtsgesellschaft "
        "Donaudampfschifffahrtsgesellschaft "
        "Donaudampfschifffahrtsgesellschaft "
        "Donaudampfschifffahrtsgesellschaft"
    )
    fake = FakeLLMClient(
        json_responses={
            "planner": [plan],
            "summary_writer": [draft],
            "summary_fact_check": [FactCheckResult(issues=[])],
            "caption_writer": [CaptionDraft(body="Caption")],
        }
    )
    _script_topics_success(fake, plan=plan)
    protocol = await _add_protocol(postgres_session)
    await PostPipeline(fake, output_dir=tmp_path).run(protocol, postgres_session)

    summary, haushalt, radweg = await _posts(postgres_session, protocol)

    assert summary.status == "failed"
    assert summary.failed_step == "slide_composer"
    assert "heading" in summary.error
    assert [call.role for call in fake.calls[:2]] == [
        "planner",
        "summary_writer",
    ]
    assert haushalt.status == "draft"
    assert radweg.status == "draft"


async def test_rerun_resumes_draft_summary_and_topics_without_rewriting_content(
    postgres_session, tmp_path
):
    plan = _plan()
    fake = FakeLLMClient(
        json_responses={
            "planner": [plan],
            "summary_writer": [_summary_draft(plan)],
            "summary_fact_check": [FactCheckResult(issues=[])],
            "caption_writer": [CaptionDraft(body="Der Rat hat entschieden.")],
        }
    )
    _script_topics_success(fake, plan=plan)
    protocol = await _add_protocol(postgres_session)
    await PostPipeline(fake, output_dir=tmp_path).run(protocol, postgres_session)

    summary, haushalt, radweg = await _posts(postgres_session, protocol)
    assert summary.status == "failed"
    assert summary.failed_step == "visual_prompts"
    assert len(await _slides(postgres_session, summary)) == 3
    assert len(fake.calls_for("summary_writer")) == 1
    assert len(fake.calls_for("topic_writer")) == 2

    # Simulate a job that saved the content but stopped before the terminal
    # transition, so the next run resumes at the visual stage.
    summary.status = "draft"
    summary.failed_step = None
    summary.error = None
    await postgres_session.commit()

    fake.script_json(
        "summary_visual_prompts",
        VisualPrompts(cover_prompt="Weite, ruhige Szene am Ortsrand."),
    )
    fake.script_image("summary_cover", _cover_png_bytes())
    _script_topics_success(fake, plan=plan)
    second_result = await PostPipeline(fake, output_dir=tmp_path).run(
        protocol, postgres_session
    )

    summary, haushalt_again, radweg_again = await _posts(
        postgres_session, protocol
    )
    assert summary.status == "ready"
    assert len(await _slides(postgres_session, summary)) == 3
    assert len(fake.calls_for("summary_writer")) == 1
    assert len(fake.calls_for("summary_visual_prompts")) == 2
    assert len(fake.image_calls) == 1
    assert len(fake.calls_for("topic_writer")) == 4
    assert haushalt.status == haushalt_again.status == "draft"
    assert radweg.status == radweg_again.status == "draft"
    assert haushalt.content_json["draft"]["sections"]
    assert [post.status for post in second_result.posts] == [
        "ready",
        "draft",
        "draft",
    ]


async def test_rerun_never_retries_a_failed_summary(postgres_session, tmp_path):
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
    _script_topics_success(fake, plan=plan)
    protocol = await _add_protocol(postgres_session)
    pipeline = PostPipeline(fake, output_dir=tmp_path)
    await pipeline.run(protocol, postgres_session)

    summary, _, _ = await _posts(postgres_session, protocol)
    assert summary.status == "failed"
    assert len(fake.calls_for("summary_writer")) == 2
    assert len(fake.calls_for("topic_writer")) == 2

    _script_summary_success(fake, plan=plan)
    _script_topics_success(fake, plan=plan)
    await pipeline.run(protocol, postgres_session)

    summary, haushalt, radweg = await _posts(postgres_session, protocol)
    assert summary.status == "failed"
    assert len(fake.calls_for("summary_writer")) == 2
    assert len(fake.calls_for("topic_writer")) == 4
    assert haushalt.status == "draft"
    assert haushalt.content_json["draft"]["sections"]
    assert radweg.status == "draft"


async def test_successful_repair_recomposes_the_summary_from_the_repaired_draft(
    postgres_session, tmp_path
):
    plan = _plan()
    original = _summary_draft(plan)
    repaired = _summary_draft(plan)
    repaired.points[0].body = ("Der korrigierte Beschluss ist belegt. " * 5)[
        :120
    ].ljust(120, "x")
    issues = ["Der erste Entwurf enthielt eine unbelegte Zahl."]
    fake = FakeLLMClient(
        json_responses={
            "planner": [plan],
            "summary_writer": [original],
            "summary_fact_check": [
                FactCheckResult(issues=issues),
                FactCheckResult(issues=[]),
            ],
            "summary_repair": [repaired],
            "caption_writer": [CaptionDraft(body="Der Rat hat entschieden.")],
            "summary_visual_prompts": [
                VisualPrompts(cover_prompt="Weite, ruhige Szene am Ortsrand.")
            ],
        },
        image_responses={"summary_cover": [_cover_png_bytes()]},
    )
    _script_topics_success(fake, plan=plan)
    protocol = await _add_protocol(postgres_session)
    await PostPipeline(fake, output_dir=tmp_path).run(protocol, postgres_session)

    summary, _, _ = await _posts(postgres_session, protocol)
    slides = await _slides(postgres_session, summary)

    assert summary.status == "ready"
    assert summary.content_json["draft"]["points"][0]["body"] == (
        repaired.points[0].body
    )
    assert slides[1].body == repaired.points[0].body
    assert summary.fact_check_json == {
        "passed": True,
        "issues": [],
        "repaired": True,
    }
