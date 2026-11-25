"""End-to-end topic content path against a real PostgreSQL schema."""

import io
from datetime import date

import httpx
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
from app.database import get_db
from app.main import app
from app.models import Post, PostSlide, Protocol
from app.services.caption_writer import CAPTION_FIRST_LINE
from app.services.llm_client import LLMSchemaError
from app.services.post_pipeline import PostPipeline
from app.services.slide_composer import compose_topic_slides
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

ANCHOR_HAUSHALT = "Der Rat beschließt den Haushalt einstimmig."
ANCHOR_RADWEG = "Der Radweg an der Hauptstraße wird im Sommer gebaut."


def _summary_body(index: int) -> str:
    return (
        f"Zum Punkt {index} hat der Rat beraten und entschieden. "
        "Die Verwaltung setzt die Mittel im Frühjahr um. "
        "Das betrifft alle Ortsteile gleichermaßen."
    )[:120].ljust(120, "x")


def _cover_png_bytes() -> bytes:
    image = Image.new("RGB", (540, 960), (80, 120, 100))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


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
                focus="Die wichtigsten Posten im Gemeindehaushalt",
                relevance="Die Entscheidung betrifft alle Ortsteile.",
                source_anchors=[ANCHOR_HAUSHALT],
            ),
            TopicBrief(
                slug="radweg",
                title="Radweg kommt im Sommer",
                focus="Der neue Weg an der Hauptstraße",
                relevance="Bessere Verbindung für den Alltag.",
                source_anchors=[ANCHOR_RADWEG],
            ),
        ],
    )


def _summary_draft(plan: EditorialPlan) -> SummaryDraft:
    return SummaryDraft(
        cover_title=plan.summary_title,
        points=[
            {
                "kicker": f"Thema{index}",
                "heading": brief.point,
                "body": _summary_body(index),
            }
            for index, brief in enumerate(plan.summary_briefs, start=1)
        ],
    )


def _paragraph(seed: str, length: int = 700) -> str:
    text = ""
    while len(text) < length:
        text = f"{text} {seed}".strip()
    if len(text) > length:
        text = text[:length].rsplit(" ", 1)[0]
    return text.rstrip(" ,;") + "."


def _topic_draft(
    brief: TopicBrief,
    *,
    title: str | None = None,
    short: bool = False,
    seed: str | None = None,
) -> TopicDraft:
    title = title or (
        f"{brief.title}: Was der Rat in Rosdorf entschieden hat"
    )[:100]
    if short:
        return TopicDraft(
            title=title,
            sections=[
                {"h2": f"Der Rat hat zu {brief.slug} entschieden", "paragraphs": ["Kurz."]},
                {"h2": f"Was jetzt für {brief.slug} passiert", "paragraphs": ["Auch kurz."]},
            ],
        )
    text = seed or (
        "Der Rat hat zu diesem Thema beraten und eine Entscheidung "
        "getroffen. Die Verwaltung setzt die Mittel im Frühjahr um."
    )
    return TopicDraft(
        title=title,
        sections=[
            {
                "h2": f"Der Rat hat zu {brief.slug} entschieden",
                "paragraphs": [_paragraph(text)],
            },
            {
                "h2": f"Was jetzt für {brief.slug} passiert",
                "paragraphs": [_paragraph(text)],
            },
        ],
    )


def _script_happy_path(
    fake: FakeLLMClient,
    plan: EditorialPlan,
    *,
    topic_drafts: list[TopicDraft] | None = None,
) -> None:
    fake.script_json("planner", plan)
    fake.script_json("summary_writer", _summary_draft(plan))
    fake.script_json("summary_fact_check", FactCheckResult(issues=[]))
    drafts = topic_drafts or [
        _topic_draft(brief) for brief in plan.topic_briefs
    ]
    fake.script_json("topic_writer", *drafts)
    fake.script_json(
        "topic_fact_check",
        *[FactCheckResult(issues=[]) for _ in plan.topic_briefs],
    )
    fake.script_json(
        "caption_writer",
        *[
            CaptionDraft(body=f"Caption {index}")
            for index in range(len(plan.topic_briefs) + 1)
        ],
    )


