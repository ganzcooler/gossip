"""Schema, constraint and cascade tests against a real PostgreSQL database."""

from datetime import date

import pytest
from sqlalchemy import delete, func, inspect, select
from sqlalchemy.exc import IntegrityError

from app.database import Base
from app.models import (
    Article,
    EditorialPlan,
    Post,
    PostAsset,
    PostSlide,
    Protocol,
)

pytestmark = pytest.mark.integration


async def _create_protocol(session, getfile_id: int = 1) -> Protocol:
    protocol = Protocol(
        session_date=date(2024, 1, 15),
        title="Gemeinderat Rosdorf",
        getfile_id=getfile_id,
        pdf_text="Protokoll text",
    )
    session.add(protocol)
    await session.flush()
    return protocol


async def _create_post(
    session,
    protocol: Protocol,
    *,
    post_type: str = "summary",
    slug: str = "summary",
    post_index: int = 0,
) -> Post:
    post = Post(
        protocol_id=protocol.id,
        post_type=post_type,
        slug=slug,
        post_index=post_index,
    )
    session.add(post)
    await session.flush()
    return post


async def _count(session, model) -> int:
    result = await session.execute(select(func.count()).select_from(model))
    return result.scalar_one()


@pytest.mark.asyncio
async def test_create_tables_creates_post_tables_and_keeps_articles(
    blank_postgres_engine, monkeypatch
):
    """create_all() adds the post tables without touching existing legacy data."""
    engine, schema = blank_postgres_engine

    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(
                sync_connection, tables=[Protocol.__table__, Article.__table__]
            )
        )
        await connection.execute(
            Protocol.__table__.insert().values(
                id=1,
                session_date=date(2024, 1, 15),
                title="Gemeinderat Rosdorf",
                getfile_id=1,
                pdf_text="Protokoll text",
                processed=False,
            )
        )
        await connection.execute(
            Article.__table__.insert().values(
                id=1,
                protocol_id=1,
                article_index=1,
                content="<p>Legacy</p>",
            )
        )

    import app.database as database

    monkeypatch.setattr(database, "engine", engine)
    await database.create_tables()

    async with engine.connect() as connection:
        table_names = set(
            await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).get_table_names(schema=schema)
            )
        )
        article_columns = set(
            await connection.run_sync(
                lambda sync_connection: [
                    column["name"]
                    for column in inspect(sync_connection).get_columns(
                        "articles", schema=schema
                    )
                ]
            )
        )
        article_count = (
            await connection.execute(select(func.count()).select_from(Article))
        ).scalar_one()

    assert {
        "editorial_plans",
        "posts",
        "post_slides",
        "post_assets",
        "protocols",
        "articles",
    }.issubset(table_names)
    assert article_columns == {
        "id",
        "protocol_id",
        "article_index",
        "content",
        "caption",
        "created_at",
    }
    assert article_count == 1


@pytest.mark.asyncio
async def test_one_editorial_plan_per_protocol(postgres_session):
    protocol = await _create_protocol(postgres_session)
    postgres_session.add(EditorialPlan(protocol_id=protocol.id, plan_json={"focus": "Haushalt"}))
    await postgres_session.flush()

    with pytest.raises(IntegrityError):
        async with postgres_session.begin_nested():
            postgres_session.add(EditorialPlan(protocol_id=protocol.id, plan_json={}))
            await postgres_session.flush()


@pytest.mark.asyncio
async def test_post_is_unique_per_protocol_type_and_slug(postgres_session):
    protocol = await _create_protocol(postgres_session)
    await _create_post(postgres_session, protocol, post_type="summary", slug="haushalt")

    with pytest.raises(IntegrityError):
        async with postgres_session.begin_nested():
            postgres_session.add(
                Post(
                    protocol_id=protocol.id,
                    post_type="summary",
                    slug="haushalt",
                    post_index=1,
                )
            )
            await postgres_session.flush()

    # The same slug is allowed for the other post type.
    await _create_post(
        postgres_session, protocol, post_type="topic", slug="haushalt", post_index=1
    )
    assert await _count(postgres_session, Post) == 2


