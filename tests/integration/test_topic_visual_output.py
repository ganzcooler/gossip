"""Integration tests for the topic visual output path against PostgreSQL."""

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
    TopicVisualPrompts,
    VisualPrompts,
)
from app.database import get_db
from app.main import app
from app.models import Post, PostAsset, PostSlide, Protocol
from app.services import post_pipeline as pipeline_module
from app.services.caption_writer import CAPTION_FIRST_LINE
from app.services.image_generation import IMAGE_STYLE_SUFFIX, topic_pair_fallback_art
from app.services.llm_client import (
    LLMAuthenticationError,
    LLMSchemaError,
    LLMTransportError,
)
from app.services.post_pipeline import PostPipeline
from app.services.post_renderer import RenderError
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


def _paragraph(length: int = 700) -> str:
    seed = (
        "Der Rat hat zu diesem Thema beraten und eine Entscheidung getroffen. "
        "Die Verwaltung setzt die Mittel im Frühjahr um."
    )
    text = ""
    while len(text) < length:
        text = f"{text} {seed}".strip()
    if len(text) > length:
        text = text[:length].rsplit(" ", 1)[0]
    return text.rstrip(" ,;") + "."


def _topic_draft(brief: TopicBrief) -> TopicDraft:
    return TopicDraft(
        title=f"{brief.title}: Was der Rat in Rosdorf entschieden hat"[:100],
        sections=[
            {
                "h2": f"Der Rat hat zu {brief.slug} entschieden",
                "paragraphs": [_paragraph()],
            },
            {
                "h2": f"Was jetzt für {brief.slug} passiert",
                "paragraphs": [_paragraph()],
            },
        ],
    )