def _script_topic_visuals(
    fake: FakeLLMClient, drafts: list[TopicDraft]
) -> None:
    for draft in drafts:
        composition = compose_topic_slides(draft)
        content_count = len(composition.slides) - 1
        pair_count = content_count // 2
        fake.script_json(
            "topic_visual_prompts",
            VisualPrompts(
                cover_prompt=f"Cover für {draft.title}",
                artwork_prompts=[
                    f"Paar {index} für {draft.title}"
                    for index in range(1, pair_count + 1)
                ],
                single_prompt=(
                    f"Single strip für {draft.title}"
                    if content_count % 2
                    else None
                ),
            ),
        )
        fake.script_image("topic_cover", _cover_png_bytes())
        if pair_count:
            fake.script_image(
                "topic_pair_art", *[_cover_png_bytes() for _ in range(pair_count)]
            )
        if content_count % 2:
            fake.script_image("topic_single_art", _cover_png_bytes())


async def _add_protocol(session) -> Protocol:
    protocol = Protocol(
        session_date=date(2024, 1, 15),
        title="Gemeinderat",
        getfile_id=1,
        pdf_text=PROTOCOL_TEXT,
    )
    session.add(protocol)
    await session.flush()
    return protocol


async def _run(session, tmp_path, plan, fake):
    fake.script_json(
        "summary_visual_prompts",
        VisualPrompts(cover_prompt="Weite, ruhige Szene am Ortsrand."),
    )
    fake.script_image("summary_cover", _cover_png_bytes())
    protocol = await _add_protocol(session)
    result = await PostPipeline(fake, output_dir=tmp_path).run(protocol, session)
    return protocol, result


async def _posts(session, protocol: Protocol) -> list[Post]:
    result = await session.execute(
        select(Post)
        .where(Post.protocol_id == protocol.id)
        .order_by(Post.post_index)
    )
    return list(result.scalars().all())


async def _slides(session, post: Post) -> list[PostSlide]:
    result = await session.execute(
        select(PostSlide)
        .where(PostSlide.post_id == post.id)
        .order_by(PostSlide.slide_index)
    )
    return list(result.scalars().all())


async def test_summary_failure_does_not_block_topic_content(
    postgres_session, tmp_path
):
    plan = _plan()
    fake = FakeLLMClient(
        json_responses={
            "planner": [plan],
            "summary_writer": [
                LLMSchemaError("first summary writer failure"),
                LLMSchemaError("second summary writer failure"),
            ],
            "topic_writer": [
                _topic_draft(brief) for brief in plan.topic_briefs
            ],
            "topic_fact_check": [FactCheckResult(issues=[])] * 2,
            "caption_writer": [
                CaptionDraft(body="Caption Haushalt"),
                CaptionDraft(body="Caption Radweg"),
            ],
        }
    )
    _script_topic_visuals(
        fake, [_topic_draft(brief) for brief in plan.topic_briefs]
    )

    protocol, result = await _run(postgres_session, tmp_path, plan, fake)
    summary, haushalt, radweg = await _posts(postgres_session, protocol)

    assert summary.status == "failed"
    assert summary.failed_step == "writer"
    assert haushalt.status == "ready"
    assert radweg.status == "ready"
    assert result.plan_status == "ready"
    assert [post.status for post in result.posts] == [
        "failed",
        "ready",
        "ready",
    ]

    for post, brief in zip((haushalt, radweg), plan.topic_briefs):
        draft = post.content_json["draft"]
        assert draft["title"] == _topic_draft(brief).title
        assert post.content_json["excerpts"]
        assert post.content_markdown.startswith(f"# {draft['title']}")
        assert post.slide_plan_json["family"] == "topic"
        assert post.slide_plan_json["body_size"] in (42, 39, 36)
        assert 4 <= len(post.slide_plan_json["slides"]) <= 7
        assert post.caption.startswith(f"{CAPTION_FIRST_LINE}\n")
        post_slides = await _slides(postgres_session, post)
        assert len(post.alt_text_json) == len(post_slides)
        assert all(post.alt_text_json)
        assert post.fact_check_json == {
            "passed": True,
            "issues": [],
            "repaired": False,
        }

    slides = await _slides(postgres_session, haushalt)
    assert slides[0].slide_index == 1
    assert slides[0].slide_type == "cover"
    assert slides[0].label == "IM FOKUS"
    assert slides[0].headline == haushalt.content_json["draft"]["title"]
    assert slides[0].body is None
    assert slides[1].slide_index == 2
    assert slides[1].slide_type == "heading"
    assert slides[1].headline == haushalt.content_json["draft"]["sections"][0]["h2"]
    assert slides[1].pair_index == 1
    assert [slide.slide_index for slide in slides] == list(
        range(1, len(slides) + 1)
    )

    # Input isolation: the topic writer got only its own brief and excerpts.
    writer_calls = fake.calls_for("topic_writer")
    assert len(writer_calls) == 2
    assert plan.topic_briefs[0].focus in writer_calls[0].prompt
    assert plan.topic_briefs[1].focus not in writer_calls[0].prompt
    assert plan.summary_title not in writer_calls[0].prompt
    assert PROTOCOL_TEXT not in writer_calls[0].prompt
    assert plan.topic_briefs[1].focus in writer_calls[1].prompt
    assert plan.topic_briefs[0].focus not in writer_calls[1].prompt
    assert PROTOCOL_TEXT not in writer_calls[1].prompt
    for call in fake.calls_for("topic_fact_check"):
        assert PROTOCOL_TEXT not in call.prompt
    for call in fake.calls_for("caption_writer"):
        assert PROTOCOL_TEXT not in call.prompt

    # The persisted content is visible through the read API.
    async def override_get_db():
        yield postgres_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            detail_response = await client.get(f"/api/posts/{haushalt.id}")
    finally:
        app.dependency_overrides.clear()

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["post_type"] == "topic"
    assert detail["status"] == "ready"
    assert detail["content_json"]["draft"]["sections"]
    assert detail["content_markdown"].startswith("# ")
    assert detail["slide_plan_json"]["family"] == "topic"
    assert detail["caption"].startswith(CAPTION_FIRST_LINE)
    assert len(detail["slides"]) == len(detail["alt_text_json"])
    assert [slide["slide_index"] for slide in detail["slides"]] == list(
        range(1, len(detail["slides"]) + 1)
    )
    assert detail["slides"][1]["slide_type"] == "heading"
    assert detail["slides"][1]["headline"]


