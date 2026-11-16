"""End-to-end read path from PostgreSQL through the FastAPI routes."""

from datetime import date

import httpx
import pytest

from app.database import get_db
from app.main import app
from app.models import Post, PostAsset, PostSlide, Protocol

pytestmark = pytest.mark.integration


async def _add_post_tree(session):
    protocol = Protocol(
        session_date=date(2024, 1, 15),
        title="Gemeinderat Rosdorf",
        getfile_id=42,
        pdf_text="Protokoll text",
    )
    session.add(protocol)
    await session.flush()

    summary = Post(
        protocol_id=protocol.id,
        post_type="summary",
        slug="summary",
        post_index=0,
        title="Sitzung kompakt",
        status="ready",
    )
    topic = Post(
        protocol_id=protocol.id,
        post_type="topic",
        slug="haushalt",
        post_index=1,
        title="Haushalt",
        status="draft",
        failed_step="writer",
    )
    session.add_all([topic, summary])
    await session.flush()

    # Insert slides out of order; the API must return them by slide_index.
    session.add_all(
        [
            PostSlide(
                post_id=topic.id,
                slide_index=1,
                slide_type="heading",
                label="Haushalt",
                body="Der Rat hat den Haushalt beschlossen.",
                alt_text="Orange Folie über den Haushalt.",
            ),
            PostSlide(
                post_id=topic.id,
                slide_index=0,
                slide_type="cover",
                label="Haushalt",
                headline="Was der Rat beschlossen hat",
                alt_text="Orange Cover-Folie.",
            ),
            PostAsset(
                post_id=topic.id,
                role="cover",
                status="ready",
                path="output/topic-2024-01-15-01.png",
                model="google/gemini-3.1-flash-image",
            ),
        ]
    )
    await session.commit()
    return protocol, summary, topic


@pytest.mark.asyncio
async def test_read_posts_api_serves_persisted_post_tree(postgres_session):
    protocol, summary, topic = await _add_post_tree(postgres_session)

    async def override_get_db():
        yield postgres_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            list_response = await client.get(f"/api/protocols/{protocol.id}/posts")
            detail_response = await client.get(f"/api/posts/{topic.id}")
    finally:
        app.dependency_overrides.clear()

    assert list_response.status_code == 200
    listed = list_response.json()
    assert [post["id"] for post in listed] == [summary.id, topic.id]
    assert [post["post_index"] for post in listed] == [0, 1]
    assert [post["slide_count"] for post in listed] == [0, 2]

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["post_type"] == "topic"
    assert detail["status"] == "draft"
    assert detail["failed_step"] == "writer"
    assert [slide["slide_index"] for slide in detail["slides"]] == [0, 1]
    assert [slide["slide_type"] for slide in detail["slides"]] == ["cover", "heading"]
    assert detail["assets"][0]["role"] == "cover"
    assert detail["assets"][0]["status"] == "ready"