def _png_bytes(size=(720, 900), color=(80, 120, 100)) -> bytes:
    image = Image.new("RGB", size, color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _script_success(
    fake: FakeLLMClient,
    plan: EditorialPlan,
    *,
    topic_visuals: object | None = None,
    topic_image: object | None = None,
) -> None:
    fake.script_json("planner", plan)
    fake.script_json("summary_writer", _summary_draft(plan))
    fake.script_json("summary_fact_check", FactCheckResult(issues=[]))
    fake.script_json(
        "caption_writer",
        *[
            CaptionDraft(body=f"Caption {index}")
            for index in range(len(plan.topic_briefs) + 1)
        ],
    )
    fake.script_json(
        "summary_visual_prompts",
        VisualPrompts(cover_prompt="Weite, ruhige Szene am Ortsrand."),
    )
    fake.script_image("summary_cover", _png_bytes(size=(540, 960)))
    fake.script_json(
        "topic_writer", *[_topic_draft(brief) for brief in plan.topic_briefs]
    )
    fake.script_json(
        "topic_fact_check",
        *[FactCheckResult(issues=[]) for _ in plan.topic_briefs],
    )
    fake.script_json(
        "topic_visual_prompts",
        *(
            [topic_visuals]
            if topic_visuals is not None
            else [
                TopicVisualPrompts(
                    cover_prompt=f"Cover {brief.slug}",
                    artwork_prompts=[
                        f"Pair {brief.slug} 1",
                        f"Pair {brief.slug} 2",
                    ],
                )
                for brief in plan.topic_briefs
            ]
        ),
    )
    for index, _ in enumerate(plan.topic_briefs):
        cover_image = (
            _png_bytes(color=(70 + index * 40, 110, 90))
            if topic_image is None
            else topic_image
        )
        fake.script_image("topic_cover", cover_image)
        pair_color = (60, 100 + index * 40, 140)
        fake.script_image(
            "topic_pair_art",
            _png_bytes(color=pair_color),
            _png_bytes(color=pair_color),
        )


async def _protocol(session) -> Protocol:
    protocol = Protocol(
        session_date=date(2024, 1, 15),
        title="Gemeinderat",
        getfile_id=99,
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
        .order_by(PostAsset.role)
    )
    return list(result.scalars().all())


async def _asgi_client(session) -> httpx.AsyncClient:
    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_full_protocol_renders_summary_and_topics_with_assets_and_api_paths(
    postgres_session, tmp_path
):
    plan = _plan()
    fake = FakeLLMClient()
    _script_success(fake, plan)
    protocol = await _protocol(postgres_session)

    result = await PostPipeline(fake, output_dir=tmp_path).run(
        protocol, postgres_session
    )

    summary, haushalt, radweg = await _posts(postgres_session, protocol)
    assert [post.status for post in result.posts] == [
        "ready",
        "ready",
        "ready",
    ]
    assert [post.failed_step for post in result.posts] == [None, None, None]
    assert protocol.processed is True

    for post in (summary, haushalt, radweg):
        assert post.caption.startswith(f"{CAPTION_FIRST_LINE}\n")
        assert post.alt_text_json

    haushalt_assets = await _assets(postgres_session, haushalt)
    assert [asset.role for asset in haushalt_assets] == [
        "cover",
        "pair_1",
        "pair_2",
    ]
    assert [asset.status for asset in haushalt_assets] == [
        "ready",
        "ready",
        "ready",
    ]
    for asset in haushalt_assets:
        assert asset.model
        assert asset.prompt
        assert asset.prompt.endswith(IMAGE_STYLE_SUFFIX)
        assert asset.error is None
        assert asset.path
    assert haushalt_assets[0].path.endswith(
        "topic-haushalt/topic-2024-01-15-01.png"
    )
    assert haushalt_assets[1].path.endswith(
        "topic-haushalt/topic-2024-01-15-02.png"
    )
    assert haushalt_assets[2].path.endswith(
        "topic-haushalt/topic-2024-01-15-04.png"
    )

    folder = tmp_path / "240115_gemeinderat"
    assert sorted(path.name for path in folder.iterdir()) == [
        "caption-summary-summary.txt",
        "summary-2024-01-15-story-01.png",
        "summary-2024-01-15-story-02.png",
        "summary-2024-01-15-story-03.png",
        "topic-haushalt",
        "topic-radweg",
    ]
    for slug in ("haushalt", "radweg"):
        topic_folder = folder / f"topic-{slug}"
        assert sorted(path.name for path in topic_folder.iterdir()) == [
            f"caption-topic-{slug}.txt",
            "topic-2024-01-15-01.png",
            "topic-2024-01-15-02.png",
            "topic-2024-01-15-03.png",
            "topic-2024-01-15-04.png",
            "topic-2024-01-15-05.png",
        ]
        for index in range(1, 6):
            with Image.open(
                topic_folder / f"topic-2024-01-15-{index:02d}.png"
            ) as image:
                assert image.size == (1080, 1350)
                assert image.mode == "RGB"
    assert (folder / "topic-haushalt" / "caption-topic-haushalt.txt").read_text(
        encoding="utf-8"
    ) == haushalt.caption

    # The topic visual prompt only sees its own draft and the pair count.
    visual_calls = fake.calls_for("topic_visual_prompts")
    assert len(visual_calls) == 2
    haushalt_draft = _topic_draft(plan.topic_briefs[0])
    radweg_draft = _topic_draft(plan.topic_briefs[1])
    assert haushalt_draft.title in visual_calls[0].prompt
    assert haushalt_draft.sections[0].h2 in visual_calls[0].prompt
    assert radweg_draft.title not in visual_calls[0].prompt
    assert PROTOCOL_TEXT not in visual_calls[0].prompt
    assert "Summary draft" not in visual_calls[0].prompt
    assert plan.summary_briefs[0].point not in visual_calls[0].prompt
    assert "exactly 2 separate prompts" in visual_calls[0].prompt
    assert "Return exactly 3 image prompts" in visual_calls[0].prompt
    assert all(call.aspect_ratio == "4:5" for call in fake.image_calls[1:])

    client = await _asgi_client(postgres_session)
    try:
        list_response = await client.get(
            f"/api/protocols/{protocol.id}/posts"
        )
        detail_response = await client.get(f"/api/posts/{haushalt.id}")
    finally:
        await client.aclose()
        app.dependency_overrides.clear()

    assert list_response.status_code == 200
    listed = list_response.json()
    assert [post["status"] for post in listed] == ["ready", "ready", "ready"]
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["status"] == "ready"
    assert detail["failed_step"] is None
    assert [asset["role"] for asset in detail["assets"]] == [
        "cover",
        "pair_1",
        "pair_2",
    ]
    assert [asset["status"] for asset in detail["assets"]] == [
        "ready",
        "ready",
        "ready",
    ]
    assert [asset["path"] for asset in detail["assets"]] == [
        asset.path for asset in haushalt_assets
    ]
    assert len(detail["alt_text_json"]) == len(detail["slides"]) == 5


async def test_one_topic_visual_failure_leaves_summary_and_other_topic_ready(
    postgres_session, tmp_path
):
    plan = _plan()
    fake = FakeLLMClient()
    fake.script_json("planner", plan)
    fake.script_json("summary_writer", _summary_draft(plan))
    fake.script_json("summary_fact_check", FactCheckResult(issues=[]))
    fake.script_json(
        "caption_writer",
        CaptionDraft(body="Caption Summary"),
        CaptionDraft(body="Caption Haushalt"),
        CaptionDraft(body="Caption Radweg"),
    )
    fake.script_json(
        "summary_visual_prompts",
        VisualPrompts(cover_prompt="Weite, ruhige Szene am Ortsrand."),
    )
    fake.script_image("summary_cover", _png_bytes(size=(540, 960)))
    fake.script_json(
        "topic_writer", *[_topic_draft(brief) for brief in plan.topic_briefs]
    )
    fake.script_json(
        "topic_fact_check",
        *[FactCheckResult(issues=[]) for _ in plan.topic_briefs],
    )
    fake.script_json(
        "topic_visual_prompts",
        LLMSchemaError("topic visual prompts failed"),
        LLMSchemaError("topic visual prompts failed again"),
        TopicVisualPrompts(
            cover_prompt="Cover radweg",
            artwork_prompts=["Pair 1", "Pair 2"],
        ),
    )
    fake.script_image("topic_cover", _png_bytes())
    fake.script_image("topic_pair_art", _png_bytes(), _png_bytes())
    protocol = await _protocol(postgres_session)

    result = await PostPipeline(fake, output_dir=tmp_path).run(
        protocol, postgres_session
    )

    summary, haushalt, radweg = await _posts(postgres_session, protocol)
    assert summary.status == "ready"
    assert haushalt.status == "failed"
    assert haushalt.failed_step == "visual_prompts"
    assert "topic visual prompts failed" in haushalt.error
    assert radweg.status == "ready"
    assert [post.status for post in result.posts] == [
        "ready",
        "failed",
        "ready",
    ]
    assert await _assets(postgres_session, haushalt) == []

    folder = tmp_path / "240115_gemeinderat"
    assert (folder / "caption-summary-summary.txt").exists()
    assert (
        folder / "topic-radweg" / "caption-topic-radweg.txt"
    ).exists()
    assert not (folder / "topic-haushalt").exists()


async def test_rerun_after_all_posts_ready_makes_no_extra_llm_calls(
    postgres_session, tmp_path
):
    plan = _plan()
    fake = FakeLLMClient()
    _script_success(fake, plan)
    protocol = await _protocol(postgres_session)
    pipeline = PostPipeline(fake, output_dir=tmp_path)

    await pipeline.run(protocol, postgres_session)
    call_count = len(fake.calls)
    image_count = len(fake.image_calls)
    folder = tmp_path / "240115_gemeinderat"
    first_mtime = folder.stat().st_mtime_ns

    await pipeline.run(protocol, postgres_session)

    summary, haushalt, radweg = await _posts(postgres_session, protocol)
    assert [post.status for post in (summary, haushalt, radweg)] == [
        "ready",
        "ready",
        "ready",
    ]
    assert len(fake.calls) == call_count
    assert len(fake.image_calls) == image_count
    assert folder.stat().st_mtime_ns == first_mtime


async def test_two_topics_keep_distinct_files_and_rerender_is_scoped(
    postgres_session, tmp_path
):
    plan = _plan()
    fake = FakeLLMClient()
    _script_success(fake, plan)
    protocol = await _protocol(postgres_session)
    pipeline = PostPipeline(fake, output_dir=tmp_path)

    await pipeline.run(protocol, postgres_session)
    summary, haushalt, radweg = await _posts(postgres_session, protocol)
    assert [post.status for post in (summary, haushalt, radweg)] == [
        "ready",
        "ready",
        "ready",
    ]

    protocol_folder = tmp_path / "240115_gemeinderat"
    haushalt_folder = protocol_folder / "topic-haushalt"
    radweg_folder = protocol_folder / "topic-radweg"
    haushalt_cover = (haushalt_folder / "topic-2024-01-15-01.png").read_bytes()
    radweg_cover = (radweg_folder / "topic-2024-01-15-01.png").read_bytes()
    assert haushalt_cover != radweg_cover
    haushalt_files = sorted(path.name for path in haushalt_folder.iterdir())
    radweg_files = sorted(path.name for path in radweg_folder.iterdir())
    assert haushalt_files == [
        "caption-topic-haushalt.txt",
        "topic-2024-01-15-01.png",
        "topic-2024-01-15-02.png",
        "topic-2024-01-15-03.png",
        "topic-2024-01-15-04.png",
        "topic-2024-01-15-05.png",
    ]
    assert radweg_files == [
        "caption-topic-radweg.txt",
        "topic-2024-01-15-01.png",
        "topic-2024-01-15-02.png",
        "topic-2024-01-15-03.png",
        "topic-2024-01-15-04.png",
        "topic-2024-01-15-05.png",
    ]
    radweg_snapshot = {
        path.name: path.read_bytes() for path in radweg_folder.iterdir()
    }

    # Rerender only the haushalt topic from its cached content. The radweg
    # topic stays ready and its files must not be touched.
    haushalt.status = "draft"
    haushalt.failed_step = None
    haushalt.error = None
    await postgres_session.commit()
    fake.script_json(
        "topic_visual_prompts",
        TopicVisualPrompts(
            cover_prompt="Neues Cover haushalt",
            artwork_prompts=["Neu 1", "Neu 2"],
        ),
    )
    fake.script_image("topic_cover", _png_bytes(color=(10, 20, 30)))
    fake.script_image(
        "topic_pair_art",
        _png_bytes(color=(40, 50, 60)),
        _png_bytes(color=(70, 80, 90)),
    )

    await pipeline.run(protocol, postgres_session)

    summary, haushalt, radweg = await _posts(postgres_session, protocol)
    assert [post.status for post in (summary, haushalt, radweg)] == [
        "ready",
        "ready",
        "ready",
    ], (haushalt.failed_step, haushalt.error)
    assert (haushalt_folder / "topic-2024-01-15-01.png").read_bytes() != (
        haushalt_cover
    )
    assert {
        path.name: path.read_bytes() for path in radweg_folder.iterdir()
    } == radweg_snapshot
    assert sorted(path.name for path in haushalt_folder.iterdir()) == (
        haushalt_files
    )


async def test_topic_render_failure_marks_only_that_topic_and_writes_no_topic_files(
    postgres_session, tmp_path, monkeypatch
):
    plan = _plan()
    fake = FakeLLMClient()
    _script_success(fake, plan)
    protocol = await _protocol(postgres_session)

    def fail_topic_render(*args, **kwargs):
        raise RenderError("forced topic render failure")

    monkeypatch.setattr(
        pipeline_module, "render_topic_frames", fail_topic_render
    )

    result = await PostPipeline(fake, output_dir=tmp_path).run(
        protocol, postgres_session
    )

    summary, haushalt, radweg = await _posts(postgres_session, protocol)
    assert summary.status == "ready"
    assert haushalt.status == "failed"
    assert haushalt.failed_step == "render"
    assert "forced topic render failure" in haushalt.error
    assert radweg.status == "failed"
    assert radweg.failed_step == "render"
    assert [post.status for post in result.posts] == [
        "ready",
        "failed",
        "failed",
    ]

    folder = tmp_path / "240115_gemeinderat"
    assert sorted(
        path.name for path in folder.iterdir() if path.name.startswith("topic-")
    ) == []
    assert (folder / "caption-summary-summary.txt").exists()

    haushalt_assets = await _assets(postgres_session, haushalt)
    assert [asset.status for asset in haushalt_assets] == [
        "failed",
        "failed",
        "failed",
    ]
    assert all(asset.path is None for asset in haushalt_assets)
    assert all(
        "forced topic render failure" in asset.error
        for asset in haushalt_assets
    )


async def test_topic_image_authentication_error_stops_the_job(
    postgres_session, tmp_path
):
    plan = _plan()
    fake = FakeLLMClient()
    _script_success(
        fake, plan, topic_image=LLMAuthenticationError("Insufficient credits")
    )
    protocol = await _protocol(postgres_session)

    with pytest.raises(LLMAuthenticationError, match="Insufficient credits"):
        await PostPipeline(fake, output_dir=tmp_path).run(
            protocol, postgres_session
        )

    summary, haushalt, _ = await _posts(postgres_session, protocol)
    assert summary.status == "ready"
    assert haushalt.status == "draft"
    assert haushalt.caption
    assert protocol.processed is False


async def test_topic_image_failures_produce_orange_fallbacks_and_stay_ready(
    postgres_session, tmp_path
):
    plan = _plan()
    plan.topic_briefs = plan.topic_briefs[:1]
    fake = FakeLLMClient()
    fake.script_json("planner", plan)
    fake.script_json("summary_writer", _summary_draft(plan))
    fake.script_json("summary_fact_check", FactCheckResult(issues=[]))
    fake.script_json(
        "caption_writer",
        CaptionDraft(body="Caption Summary"),
        CaptionDraft(body="Caption Haushalt"),
    )
    fake.script_json(
        "summary_visual_prompts",
        VisualPrompts(cover_prompt="Weite, ruhige Szene am Ortsrand."),
    )
    fake.script_image("summary_cover", _png_bytes(size=(540, 960)))
    fake.script_json("topic_writer", _topic_draft(plan.topic_briefs[0]))
    fake.script_json("topic_fact_check", FactCheckResult(issues=[]))
    fake.script_json(
        "topic_visual_prompts",
        TopicVisualPrompts(
            cover_prompt="Cover haushalt",
            artwork_prompts=["Pair 1", "Pair 2"],
        ),
    )
    fake.script_image("topic_cover", LLMTransportError("cover down"))
    fake.script_image(
        "topic_pair_art",
        LLMTransportError("pair down"),
        LLMTransportError("pair down"),
    )
    protocol = await _protocol(postgres_session)

    result = await PostPipeline(fake, output_dir=tmp_path).run(
        protocol, postgres_session
    )

    summary, haushalt = await _posts(postgres_session, protocol)
    assert summary.status == "ready"
    assert haushalt.status == "ready"
    assert [post.status for post in result.posts] == ["ready", "ready"]
    assets = await _assets(postgres_session, haushalt)
    assert [asset.role for asset in assets] == ["cover", "pair_1", "pair_2"]
    assert [asset.status for asset in assets] == [
        "fallback",
        "fallback",
        "fallback",
    ]
    assert "cover down" in assets[0].error
    assert "pair down" in assets[1].error
    assert all(asset.prompt.endswith(IMAGE_STYLE_SUFFIX) for asset in assets)
    assert all(asset.path for asset in assets)

    folder = tmp_path / "240115_gemeinderat" / "topic-haushalt"
    for index in range(1, 6):
        assert (folder / f"topic-2024-01-15-{index:02d}.png").exists()
    with Image.open(folder / "topic-2024-01-15-02.png") as first:
        with Image.open(folder / "topic-2024-01-15-03.png") as second:
            combined = Image.new("RGB", (720, 1350))
            combined.paste(first.crop((720, 0, 1080, 1350)), (0, 0))
            combined.paste(second.crop((0, 0, 360, 1350)), (360, 0))
    assert combined.tobytes() == topic_pair_fallback_art().tobytes()


async def test_odd_content_count_records_a_single_last_asset_and_strip(
    postgres_session, tmp_path
):
    plan = _plan()
    plan.topic_briefs = plan.topic_briefs[:1]
    long_topic = TopicDraft(
        title="Was der Rat zum Haushalt in Rosdorf entschieden hat",
        sections=[
            {
                "h2": f"Der Rat hat zu Abschnitt {index} ausführlich entschieden",
                "paragraphs": [_paragraph(length)],
            }
            for index, length in enumerate((700, 700, 150), start=1)
        ],
    )
    fake = FakeLLMClient()
    fake.script_json("planner", plan)
    fake.script_json("summary_writer", _summary_draft(plan))
    fake.script_json("summary_fact_check", FactCheckResult(issues=[]))
    fake.script_json(
        "caption_writer",
        CaptionDraft(body="Caption Summary"),
        CaptionDraft(body="Caption Haushalt"),
    )
    fake.script_json(
        "summary_visual_prompts",
        VisualPrompts(cover_prompt="Weite, ruhige Szene am Ortsrand."),
    )
    fake.script_image("summary_cover", _png_bytes(size=(540, 960)))
    fake.script_json("topic_writer", long_topic)
    fake.script_json("topic_fact_check", FactCheckResult(issues=[]))
    fake.script_json(
        "topic_visual_prompts",
        TopicVisualPrompts(
            cover_prompt="Cover haushalt",
            artwork_prompts=["Pair 1", "Pair 2"],
            single_prompt="Single",
        ),
    )
    fake.script_image("topic_cover", _png_bytes())
    fake.script_image("topic_pair_art", _png_bytes(), _png_bytes())
    fake.script_image("topic_single_art", _png_bytes(color=(10, 200, 30)))
    protocol = await _protocol(postgres_session)

    result = await PostPipeline(fake, output_dir=tmp_path).run(
        protocol, postgres_session
    )

    summary, haushalt = await _posts(postgres_session, protocol)
    assert result.posts[-1].slug == "haushalt"
    assert haushalt.status == "ready"
    assets = await _assets(postgres_session, haushalt)
    assert [asset.role for asset in assets] == [
        "cover",
        "pair_1",
        "pair_2",
        "single_last",
    ]
    assert [asset.status for asset in assets] == [
        "ready",
        "ready",
        "ready",
        "ready",
    ]
    assert all(asset.prompt.endswith(IMAGE_STYLE_SUFFIX) for asset in assets)
    assert assets[-1].prompt.startswith("Single")
    assert assets[-1].path.endswith(
        "topic-haushalt/topic-2024-01-15-06.png"
    )

    visual_call = fake.calls_for("topic_visual_prompts")[0]
    assert "exactly 2 separate prompts" in visual_call.prompt
    assert "Return exactly 4 image prompts" in visual_call.prompt
    assert "1 single_prompt for the unpaired last slide" in visual_call.prompt
    assert "single_prompt" in visual_call.prompt
    folder = tmp_path / "240115_gemeinderat" / "topic-haushalt"
    with Image.open(folder / "topic-2024-01-15-06.png") as last:
        assert last.getpixel((800, 675)) == (10, 200, 30)
        assert last.getpixel((400, 675)) == (30, 30, 33)
