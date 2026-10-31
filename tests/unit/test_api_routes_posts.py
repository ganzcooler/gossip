"""Tests for the new post API endpoints."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import Post, PostAsset, PostSlide, PostStatus, PostType

client = TestClient(app)


def _post() -> Post:
    post = Post(
        id=1,
        protocol_id=1,
        post_type=PostType.SUMMARY,
        slug="summary",
        post_index=0,
        title="Das war die Sitzung",
        kicker="SITZUNG KOMPAKT",
        content_markdown="# Das war die Sitzung\n\nText.",
        content_json={"title": "Das war die Sitzung"},
        slide_plan_json={"cover": {}, "slides": []},
        caption=None,
        status=PostStatus.READY,
        error=None,
        created_at=datetime(2026, 10, 31, 9, 0, 0),
    )
    post.slides = [
        PostSlide(
            post_id=1,
            slide_index=1,
            pair_index=None,
            label="HAUSHALT",
            headline="Haushalt beschlossen",
            body="Der Rat hat den Haushalt verabschiedet.",
        )
    ]
    post.assets = [
        PostAsset(
            post_id=1,
            role="cover",
            prompt="A calm town hall",
            path="/tmp/summary_cover.jpg",
            status="ready",
        )
    ]
    return post


def test_get_protocol_posts_returns_posts():
    post = _post()
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [post]
    session.execute = AsyncMock(return_value=result)

    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = client.get("/api/protocols/1/posts")
        assert response.status_code == 200
        data = response.json()
        assert data[0]["post_type"] == "summary"
        assert data[0]["status"] == "ready"
        assert data[0]["slides"][0]["headline"] == "Haushalt beschlossen"
        assert data[0]["assets"][0]["role"] == "cover"
    finally:
        app.dependency_overrides.clear()


def test_get_post_returns_one_post():
    post = _post()
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = post
    session.execute = AsyncMock(return_value=result)

    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = client.get("/api/posts/1")
        assert response.status_code == 200
        assert response.json()["slug"] == "summary"
    finally:
        app.dependency_overrides.clear()


def test_get_post_returns_404_when_missing():
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=result)

    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = client.get("/api/posts/999")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
