"""Integration tests for the Summary visual output path against PostgreSQL."""

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
    VisualPrompts,
)
from app.models import Post, PostAsset, Protocol
from app.services import render_common
from app.services.llm_client import LLMTransportError
from app.services.post_pipeline import PostPipeline
from tests.support.fake_llm import FakeLLMClient

pytestmark = pytest.mark.integration

PROTOCOL_TEXT = (
    "TOP 1 Haushalt\n"
    "Der Rat beschließt den Haushalt einstimmig.\n"
    "\n"
    "TOP 2 Radweg\n"
    "Der Radweg an der Hauptstraße wird im Sommer gebaut.\n"
)
ANCHOR_1 = "Der Rat beschließt den Haushalt einstimmig."
ANCHOR_2 = "Der Radweg an der Hauptstraße wird im Sommer gebaut."


def _plan() -> EditorialPlan:
    return EditorialPlan(
        summary_focus="Haushalt und Radweg",
        summary_title="Was der Rat in Rosdorf entschieden hat",
        summary_briefs=[
            SummaryBrief(
                point="Der Haushalt wurde beschlossen.",
                relevance="Die Mittel sind für alle Ortsteile wichtig.",
                source_anchors=[ANCHOR_1],
            ),
            SummaryBrief(
                point="Der Radweg wird gebaut.",
                relevance="Das verbessert die Verbindung im Ort.",
                source_anchors=[ANCHOR_2],
            ),
        ],
        topic_briefs=[],
    )


def _draft(plan: EditorialPlan) -> SummaryDraft:
    return SummaryDraft(
        cover_title=plan.summary_title,
        points=[
            {
                "kicker": "Haushalt",
                "heading": brief.point,
                "body": (
                    f"Zum Punkt {index} hat der Rat beraten und entschieden. "
                    "Die Verwaltung setzt die Mittel im Frühjahr um. "
                    "Das betrifft alle Ortsteile gleichermaßen."
                )[:120].ljust(120, "x"),
            }
            for index, brief in enumerate(plan.summary_briefs, start=1)
        ],
    )


def _cover_png_bytes() -> bytes:
    image = Image.new("RGB", (540, 960), (80, 120, 100))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _script_success(
    fake: FakeLLMClient,
    plan: EditorialPlan,
    *,
    image_response: object | None = None,
) -> None:
    fake.script_json("planner", plan)
    fake.script_json("summary_writer", _draft(plan))
    fake.script_json("summary_fact_check", FactCheckResult(issues=[]))
    fake.script_json("caption_writer", CaptionDraft(body="Der Rat hat entschieden."))
    fake.script_json(
        "summary_visual_prompts",
        VisualPrompts(cover_prompt="Weite, ruhige Szene am Ortsrand."),
    )
    fake.script_image(
        "summary_cover",
        _cover_png_bytes() if image_response is None else image_response,
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


async def _summary(session, protocol: Protocol) -> Post:
    result = await session.execute(
        select(Post).where(Post.protocol_id == protocol.id)
    )
    return result.scalar_one()


async def _assets(session, post: Post) -> list[PostAsset]:
    result = await session.execute(
        select(PostAsset)
        .where(PostAsset.post_id == post.id)
        .order_by(PostAsset.id)
    )
    return list(result.scalars().all())


async def test_image_failure_produces_the_brand_fallback_and_still_renders_ready(
    postgres_session, tmp_path
):
    plan = _plan()
    fake = FakeLLMClient()
    _script_success(
        fake, plan, image_response=LLMTransportError("provider unavailable")
    )
    protocol = await _protocol(postgres_session)

    result = await PostPipeline(fake, output_dir=tmp_path).run(
        protocol, postgres_session
    )

    summary = await _summary(postgres_session, protocol)
    assets = await _assets(postgres_session, summary)
    assert summary.status == "ready"
    assert summary.failed_step is None
    assert [post.status for post in result.posts] == ["ready"]
    assert len(assets) == 1
    assert assets[0].role == "cover"
    assert assets[0].status == "fallback"
    assert "provider unavailable" in assets[0].error
    assert assets[0].path is not None

    folder = tmp_path / "240115_gemeinderat"
    names = sorted(path.name for path in folder.iterdir())
    assert names == [
        "caption-summary-summary.txt",
        "summary-2024-01-15-story-01.png",
        "summary-2024-01-15-story-02.png",
        "summary-2024-01-15-story-03.png",
    ]
    with Image.open(folder / "summary-2024-01-15-story-01.png") as cover:
        assert cover.size == (1080, 1920)
        assert cover.mode == "RGB"
        assert cover.getpixel((540, 2)) == (30, 123, 181)
        assert cover.getpixel((10, 10)) == (23, 23, 26)
        assert cover.getpixel((900, 100)) != cover.getpixel((10, 10))
    with Image.open(folder / "summary-2024-01-15-story-02.png") as card:
        assert card.getpixel((70, 1000)) == (30, 123, 181)
    assert protocol.processed is False


async def test_rerun_after_ready_does_not_call_writer_visuals_or_images_again(
    postgres_session, tmp_path
):
    plan = _plan()
    fake = FakeLLMClient()
    _script_success(fake, plan)
    protocol = await _protocol(postgres_session)
    pipeline = PostPipeline(fake, output_dir=tmp_path)

    await pipeline.run(protocol, postgres_session)

    assert len(fake.calls_for("summary_writer")) == 1
    assert len(fake.calls_for("summary_visual_prompts")) == 1
    assert len(fake.image_calls) == 1
    first_mtime = (tmp_path / "240115_gemeinderat").stat().st_mtime_ns

    await pipeline.run(protocol, postgres_session)

    summary = await _summary(postgres_session, protocol)
    assert summary.status == "ready"
    assert len(fake.calls_for("summary_writer")) == 1
    assert len(fake.calls_for("summary_visual_prompts")) == 1
    assert len(fake.image_calls) == 1
    assert (tmp_path / "240115_gemeinderat").stat().st_mtime_ns == first_mtime


async def test_missing_logo_fails_the_render_and_writes_no_partial_files(
    postgres_session, tmp_path, monkeypatch
):
    plan = _plan()
    fake = FakeLLMClient()
    _script_success(fake, plan)
    protocol = await _protocol(postgres_session)
    monkeypatch.setattr(
        render_common, "LOGO_PATH", render_common.RESOURCE_DIR / "missing-logo.png"
    )

    result = await PostPipeline(fake, output_dir=tmp_path).run(
        protocol, postgres_session
    )

    summary = await _summary(postgres_session, protocol)
    assets = await _assets(postgres_session, summary)
    assert summary.status == "failed"
    assert summary.failed_step == "render"
    assert "logo" in summary.error
    assert [post.status for post in result.posts] == ["failed"]
    assert len(assets) == 1
    assert assets[0].status == "ready"
    assert assets[0].path is None
    assert list(tmp_path.iterdir()) == []
    assert protocol.processed is False
