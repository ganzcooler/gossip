"""Tests for post pipeline orchestration and processed-state semantics."""

from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.post_models import EditorialPlan, SummaryBrief, TopicBrief
from app.models import Post, PostAsset, PostStatus, PostType
from app.services.errors import AuthenticationError
from app.services.post_processor import _all_posts_ready, process_protocol_posts


def _protocol():
    protocol = MagicMock()
    protocol.id = 1
    protocol.title = "Test Protocol"
    protocol.session_date = date(2026, 10, 30)
    protocol.pdf_text = "Protocol text"
    protocol.processed = False
    return protocol


def _plan(topic_count: int = 0) -> EditorialPlan:
    return EditorialPlan(
        summary=SummaryBrief(
            working_title="Das war die Sitzung",
            focus="Haushalt und Windpark",
            key_points=["Haushalt", "Windpark"],
        ),
        topics=[
            TopicBrief(
                slug=f"thema-{index}",
                working_title=f"Thema {index}",
                focus="Fokus",
                why_relevant="Relevant",
                protocol_anchors=["Anker"],
            )
            for index in range(1, topic_count + 1)
        ],
    )


def _post(status: PostStatus, assets: list[PostAsset] | None = None) -> Post:
    post = Post(
        id=1,
        protocol_id=1,
        post_type=PostType.SUMMARY,
        slug="summary",
        post_index=0,
        title="Titel",
        kicker="SITZUNG KOMPAKT",
        content_markdown="Text",
        content_json={},
        status=status,
        created_at=datetime.utcnow(),
    )
    post.assets = assets or []
    return post


@pytest.mark.asyncio
async def test_all_posts_ready_true_when_all_posts_and_assets_exist(tmp_path):
    asset_path = tmp_path / "slide.jpg"
    asset_path.write_bytes(b"image")
    post = _post(PostStatus.READY, [PostAsset(role="cover", path=str(asset_path), status="ready")])
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [post]
    session.execute = AsyncMock(return_value=result)

    assert await _all_posts_ready(_protocol(), _plan(), session) is True


@pytest.mark.asyncio
async def test_all_posts_ready_false_when_asset_missing(tmp_path):
    post = _post(
        PostStatus.READY,
        [PostAsset(role="cover", path=str(tmp_path / "missing.jpg"), status="ready")],
    )
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [post]
    session.execute = AsyncMock(return_value=result)

    assert await _all_posts_ready(_protocol(), _plan(), session) is False


@pytest.mark.asyncio
async def test_all_posts_ready_false_when_topic_post_is_missing():
    post = _post(PostStatus.READY, [])
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [post]
    session.execute = AsyncMock(return_value=result)

    assert await _all_posts_ready(_protocol(), _plan(topic_count=1), session) is False


@pytest.mark.asyncio
async def test_summary_runs_before_topics_and_failure_leaves_protocol_unprocessed(tmp_path):
    protocol = _protocol()
    plan = _plan(topic_count=1)
    session = AsyncMock()
    order: list[str] = []

    async def summary(*args, **kwargs):
        order.append("summary")

    async def topic(*args, **kwargs):
        order.append("topic")
        raise RuntimeError("topic failed")

    with patch("app.services.post_processor._protocol_folder", return_value=tmp_path), patch(
        "app.services.post_processor._get_or_create_plan",
        AsyncMock(return_value=plan),
    ), patch(
        "app.services.post_processor._ensure_summary_post", side_effect=summary
    ), patch(
        "app.services.post_processor._ensure_topic_post", side_effect=topic
    ), patch(
        "app.services.post_processor._get_post", AsyncMock(return_value=None)
    ), patch(
        "app.services.post_processor._all_posts_ready", AsyncMock(return_value=False)
    ):
        await process_protocol_posts(protocol, session)

    assert order == ["summary", "topic"]
    assert protocol.processed is False


@pytest.mark.asyncio
async def test_protocol_processed_when_all_posts_ready(tmp_path):
    protocol = _protocol()
    session = AsyncMock()

    with patch("app.services.post_processor._protocol_folder", return_value=tmp_path), patch(
        "app.services.post_processor._get_or_create_plan",
        AsyncMock(return_value=_plan()),
    ), patch(
        "app.services.post_processor._ensure_summary_post", AsyncMock()
    ), patch(
        "app.services.post_processor._all_posts_ready", AsyncMock(return_value=True)
    ):
        await process_protocol_posts(protocol, session)

    assert protocol.processed is True


@pytest.mark.asyncio
async def test_authentication_error_stops_pipeline(tmp_path):
    protocol = _protocol()
    session = AsyncMock()

    with patch("app.services.post_processor._protocol_folder", return_value=tmp_path), patch(
        "app.services.post_processor._get_or_create_plan",
        AsyncMock(side_effect=AuthenticationError("Payment required")),
    ):
        with pytest.raises(AuthenticationError):
            await process_protocol_posts(protocol, session)
