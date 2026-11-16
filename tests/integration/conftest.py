"""PostgreSQL fixtures for integration tests.

Every test gets its own throwaway schema so concurrent test sessions never
share tables. The schema is dropped again afterwards; the public schema is
never touched.
"""

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


async def _create_isolated_schema():
    schema = f"test_{uuid.uuid4().hex}"
    admin_engine = create_async_engine(TEST_DATABASE_URL, isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as connection:
        await connection.execute(text(f"CREATE SCHEMA {_quote_identifier(schema)}"))

    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"server_settings": {"search_path": schema}},
    )
    return admin_engine, engine, schema


async def _drop_isolated_schema(admin_engine, schema: str):
    async with admin_engine.connect() as connection:
        await connection.execute(
            text(f"DROP SCHEMA IF EXISTS {_quote_identifier(schema)} CASCADE")
        )
    await admin_engine.dispose()


@pytest.fixture
async def blank_postgres_engine():
    """A connection to a fresh, empty PostgreSQL schema."""
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is not set")

    admin_engine, engine, schema = await _create_isolated_schema()
    try:
        yield engine, schema
    finally:
        await engine.dispose()
        await _drop_isolated_schema(admin_engine, schema)


@pytest.fixture
async def postgres_engine():
    """A PostgreSQL engine whose schema already contains all application tables."""
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is not set")

    from app.database import Base
    import app.models  # noqa: F401

    admin_engine, engine, schema = await _create_isolated_schema()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()
        await _drop_isolated_schema(admin_engine, schema)


@pytest.fixture
async def postgres_session(postgres_engine):
    """An async session bound to the isolated PostgreSQL schema."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    session_factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()