async def test_one_topic_fact_check_failure_leaves_other_topics_draft(
    postgres_session, tmp_path
):
    plan = _plan()
    haushalt_draft = _topic_draft(plan.topic_briefs[0])
    radweg_draft = _topic_draft(plan.topic_briefs[1])
    summary_draft = _summary_draft(plan)
    issues = ["Die Zahl 12 ist in den Quellen nicht belegt."]
    fake = FakeLLMClient(
        json_responses={
            "planner": [plan],
            "summary_writer": [summary_draft],
            "summary_fact_check": [FactCheckResult(issues=[])],
            "topic_writer": [haushalt_draft, radweg_draft],
            "topic_fact_check": [
                FactCheckResult(issues=issues),
                FactCheckResult(issues=issues),
                FactCheckResult(issues=[]),
            ],
            "topic_repair": [haushalt_draft],
            "caption_writer": [
                CaptionDraft(body="Caption Summary"),
                CaptionDraft(body="Caption Radweg"),
            ],
        }
    )
    _script_topic_visuals(fake, [haushalt_draft, radweg_draft])

    protocol, result = await _run(postgres_session, tmp_path, plan, fake)
    summary, haushalt, radweg = await _posts(postgres_session, protocol)

    assert summary.status == "ready"
    assert summary.content_json["draft"]["cover_title"] == plan.summary_title
    assert summary.fact_check_json["passed"] is True
    assert summary.caption.startswith(CAPTION_FIRST_LINE)

    assert haushalt.status == "failed"
    assert haushalt.failed_step == "fact_check"
    assert issues[0] in haushalt.error
    assert haushalt.fact_check_json == {
        "passed": False,
        "issues": issues,
        "repaired": True,
    }

    assert radweg.status == "ready"
    assert radweg.content_json["draft"]["title"] == radweg_draft.title
    assert radweg.fact_check_json["passed"] is True
    assert [post.status for post in result.posts] == [
        "ready",
        "failed",
        "ready",
    ]

    repair_calls = fake.calls_for("topic_repair")
    assert len(repair_calls) == 1
    assert issues[0] in repair_calls[0].prompt
    assert PROTOCOL_TEXT not in repair_calls[0].prompt
    assert plan.topic_briefs[1].focus not in repair_calls[0].prompt


