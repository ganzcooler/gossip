"""API tests for the retry and reprocess endpoints."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from app.api.routes import get_post_pipeline
from app.database import get_db
from app.main import app
from app.services.caption_writer import CAPTION_FIRST_LINE
from app.services.post_pipeline import PostPipelineResult, PostRunResult

client = TestClient(app)


def _override_db(mock_session):
    async def override_get_db():
        yield mock_session

    app.dependency_overrides[get_db] = override_get_db


def _override_pipeline(pipeline):
    app.dependency_overrides[get_post_pipeline] = lambda: pipeline


def _post(**overrides):
    values = {
        "id": 2,
        "protocol_id": 7,
        "post_type": "topic",
        "slug": "haushalt",
        "post_index": 1,
        "title": "Haushalt",
        "content_json": {"draft": {"title": "Haushalt"}},
        "content_markdown": "# Haushalt",
        "slide_plan_json": {"family": "topic"},
        "caption": CAPTION_FIRST_LINE,
        "alt_text_json": ["Alt"],
        "fact_check_json": {"passed": True, "issues": [], "repaired": False},
        "status": "failed",
        "failed_step": "caption",
        "error": "caption broke",
        "generator_version": "post-pipeline-v1",
        "created_at": datetime(2024, 1, 15, 10, 0, 0),
        "updated_at": datetime(2024, 1, 15, 11, 0, 0),
        "slides": [],
        "assets": [],
    }
    values.update(overrides)
    return MagicMock(**values)


def _post_result(post):
    result = MagicMock()
    result.scalar_one_or_none.return_value = post
    return result


def _protocol():
    return MagicMock(
        id=7,
        processed=True,
    )


def test_retry_returns_404_for_unknown_post():
    mock_session = AsyncMock()
    mock_session.execute.return_value = _post_result(None)
    pipeline = MagicMock()
    pipeline.retry_post = AsyncMock()
    _override_db(mock_session)
    _override_pipeline(pipeline)

    try:
        response = client.post("/api/posts/999/retry")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()
    pipeline.retry_post.assert_not_awaited()


def test_retry_returns_the_full_post_shape_and_forwards_force():
    post = _post()
    mock_session = AsyncMock()
    mock_session.execute.return_value = _post_result(post)
    pipeline = MagicMock()
    pipeline.retry_post = AsyncMock()
    _override_db(mock_session)
    _override_pipeline(pipeline)

    try:
        response = client.post("/api/posts/2/retry?force=true")
        detail_response = client.get("/api/posts/2")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == detail_response.json()
    pipeline.retry_post.assert_awaited_once_with(post, mock_session, force=True)


def test_retry_defaults_to_force_false():
    post = _post()
    mock_session = AsyncMock()
    mock_session.execute.return_value = _post_result(post)
    pipeline = MagicMock()
    pipeline.retry_post = AsyncMock()
    _override_db(mock_session)
    _override_pipeline(pipeline)

    try:
        response = client.post("/api/posts/2/retry")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    pipeline.retry_post.assert_awaited_once_with(post, mock_session, force=False)


def test_reprocess_returns_404_for_unknown_protocol():
    mock_session = AsyncMock()
    mock_session.execute.return_value = _post_result(None)
    pipeline = MagicMock()
    pipeline.reprocess_protocol = AsyncMock()
    _override_db(mock_session)
    _override_pipeline(pipeline)

    try:
        response = client.post("/api/protocols/999/reprocess")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()
    pipeline.reprocess_protocol.assert_not_awaited()


def test_reprocess_returns_plan_status_counts_and_post_statuses():
    protocol = _protocol()
    mock_session = AsyncMock()
    mock_session.execute.return_value = _post_result(protocol)
    pipeline = MagicMock()
    pipeline.reprocess_protocol = AsyncMock(
        return_value=PostPipelineResult(
            protocol_id=7,
            plan_status="ready",
            posts=[
                PostRunResult(
                    post_id=1,
                    post_type="summary",
                    slug="summary",
                    status="ready",
                    failed_step=None,
                    error=None,
                ),
                PostRunResult(
                    post_id=2,
                    post_type="topic",
                    slug="haushalt",
                    status="failed",
                    failed_step="fact_check",
                    error="unsupported claim",
                ),
            ],
        )
    )
    _override_db(mock_session)
    _override_pipeline(pipeline)

    try:
        response = client.post("/api/protocols/7/reprocess")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "protocol_id": 7,
        "processed": True,
        "plan_status": "ready",
        "post_counts": {"draft": 0, "ready": 1, "failed": 1},
        "posts": [
            {
                "post_id": 1,
                "post_type": "summary",
                "slug": "summary",
                "status": "ready",
                "failed_step": None,
                "error": None,
            },
            {
                "post_id": 2,
                "post_type": "topic",
                "slug": "haushalt",
                "status": "failed",
                "failed_step": "fact_check",
                "error": "unsupported claim",
            },
        ],
    }
    pipeline.reprocess_protocol.assert_awaited_once_with(
        protocol, mock_session
    )
