"""Retry and reprocess endpoints through the real PostgreSQL read path."""

import httpx
import pytest

from app.api.routes import get_post_pipeline
from app.database import get_db
from app.main import app
from app.services.caption_writer import CAPTION_FIRST_LINE
from app.services.llm_client import LLMSchemaError
from tests.integration.test_post_retry import (
    _plan,
    _plan_with_slugs,
    _posts,
    _run_success,
    _script_full_success,
    _script_summary_retry,
    _simulate_failure,
)
from tests.support.fake_llm import FakeLLMClient

pytestmark = pytest.mark.integration


def _override(session, pipeline):
    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_post_pipeline] = lambda: pipeline


async def test_retry_endpoint_returns_the_same_full_shape_as_get_post(
    postgres_session, tmp_path
):
    plan = _plan()
    protocol, pipeline, posts = await _run_success(
        postgres_session, tmp_path, FakeLLMClient(), plan
    )
    summary, _ = posts
    await _simulate_failure(
        postgres_session, tmp_path, protocol, summary, plan, "caption"
    )
    _script_summary_retry(pipeline.llm_client, plan, "caption")

    _override(postgres_session, pipeline)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            retry_response = await client.post(
                f"/api/posts/{summary.id}/retry"
            )
            detail_response = await client.get(f"/api/posts/{summary.id}")
            missing_response = await client.post("/api/posts/999999/retry")
    finally:
        app.dependency_overrides.clear()

    assert retry_response.status_code == 200
    assert retry_response.json() == detail_response.json()
    data = retry_response.json()
    assert data["status"] == "ready"
    assert data["failed_step"] is None
    assert data["caption"].startswith(CAPTION_FIRST_LINE)
    assert data["slides"]
    assert data["assets"]
    assert missing_response.status_code == 404


async def test_reprocess_endpoint_reports_plan_counts_and_statuses(
    postgres_session, tmp_path
):
    plan = _plan_with_slugs(["haushalt"])
    protocol, pipeline, posts = await _run_success(
        postgres_session, tmp_path, FakeLLMClient(), plan
    )
    assert protocol.processed is True

    new_plan = _plan_with_slugs(["radweg"])
    _script_full_success(pipeline.llm_client, new_plan)

    _override(postgres_session, pipeline)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            response = await client.post(
                f"/api/protocols/{protocol.id}/reprocess"
            )
            missing_response = await client.post(
                "/api/protocols/999999/reprocess"
            )
            stats_response = await client.get("/api/stats")
            status_response = await client.get("/api/pipeline/status")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "protocol_id": protocol.id,
        "processed": True,
        "plan_status": "ready",
        "post_counts": {"draft": 0, "ready": 2, "failed": 0},
        "posts": [
            {
                "post_id": response.json()["posts"][0]["post_id"],
                "post_type": "summary",
                "slug": "summary",
                "status": "ready",
                "failed_step": None,
                "error": None,
            },
            {
                "post_id": response.json()["posts"][1]["post_id"],
                "post_type": "topic",
                "slug": "radweg",
                "status": "ready",
                "failed_step": None,
                "error": None,
            },
        ],
    }
    assert [post.slug for post in await _posts(postgres_session, protocol)] == [
        "summary",
        "radweg",
    ]
    assert missing_response.status_code == 404

    assert stats_response.status_code == 200
    assert stats_response.json()["post_counts"] == {
        "draft": 0,
        "ready": 2,
        "failed": 0,
    }
    assert status_response.status_code == 200
    assert status_response.json()["post_counts"] == {
        "draft": 0,
        "ready": 2,
        "failed": 0,
    }


async def test_reprocess_endpoint_returns_unprocessed_after_planner_failure(
    postgres_session, tmp_path
):
    plan = _plan_with_slugs(["haushalt"])
    protocol, pipeline, _ = await _run_success(
        postgres_session, tmp_path, FakeLLMClient(), plan
    )
    pipeline.llm_client.script_json("planner", LLMSchemaError("planner broke"))

    _override(postgres_session, pipeline)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            response = await client.post(
                f"/api/protocols/{protocol.id}/reprocess"
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["processed"] is False
    assert response.json()["plan_status"] == "failed"
    assert response.json()["post_counts"] == {
        "draft": 0,
        "ready": 0,
        "failed": 0,
    }
    assert protocol.processed is False
    assert await _posts(postgres_session, protocol) == []