async def test_composition_failure_retries_the_writer_with_feedback(
    postgres_session, tmp_path
):
    plan = _plan()
    too_short = _topic_draft(plan.topic_briefs[0], short=True)
    valid = _topic_draft(plan.topic_briefs[0])
    radweg = _topic_draft(plan.topic_briefs[1])
    fake = FakeLLMClient(
        json_responses={
            "planner": [plan],
            "summary_writer": [_summary_draft(plan)],
            "summary_fact_check": [FactCheckResult(issues=[])],
            "topic_writer": [too_short, valid, radweg],
            "topic_fact_check": [FactCheckResult(issues=[])] * 2,
            "caption_writer": [
                CaptionDraft(body="Caption Summary"),
                CaptionDraft(body="Caption Haushalt"),
                CaptionDraft(body="Caption Radweg"),
            ],
        }
    )
    _script_topic_visuals(fake, [valid, radweg])

    protocol, _ = await _run(postgres_session, tmp_path, plan, fake)
    _, haushalt, radweg_post = await _posts(postgres_session, protocol)

    haushalt_calls = [
        call
        for call in fake.calls_for("topic_writer")
        if plan.topic_briefs[0].focus in call.prompt
    ]
    assert len(haushalt_calls) == 2
    assert "Korrekturhinweis" not in haushalt_calls[0].prompt
    assert "Korrekturhinweis" in haushalt_calls[1].prompt
    assert "content slides" in haushalt_calls[1].prompt
    assert PROTOCOL_TEXT not in haushalt_calls[1].prompt

    assert haushalt.status == "ready"
    assert haushalt.failed_step is None
    assert 4 <= len(haushalt.slide_plan_json["slides"]) <= 7
    assert radweg_post.status == "ready"


async def test_persistent_composition_failure_fails_at_slide_composer(
    postgres_session, tmp_path
):
    plan = _plan()
    too_short = _topic_draft(plan.topic_briefs[0], short=True)
    radweg = _topic_draft(plan.topic_briefs[1])
    fake = FakeLLMClient(
        json_responses={
            "planner": [plan],
            "summary_writer": [_summary_draft(plan)],
            "summary_fact_check": [FactCheckResult(issues=[])],
            "topic_writer": [too_short, too_short, radweg],
            "topic_fact_check": [FactCheckResult(issues=[])],
            "caption_writer": [
                CaptionDraft(body="Caption Summary"),
                CaptionDraft(body="Caption Radweg"),
            ],
        }
    )
    _script_topic_visuals(fake, [radweg])

    protocol, _ = await _run(postgres_session, tmp_path, plan, fake)
    _, haushalt, radweg_post = await _posts(postgres_session, protocol)

    assert haushalt.status == "failed"
    assert haushalt.failed_step == "slide_composer"
    assert "content slides" in haushalt.error
    assert radweg_post.status == "ready"
    assert len(fake.calls_for("topic_writer")) == 3


async def test_topic_writer_failure_marks_only_that_topic_failed(
    postgres_session, tmp_path
):
    plan = _plan()
    invalid = {"title": "Zu kurz", "sections": []}
    radweg = _topic_draft(plan.topic_briefs[1])
    fake = FakeLLMClient(
        json_responses={
            "planner": [plan],
            "summary_writer": [_summary_draft(plan)],
            "summary_fact_check": [FactCheckResult(issues=[])],
            "topic_writer": [invalid, invalid, radweg],
            "topic_fact_check": [FactCheckResult(issues=[])],
            "caption_writer": [
                CaptionDraft(body="Caption Summary"),
                CaptionDraft(body="Caption Radweg"),
            ],
        }
    )
    _script_topic_visuals(fake, [radweg])

    protocol, _ = await _run(postgres_session, tmp_path, plan, fake)
    summary, haushalt, radweg_post = await _posts(postgres_session, protocol)

    assert summary.status == "ready"
    assert summary.content_json["draft"]["cover_title"] == plan.summary_title
    assert haushalt.status == "failed"
    assert haushalt.failed_step == "writer"
    assert "after retry" in haushalt.error
    assert radweg_post.status == "ready"