@pytest.mark.asyncio
async def test_slide_is_unique_per_post_and_index(postgres_session):
    protocol = await _create_protocol(postgres_session)
    post = await _create_post(postgres_session, protocol)
    postgres_session.add(PostSlide(post_id=post.id, slide_index=0, slide_type="cover"))
    await postgres_session.flush()

    with pytest.raises(IntegrityError):
        async with postgres_session.begin_nested():
            postgres_session.add(
                PostSlide(post_id=post.id, slide_index=0, slide_type="heading")
            )
            await postgres_session.flush()


@pytest.mark.asyncio
async def test_asset_is_unique_per_post_and_role(postgres_session):
    protocol = await _create_protocol(postgres_session)
    post = await _create_post(postgres_session, protocol)
    postgres_session.add(PostAsset(post_id=post.id, role="cover"))
    await postgres_session.flush()

    with pytest.raises(IntegrityError):
        async with postgres_session.begin_nested():
            postgres_session.add(PostAsset(post_id=post.id, role="cover"))
            await postgres_session.flush()


@pytest.mark.asyncio
@pytest.mark.parametrize(("field", "value"), [("post_type", "reel"), ("status", "published")])
async def test_post_rejects_unknown_enum_values(postgres_session, field, value):
    protocol = await _create_protocol(postgres_session)
    post = await _create_post(postgres_session, protocol)

    with pytest.raises(IntegrityError):
        async with postgres_session.begin_nested():
            setattr(post, field, value)
            await postgres_session.flush()


@pytest.mark.asyncio
async def test_editorial_plan_rejects_unknown_status(postgres_session):
    protocol = await _create_protocol(postgres_session)

    with pytest.raises(IntegrityError):
        async with postgres_session.begin_nested():
            postgres_session.add(EditorialPlan(protocol_id=protocol.id, status="published"))
            await postgres_session.flush()


@pytest.mark.asyncio
async def test_slide_rejects_unknown_slide_type(postgres_session):
    protocol = await _create_protocol(postgres_session)
    post = await _create_post(postgres_session, protocol)

    with pytest.raises(IntegrityError):
        async with postgres_session.begin_nested():
            postgres_session.add(
                PostSlide(post_id=post.id, slide_index=0, slide_type="quote")
            )
            await postgres_session.flush()


@pytest.mark.asyncio
async def test_asset_rejects_unknown_status(postgres_session):
    protocol = await _create_protocol(postgres_session)
    post = await _create_post(postgres_session, protocol)

    with pytest.raises(IntegrityError):
        async with postgres_session.begin_nested():
            postgres_session.add(PostAsset(post_id=post.id, role="cover", status="rendering"))
            await postgres_session.flush()


async def _populate_post_tree(session) -> Protocol:
    protocol = await _create_protocol(session)
    session.add(Article(protocol_id=protocol.id, content="<p>Legacy</p>"))
    session.add(EditorialPlan(protocol_id=protocol.id, plan_json={"summary": []}))
    post = await _create_post(session, protocol)
    session.add(
        PostSlide(post_id=post.id, slide_index=0, slide_type="cover", headline="Titel")
    )
    session.add(
        PostAsset(post_id=post.id, role="cover", status="ready", path="cover.png")
    )
    await session.flush()
    return protocol


@pytest.mark.asyncio
async def test_deleting_a_post_cascades_to_slides_and_assets(postgres_session):
    protocol = await _populate_post_tree(postgres_session)
    post = (
        await postgres_session.execute(select(Post).where(Post.protocol_id == protocol.id))
    ).scalar_one()

    await postgres_session.delete(post)
    await postgres_session.flush()

    assert await _count(postgres_session, PostSlide) == 0
    assert await _count(postgres_session, PostAsset) == 0


@pytest.mark.asyncio
async def test_database_cascade_deletes_post_tree_with_protocol(postgres_session):
    """A bulk delete bypasses the ORM, so only the database cascade can clean up."""
    protocol = await _populate_post_tree(postgres_session)
    await postgres_session.execute(delete(Protocol).where(Protocol.id == protocol.id))
    await postgres_session.flush()

    assert await _count(postgres_session, EditorialPlan) == 0
    assert await _count(postgres_session, Post) == 0
    assert await _count(postgres_session, PostSlide) == 0
    assert await _count(postgres_session, PostAsset) == 0
    assert await _count(postgres_session, Article) == 0
