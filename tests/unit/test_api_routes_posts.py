"""API tests for the post read endpoints."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.services.caption_writer import CAPTION_FIRST_LINE

client = TestClient(app)


def _override_db(mock_session):
    async def override_get_db():
        yield mock_session

    app.dependency_overrides[get_db] = override_get_db


def _post(**overrides):
    values = {
        "id": 1,
        "protocol_id": 7,
        "post_type": "summary",
        "slug": "summary",
        "post_index": 0,
        "title": "Sitzung kompakt",
        "caption": CAPTION_FIRST_LINE,
        "status": "ready",
        "failed_step": None,
        "created_at": datetime(2024, 1, 15, 10, 0, 0),
        "updated_at": datetime(2024, 1, 15, 11, 0, 0),
        "slides": [],
    }
    values.update(overrides)
    return MagicMock(**values)


def test_list_protocol_posts_returns_compact_posts():
    protocol_result = MagicMock()
    protocol_result.scalar_one_or_none.return_value = 7

    summary = _post(slides=[MagicMock(), MagicMock(), MagicMock()])
    topic = _post(
        id=2,
        post_type="topic",
        slug="haushalt",
        post_index=1,
        title="Haushalt",
        status="draft",
        failed_step="writer",
        slides=[MagicMock()],
    )
    posts_result = MagicMock()
    posts_result.scalars.return_value.all.return_value = [summary, topic]

    mock_session = AsyncMock()
    mock_session.execute.side_effect = [protocol_result, posts_result]
    _override_db(mock_session)

    try:
        response = client.get("/api/protocols/7/posts")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": 1,
            "protocol_id": 7,
            "post_type": "summary",
            "slug": "summary",
            "post_index": 0,
            "title": "Sitzung kompakt",
            "status": "ready",
            "failed_step": None,
            "caption": CAPTION_FIRST_LINE,
            "slide_count": 3,
            "created_at": "2024-01-15T10:00:00",
            "updated_at": "2024-01-15T11:00:00",
        },
        {
            "id": 2,
            "protocol_id": 7,
            "post_type": "topic",
            "slug": "haushalt",
            "post_index": 1,
            "title": "Haushalt",
            "status": "draft",
            "failed_step": "writer",
            "caption": CAPTION_FIRST_LINE,
            "slide_count": 1,
            "created_at": "2024-01-15T10:00:00",
            "updated_at": "2024-01-15T11:00:00",
        },
    ]


def test_list_protocol_posts_returns_404_for_unknown_protocol():
    protocol_result = MagicMock()
    protocol_result.scalar_one_or_none.return_value = None

    mock_session = AsyncMock()
    mock_session.execute.return_value = protocol_result
    _override_db(mock_session)

    try:
        response = client.get("/api/protocols/999/posts")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_get_post_returns_slides_and_assets():
    slide_0 = MagicMock(
        id=10,
        slide_index=0,
        slide_type="cover",
        pair_index=None,
        label="Haushalt",
        headline="Was der Rat beschlossen hat",
        body=None,
        alt_text="Blaue Story-Karte mit dem Titel Haushalt.",
    )
    slide_1 = MagicMock(
        id=11,
        slide_index=1,
        slide_type="heading",
        pair_index=0,
        label="Haushalt",
        headline=None,
        body="Der Rat hat den Haushalt beschlossen.",
        alt_text="Orange Folie über den Haushalt.",
    )
    cover_asset = MagicMock(
        id=20,
        role="cover",
        prompt="Abstrakte Illustration",
        path="output/topic-2024-01-15-01.png",
        status="ready",
        error=None,
        model="google/gemini-3.1-flash-image",
    )
    post = _post(
        id=2,
        post_type="topic",
        slug="haushalt",
        post_index=1,
        title="Haushalt",
        content_json={"sections": [{"heading": "Haushalt", "paragraphs": ["Text"]}]},
        content_markdown="## Haushalt\n\nText",
        slide_plan_json={"slides": [{"type": "cover"}]},
        alt_text_json=["Blaue Story-Karte", "Orange Folie"],
        fact_check_json={"passed": True, "issues": []},
        status="failed",
        failed_step="fact_check",
        error="Unsupported claim",
        generator_version="post-pipeline-v1",
        slides=[slide_0, slide_1],
        assets=[cover_asset],
    )

    post_result = MagicMock()
    post_result.scalar_one_or_none.return_value = post

    mock_session = AsyncMock()
    mock_session.execute.return_value = post_result
    _override_db(mock_session)

    try:
        response = client.get("/api/posts/2")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "id": 2,
        "protocol_id": 7,
        "post_type": "topic",
        "slug": "haushalt",
        "post_index": 1,
        "title": "Haushalt",
        "content_json": {"sections": [{"heading": "Haushalt", "paragraphs": ["Text"]}]},
        "content_markdown": "## Haushalt\n\nText",
        "slide_plan_json": {"slides": [{"type": "cover"}]},
        "caption": CAPTION_FIRST_LINE,
        "alt_text_json": ["Blaue Story-Karte", "Orange Folie"],
        "fact_check_json": {"passed": True, "issues": []},
        "status": "failed",
        "failed_step": "fact_check",
        "error": "Unsupported claim",
        "generator_version": "post-pipeline-v1",
        "created_at": "2024-01-15T10:00:00",
        "updated_at": "2024-01-15T11:00:00",
        "slide_count": 2,
        "slides": [
            {
                "id": 10,
                "slide_index": 0,
                "slide_type": "cover",
                "pair_index": None,
                "label": "Haushalt",
                "headline": "Was der Rat beschlossen hat",
                "body": None,
                "alt_text": "Blaue Story-Karte mit dem Titel Haushalt.",
            },
            {
                "id": 11,
                "slide_index": 1,
                "slide_type": "heading",
                "pair_index": 0,
                "label": "Haushalt",
                "headline": None,
                "body": "Der Rat hat den Haushalt beschlossen.",
                "alt_text": "Orange Folie über den Haushalt.",
            },
        ],
        "assets": [
            {
                "id": 20,
                "role": "cover",
                "prompt": "Abstrakte Illustration",
                "path": "output/topic-2024-01-15-01.png",
                "status": "ready",
                "error": None,
                "model": "google/gemini-3.1-flash-image",
            }
        ],
    }


def test_get_post_returns_404_for_unknown_post():
    post_result = MagicMock()
    post_result.scalar_one_or_none.return_value = None

    mock_session = AsyncMock()
    mock_session.execute.return_value = post_result
    _override_db(mock_session)

    try:
        response = client.get("/api/posts/999")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def _count_result(value):
    result = MagicMock()
    result.scalar.return_value = value
    return result


def _post_counts_result(rows):
    result = MagicMock()
    result.all.return_value = rows
    return result


def test_stats_include_post_counts_without_losing_existing_keys():
    mock_session = AsyncMock()
    mock_session.execute.side_effect = [
        _count_result(12),
        _count_result(9),
        _count_result(30),
        _post_counts_result([("draft", 2), ("ready", 3), ("failed", 1)]),
    ]
    _override_db(mock_session)

    try:
        response = client.get("/api/stats")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["total_protocols"] == 12
    assert data["processed_protocols"] == 9
    assert data["unprocessed_protocols"] == 3
    assert data["total_articles"] == 30
    assert data["post_counts"] == {"draft": 2, "ready": 3, "failed": 1}


def test_pipeline_status_includes_post_counts_without_losing_existing_keys():
    mock_session = AsyncMock()
    mock_session.execute.side_effect = [
        _count_result(12),
        _count_result(4),
        _count_result(30),
        _post_counts_result([("draft", 2), ("ready", 3), ("failed", 1)]),
    ]
    _override_db(mock_session)

    try:
        response = client.get("/api/pipeline/status")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["total_protocols"] == 12
    assert data["unprocessed_protocols"] == 4
    assert data["total_articles"] == 30
    assert data["ready_to_process"] is True
    assert data["post_counts"] == {"draft": 2, "ready": 3, "failed": 1}