async def test_topic_caption_failure_records_the_caption_step(
    postgres_session, tmp_path
):
    plan = _plan()
    fake = FakeLLMClient(
        json_responses={
            "planner": [plan],
            "summary_writer": [_summary_draft(plan)],
            "summary_fact_check": [FactCheckResult(issues=[])],
            "topic_writer": [
                _topic_draft(brief) for brief in plan.topic_briefs
            ],
            "topic_fact_check": [FactCheckResult(issues=[])] * 2,
            "caption_writer": [
                CaptionDraft(body="Caption Summary"),
                LLMSchemaError("caption returned bad JSON"),
                CaptionDraft(body="Caption Radweg"),
            ],
        }
    )
    _script_topic_visuals(fake, [_topic_draft(plan.topic_briefs[1])])

    protocol, _ = await _run(postgres_session, tmp_path, plan, fake)
    summary, haushalt, radweg = await _posts(postgres_session, protocol)

    assert summary.status == "ready"
    assert haushalt.status == "failed"
    assert haushalt.failed_step == "caption"
    assert "caption returned bad JSON" in haushalt.error
    assert radweg.status == "ready"


async def test_topic_repair_call_failure_records_the_repair_step(
    postgres_session, tmp_path
):
    plan = _plan()
    fake = FakeLLMClient(
        json_responses={
            "planner": [plan],
            "summary_writer": [_summary_draft(plan)],
            "summary_fact_check": [FactCheckResult(issues=[])],
            "topic_writer": [
                _topic_draft(brief) for brief in plan.topic_briefs
            ],
            "topic_fact_check": [
                FactCheckResult(issues=["Ein Problem"]),
                FactCheckResult(issues=[]),
            ],
            "topic_repair": [
                LLMSchemaError("repair returned bad JSON")
            ],
            "caption_writer": [
                CaptionDraft(body="Caption Summary"),
                CaptionDraft(body="Caption Radweg"),
            ],
        }
    )
    _script_topic_visuals(
        fake, [_topic_draft(plan.topic_briefs[1])]
    )

    protocol, _ = await _run(postgres_session, tmp_path, plan, fake)
    summary, haushalt, radweg = await _posts(postgres_session, protocol)

    assert summary.status == "ready"
    assert haushalt.status == "failed"
    assert haushalt.failed_step == "repair"
    assert "repair returned bad JSON" in haushalt.error
    assert radweg.status == "ready"


async def test_successful_topic_repair_recomposes_the_topic(
    postgres_session, tmp_path
):
    plan = _plan()
    original = _topic_draft(plan.topic_briefs[0])
    repaired = _topic_draft(
        plan.topic_briefs[0],
        title="Haushalt: Der korrigierte Beschluss im Überblick",
        seed=(
            "Der korrigierte Beschluss ist belegt und die Verwaltung "
            "setzt die Mittel im Frühjahr um."
        ),
    )
    issues = ["Der erste Entwurf enthielt eine unbelegte Zahl."]
    fake = FakeLLMClient(
        json_responses={
            "planner": [plan],
            "summary_writer": [_summary_draft(plan)],
            "summary_fact_check": [FactCheckResult(issues=[])],
            "topic_writer": [original, _topic_draft(plan.topic_briefs[1])],
            "topic_fact_check": [
                FactCheckResult(issues=issues),
                FactCheckResult(issues=[]),
                FactCheckResult(issues=[]),
            ],
            "topic_repair": [repaired],
            "caption_writer": [
                CaptionDraft(body="Caption Summary"),
                CaptionDraft(body="Caption Haushalt"),
                CaptionDraft(body="Caption Radweg"),
            ],
        }
    )
    _script_topic_visuals(
        fake, [repaired, _topic_draft(plan.topic_briefs[1])]
    )

    protocol, _ = await _run(postgres_session, tmp_path, plan, fake)
    _, haushalt, radweg = await _posts(postgres_session, protocol)

    assert haushalt.status == "ready"
    assert haushalt.failed_step is None
    assert haushalt.content_json["draft"]["title"] == repaired.title
    assert haushalt.content_markdown.startswith(f"# {repaired.title}")
    assert haushalt.fact_check_json == {
        "passed": True,
        "issues": [],
        "repaired": True,
    }
    slides = await _slides(postgres_session, haushalt)
    bodies = " ".join(slide.body for slide in slides if slide.body)
    assert "Der korrigierte Beschluss ist belegt" in bodies
    assert radweg.status == "ready"
