"""Opt-in end-to-end smoke test against real OpenRouter and PostgreSQL.

The test is marked ``manual`` and is therefore excluded from
``pytest -m "not manual"``. It needs a disposable PostgreSQL database and a
funded OpenRouter key, and it performs paid text and image requests::

    TEST_DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/gossip_test \\
    OPENROUTER_API_KEY=... \\
        pytest -m manual tests/manual/test_e2e_smoke.py

The complete pipeline runs through the real FastAPI app with overridden
``get_db`` and ``get_post_pipeline`` dependencies. The app lifespan is never
entered, so the scheduler does not start. The fixture protocol is sanitized and
contains no real personal data.

Each run writes its PNGs and captions to its own retained folder under
``tests/manual/output/<YYYYMMDD-HHMMSS>-<run-id>/``. Successful and failed runs
keep their output; only the throwaway PostgreSQL schema and fixture rows are
cleaned up. Set ``SMOKE_OUTPUT_DIR`` to use another base output root: the
timestamped run folder is still created underneath it, so runs never overwrite
each other. The default ``tests/manual/output/`` folder is gitignored.
"""

from __future__ import annotations

import asyncio
import os
import re
import uuid
from datetime import date, datetime
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.manual,
    pytest.mark.skipif(
        not os.getenv("OPENROUTER_API_KEY") or not os.getenv("TEST_DATABASE_URL"),
        reason=(
            "the paid manual smoke test needs OPENROUTER_API_KEY and "
            "TEST_DATABASE_URL"
        ),
    ),
]

FIXTURE_SESSION_DATE = date(2024, 5, 14)
FIXTURE_DATE_TEXT = "14.05.2024"
FIXTURE_TITLE = "Gemeinderat"
FIXTURE_GETFILE_ID = 900_001
CAPTION_FIRST_LINE = "Illustration: KI-generiert."
MANUAL_LINK_HINT = (
    "Hinweis: Der SessionNet-Link fehlt und muss manuell ergänzt werden."
)

FIXTURE_PROTOCOL_TEXT = """Gemeinderat Rosdorf
Sitzung am 14. Mai 2024, 18:00 Uhr, Rathaus Rosdorf

Anwesend: 24 Mitglieder des Gemeinderats, die Verwaltung und die Schriftführung.
Entschuldigt: drei Mitglieder. Die Sitzung ist öffentlich.

TOP 1 Haushalt 2024: Investitionen, Gebühren und Feuerwehr
Der Rat beschließt den Haushalt 2024 mit einem Volumen von 18,4 Millionen Euro. Für die Feuerwehr sind 420.000 Euro für ein neues Hilfeleistungsfahrzeug eingeplant, das im zweiten Halbjahr 2025 geliefert werden soll. In die Sanierung der Grundschule fließen 1,2 Millionen Euro, verteilt auf die Jahre 2024 und 2025. Die Straßenausbaubeiträge bleiben unverändert. Die Abwassergebühr steigt zum 1. Juli 2024 um sechs Prozent, weil die Kläranlage erneuert werden muss. Für die Dorfentwicklung stehen 150.000 Euro bereit. Die Verwaltung soll bis September 2024 eine Liste mit allen geplanten Maßnahmen vorlegen und die Reihenfolge nach Dringlichkeit sortieren. Der Rat stimmt dem Haushalt mit 21 Ja-Stimmen, zwei Nein-Stimmen und einer Enthaltung zu.

TOP 2 Radweg an der Hauptstraße: Lückenschluss und Sicherheit
Der Radweg an der Hauptstraße wird zwischen dem Ortsausgang und der Einmündung Am Kirchberg auf einer Länge von 850 Metern geschlossen. Die Arbeiten beginnen im Juli 2024 und sollen bis Oktober 2024 abgeschlossen sein. Die Gemeinde rechnet mit Kosten von 310.000 Euro, von denen das Land 70 Prozent übernimmt. Während der Bauzeit wird der Verkehr einspurig an der Baustelle vorbeigeführt. Für den Schulbus werden zwei Ersatzhaltestellen eingerichtet. Die Verwaltung prüft außerdem, ob an der Einmündung ein Fußgängerüberweg mit Beleuchtung ergänzt werden kann. Eine Anwohnerin weist darauf hin, dass auf dem Schulweg morgens viele Kinder mit dem Fahrrad unterwegs sind. Der Rat beschließt die Maßnahme einstimmig und bittet die Verwaltung, die Anwohner rechtzeitig über die Bauzeiten zu informieren.

TOP 3 Kindertagesstätte Am Kirchberg: Erweiterung und Betreuungszeiten
Die Kindertagesstätte Am Kirchberg wird um eine Gruppe für 18 Kinder erweitert. Der Anbau kostet 780.000 Euro; das Land fördert das Projekt mit 240.000 Euro. Der Rat beschließt außerdem, die Betreuungszeiten ab dem 1. August 2024 auf 7:00 bis 17:00 Uhr auszuweiten. Dafür werden zwei zusätzliche Stellen geschaffen. Die Elternvertretung hatte in der Einwohnerfragestunde auf lange Wartelisten hingewiesen. Die Verwaltung soll prüfen, ob im Obergeschoss ein Ruheraum für die Mittagsbetreuung eingerichtet werden kann. Die Arbeiten sollen im Frühjahr 2025 beginnen und bis zum Jahresende abgeschlossen sein. Während der Bauzeit bleibt die Kita geöffnet; die Gruppen werden vorübergehend im Gemeindehaus betreut. Der Rat stimmt der Erweiterung mit großer Mehrheit zu.
"""

SUMMARY_IMAGE_PATTERN = re.compile(
    rf"^summary-{FIXTURE_SESSION_DATE.isoformat()}-story-(\d{{2}})\.png$"
)
TOPIC_IMAGE_PATTERN = re.compile(
    rf"^topic-{FIXTURE_SESSION_DATE.isoformat()}-(\d{{2}})\.png$"
)
SLUG_PATTERN = re.compile(r"^[a-z0-9-]+$")

MANUAL_OUTPUT_ROOT = Path(__file__).resolve().parent / "output"


def _smoke_run_dir() -> Path:
    """Create and return this run's retained, timestamped output folder.

    ``SMOKE_OUTPUT_DIR`` is a base output root: the timestamped run folder is
    always created underneath it.
    """
    root = Path(os.getenv("SMOKE_OUTPUT_DIR") or MANUAL_OUTPUT_ROOT).expanduser()
    run_id = f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}"
    run_dir = root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _normalise_url(url: str) -> str:
    return str(url).strip().rstrip("/")


def _assert_disposable_postgres(test_url: str) -> None:
    """Refuse non-PostgreSQL and the application database before any write."""
    if not test_url.startswith("postgresql+asyncpg://"):
        pytest.fail(
            "TEST_DATABASE_URL must be a PostgreSQL asyncpg URL "
            "(postgresql+asyncpg://...); refusing to run against another backend"
        )

    from app.core.config import DATABASE_URL

    if _normalise_url(test_url) == _normalise_url(DATABASE_URL):
        pytest.fail(
            "TEST_DATABASE_URL points at the application database; use a "
            "disposable PostgreSQL database instead"
        )


async def _create_schema_and_protocol(test_url: str, schema: str) -> int:
    """Create a throwaway schema, its tables and the fixture protocol."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    import app.models  # noqa: F401
    from app.database import Base
    from app.models import Protocol

    admin_engine = create_async_engine(test_url, isolation_level="AUTOCOMMIT")
    try:
        async with admin_engine.connect() as connection:
            await connection.execute(
                text(f"CREATE SCHEMA {_quote_identifier(schema)}")
            )
    finally:
        await admin_engine.dispose()

    engine = create_async_engine(
        test_url,
        connect_args={"server_settings": {"search_path": schema}},
    )
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            protocol = Protocol(
                session_date=FIXTURE_SESSION_DATE,
                title=FIXTURE_TITLE,
                getfile_id=FIXTURE_GETFILE_ID,
                pdf_text=FIXTURE_PROTOCOL_TEXT,
                processed=False,
            )
            session.add(protocol)
            await session.commit()
            return protocol.id
    finally:
        await engine.dispose()


def _session_override(test_url: str, schema: str):
    """Yield a real DB session per request, created in that request's loop."""

    async def _get_db():
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        engine = create_async_engine(
            test_url,
            connect_args={"server_settings": {"search_path": schema}},
        )
        try:
            session_factory = async_sessionmaker(engine, expire_on_commit=False)
            async with session_factory() as session:
                yield session
        finally:
            await engine.dispose()

    return _get_db


async def _read_database_state(test_url: str, schema: str, protocol_id: int):
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(
        test_url,
        connect_args={"server_settings": {"search_path": schema}},
    )
    try:
        async with engine.connect() as connection:
            processed = (
                await connection.execute(
                    text("SELECT processed FROM protocols WHERE id = :id"),
                    {"id": protocol_id},
                )
            ).scalar_one()
            plan_status = (
                await connection.execute(
                    text(
                        "SELECT status FROM editorial_plans "
                        "WHERE protocol_id = :id"
                    ),
                    {"id": protocol_id},
                )
            ).scalar_one_or_none()
            post_rows = (
                await connection.execute(
                    text(
                        "SELECT post_type, slug, status, failed_step "
                        "FROM posts WHERE protocol_id = :id "
                        "ORDER BY post_index, id"
                    ),
                    {"id": protocol_id},
                )
            ).all()
            slide_count = (
                await connection.execute(
                    text(
                        "SELECT count(*) FROM post_slides s "
                        "JOIN posts p ON p.id = s.post_id "
                        "WHERE p.protocol_id = :id"
                    ),
                    {"id": protocol_id},
                )
            ).scalar_one()
            asset_count = (
                await connection.execute(
                    text(
                        "SELECT count(*) FROM post_assets a "
                        "JOIN posts p ON p.id = a.post_id "
                        "WHERE p.protocol_id = :id"
                    ),
                    {"id": protocol_id},
                )
            ).scalar_one()
    finally:
        await engine.dispose()

    return {
        "processed": processed,
        "plan_status": plan_status,
        "posts": [
            {
                "post_type": row.post_type,
                "slug": row.slug,
                "status": row.status,
                "failed_step": row.failed_step,
            }
            for row in post_rows
        ],
        "slide_count": slide_count,
        "asset_count": asset_count,
    }


async def _cleanup_database(
    test_url: str, schema: str, protocol_id: int | None
) -> None:
    """Delete the fixture rows, then drop the whole throwaway schema."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    if protocol_id is not None:
        engine = create_async_engine(
            test_url,
            connect_args={"server_settings": {"search_path": schema}},
        )
        try:
            async with engine.begin() as connection:
                table = (
                    await connection.execute(
                        text("SELECT to_regclass('protocols')")
                    )
                ).scalar_one_or_none()
                if table is not None:
                    await connection.execute(
                        text("DELETE FROM protocols WHERE id = :id"),
                        {"id": protocol_id},
                    )
        finally:
            await engine.dispose()

    admin_engine = create_async_engine(test_url, isolation_level="AUTOCOMMIT")
    try:
        async with admin_engine.connect() as connection:
            await connection.execute(
                text(
                    "DROP SCHEMA IF EXISTS "
                    f"{_quote_identifier(schema)} CASCADE"
                )
            )
    finally:
        await admin_engine.dispose()


def _response_failure(response) -> str:
    return f"HTTP {response.status_code}: {response.text[:2000]}"


def _assert_png(path: Path, expected_size: tuple[int, int]) -> None:
    from PIL import Image

    assert path.suffix == ".png", f"expected a PNG, got {path}"
    with Image.open(path) as image:
        assert image.format == "PNG", f"{path} is not a PNG"
        assert image.size == expected_size, (
            f"{path} has size {image.size}, expected {expected_size}"
        )
        assert image.mode == "RGB", f"{path} has mode {image.mode}, expected RGB"


def _assert_caption(text: str, *, expected_link: str) -> None:
    assert text.startswith(CAPTION_FIRST_LINE), (
        f"caption must start with {CAPTION_FIRST_LINE!r}: {text!r}"
    )
    assert f"Gemeinderat Rosdorf · Sitzung vom {FIXTURE_DATE_TEXT}" in text
    assert f"Quelle: Ratsprotokoll vom {FIXTURE_DATE_TEXT}" in text
    assert expected_link in text or MANUAL_LINK_HINT in text, (
        "caption must contain the SessionNet link or the manual-fix hint: "
        f"{text!r}"
    )


def _assert_post_detail(detail: dict, *, output_folder: Path) -> None:
    assert detail["status"] == "ready", (
        f"post {detail['id']} is {detail['status']} at "
        f"{detail['failed_step']!r}: {detail['error']}"
    )
    assert detail["failed_step"] is None
    assert detail["error"] is None
    assert detail["slides"], f"post {detail['id']} has no slides"
    assert detail["assets"], f"post {detail['id']} has no assets"
    assert detail["alt_text_json"], f"post {detail['id']} has no alt_text_json"
    assert len(detail["alt_text_json"]) == len(detail["slides"])

    for slide in detail["slides"]:
        assert isinstance(slide["alt_text"], str) and slide["alt_text"].strip(), (
            f"slide {slide['slide_index']} of post {detail['id']} has no alt text"
        )
    for alt_text in detail["alt_text_json"]:
        assert isinstance(alt_text, str) and alt_text.strip(), (
            f"post {detail['id']} has an empty alt_text_json entry"
        )

    assert detail["caption"], f"post {detail['id']} has no caption"
    _assert_caption(
        detail["caption"],
        expected_link=f"getfile.asp?id={FIXTURE_GETFILE_ID}",
    )

    for asset in detail["assets"]:
        assert asset["status"] in {"ready", "fallback"}, (
            f"asset {asset['role']} of post {detail['id']} is "
            f"{asset['status']}: {asset['error']}"
        )
        assert asset["path"], f"asset {asset['role']} has no output path"
        asset_path = Path(asset["path"])
        assert asset_path.is_file(), f"asset output is missing: {asset_path}"
        assert asset_path.resolve().is_relative_to(
            output_folder.resolve()
        ), f"asset {asset_path} was not written to the run output folder"


def _assert_summary_output(folder: Path, post_id: int) -> None:
    top_files = sorted(path for path in folder.iterdir() if path.is_file())

    summary_images = [
        path for path in top_files if SUMMARY_IMAGE_PATTERN.match(path.name)
    ]
    assert 3 <= len(summary_images) <= 7, (
        f"summary post {post_id} wrote {len(summary_images)} images "
        f"instead of 3-7: {[path.name for path in summary_images]}"
    )
    expected_names = [
        f"summary-{FIXTURE_SESSION_DATE.isoformat()}-story-{index:02d}.png"
        for index in range(1, len(summary_images) + 1)
    ]
    assert [path.name for path in summary_images] == expected_names

    caption_files = [
        path for path in top_files if path.name == "caption-summary-summary.txt"
    ]
    assert len(caption_files) == 1, (
        "the summary must have exactly one caption-summary-summary.txt"
    )

    for path in summary_images:
        _assert_png(path, (1080, 1920))


def _assert_topic_output(
    protocol_folder: Path, slug: str, post_id: int
) -> Path:
    assert SLUG_PATTERN.fullmatch(slug), f"invalid topic slug {slug!r}"
    topic_folder = protocol_folder / f"topic-{slug}"
    assert topic_folder.is_dir(), f"missing topic output folder {topic_folder}"

    entries = list(topic_folder.iterdir())
    assert all(entry.is_file() for entry in entries), (
        f"topic folder {topic_folder} must not contain subfolders"
    )
    files = sorted(entries)

    topic_images = [
        path for path in files if TOPIC_IMAGE_PATTERN.match(path.name)
    ]
    assert 5 <= len(topic_images) <= 8, (
        f"topic post {post_id} wrote {len(topic_images)} images "
        f"instead of 5-8: {[path.name for path in topic_images]}"
    )
    expected_names = [
        f"topic-{FIXTURE_SESSION_DATE.isoformat()}-{index:02d}.png"
        for index in range(1, len(topic_images) + 1)
    ]
    assert [path.name for path in topic_images] == expected_names

    caption_files = [
        path for path in files if path.name == f"caption-topic-{slug}.txt"
    ]
    assert len(caption_files) == 1, (
        f"topic {slug} must have exactly one caption-topic-{slug}.txt"
    )

    allowed = set(topic_images) | set(caption_files)
    unexpected = [path for path in files if path not in allowed]
    assert not unexpected, (
        "topic output folder must contain only PNGs and its caption; "
        f"unexpected: {[path.name for path in unexpected]}"
    )

    for path in topic_images:
        _assert_png(path, (1080, 1350))

    return topic_folder


def test_real_openrouter_pipeline_end_to_end():
    """Run one sanitized protocol through the real API, OpenRouter and Postgres."""
    test_url = os.getenv("TEST_DATABASE_URL")
    if not test_url or not os.getenv("OPENROUTER_API_KEY"):
        pytest.skip("OPENROUTER_API_KEY and TEST_DATABASE_URL are required")

    _assert_disposable_postgres(test_url)

    # Imported inside the test so --collect-only never imports the app stack.
    from fastapi.testclient import TestClient

    from app.api.routes import get_post_pipeline
    from app.database import get_db
    from app.main import app
    from app.services.llm_client import OpenRouterLLMClient
    from app.services.post_pipeline import PostPipeline
    from app.utils.folder_utils import protocol_folder_path

    schema = f"e2e_smoke_{uuid.uuid4().hex}"
    run_dir = _smoke_run_dir()
    print(f"Smoke output: {run_dir}")
    protocol_folder = protocol_folder_path(
        run_dir, FIXTURE_SESSION_DATE, FIXTURE_TITLE
    )
    protocol_id: int | None = None
    client = None

    try:
        protocol_id = asyncio.run(_create_schema_and_protocol(test_url, schema))

        # A deliberate dependency override: no app lifespan, no scheduler.
        app.dependency_overrides[get_db] = _session_override(test_url, schema)
        app.dependency_overrides[get_post_pipeline] = lambda: PostPipeline(
            OpenRouterLLMClient(), output_dir=run_dir
        )
        client = TestClient(app)

        response = client.post(
            f"/api/protocols/{protocol_id}/reprocess"
        )
        assert response.status_code == 200, _response_failure(response)
        result = response.json()
        assert result["protocol_id"] == protocol_id
        assert result["plan_status"] == "ready", result
        assert result["processed"] is True, result
        assert result["post_counts"]["failed"] == 0, result
        assert result["post_counts"]["draft"] == 0, result

        posts_response = client.get(
            f"/api/protocols/{protocol_id}/posts"
        )
        assert posts_response.status_code == 200, _response_failure(
            posts_response
        )
        posts = posts_response.json()

        summary_posts = [
            post for post in posts if post["post_type"] == "summary"
        ]
        topic_posts = [
            post for post in posts if post["post_type"] == "topic"
        ]
        assert len(summary_posts) == 1, (
            f"expected exactly one summary post, got {len(summary_posts)}"
        )
        assert len(topic_posts) <= 5, (
            f"expected at most five topic posts, got {len(topic_posts)}"
        )
        if not topic_posts:
            pytest.fail(
                "The real planner selected no topic post for the smoke "
                "fixture. The run cannot prove the topic path; adjust the "
                "fixture or rerun the paid test."
            )

        for post in posts:
            assert post["status"] == "ready", (
                f"{post['post_type']} {post['slug']} is {post['status']} at "
                f"{post['failed_step']}"
            )

        protocol_response = client.get(
            f"/api/protocols/{protocol_id}"
        )
        assert protocol_response.status_code == 200, _response_failure(
            protocol_response
        )
        assert protocol_response.json()["processed"] is True

        detail_by_id = {}
        for post in posts:
            detail_response = client.get(
                f"/api/posts/{post['id']}"
            )
            assert detail_response.status_code == 200, _response_failure(
                detail_response
            )
            detail = detail_response.json()
            detail_by_id[post["id"]] = detail
            _assert_post_detail(detail, output_folder=protocol_folder)

        # The output folder must contain only Summary files and topic folders.
        assert protocol_folder.is_dir(), f"missing output folder {protocol_folder}"
        top_files = sorted(
            path for path in protocol_folder.iterdir() if path.is_file()
        )
        top_dirs = sorted(
            path for path in protocol_folder.iterdir() if path.is_dir()
        )
        expected_top_dirs = {
            protocol_folder / f"topic-{post['slug']}" for post in topic_posts
        }
        assert set(top_dirs) == expected_top_dirs, (
            "the output folder must contain only topic subfolders; got "
            f"{[path.name for path in top_dirs]}"
        )

        summary_post = summary_posts[0]
        _assert_summary_output(protocol_folder, summary_post["id"])
        summary_caption_path = (
            protocol_folder / "caption-summary-summary.txt"
        )
        summary_detail = detail_by_id[summary_post["id"]]
        assert summary_detail["post_type"] == "summary"
        assert summary_detail["slug"] == "summary"
        assert summary_caption_path.read_text(encoding="utf-8") == (
            summary_detail["caption"]
        )

        summary_images = [
            path for path in top_files if SUMMARY_IMAGE_PATTERN.match(path.name)
        ]
        summary_captions = [
            path
            for path in top_files
            if path.name == "caption-summary-summary.txt"
        ]
        allowed_top = set(summary_images) | set(summary_captions)
        unexpected_top = [path for path in top_files if path not in allowed_top]
        assert not unexpected_top, (
            "the protocol output folder must contain only Summary PNGs, the "
            "Summary caption and topic subfolders; unexpected: "
            f"{[path.name for path in unexpected_top]}"
        )

        for topic_post in topic_posts:
            topic_detail = detail_by_id[topic_post["id"]]
            assert topic_detail["post_type"] == "topic"
            assert topic_detail["slug"] == topic_post["slug"]
            topic_folder = _assert_topic_output(
                protocol_folder, topic_post["slug"], topic_post["id"]
            )
            topic_caption_path = (
                topic_folder / f"caption-topic-{topic_post['slug']}.txt"
            )
            assert topic_caption_path.read_text(encoding="utf-8") == (
                topic_detail["caption"]
            )

        state = asyncio.run(
            _read_database_state(test_url, schema, protocol_id)
        )
        assert state["processed"] is True
        assert state["plan_status"] == "ready", state
        assert sum(
            post["post_type"] == "summary" for post in state["posts"]
        ) == 1
        topic_states = [
            post for post in state["posts"] if post["post_type"] == "topic"
        ]
        assert 1 <= len(topic_states) <= 5
        assert all(post["status"] == "ready" for post in state["posts"]), state
        assert all(
            post["failed_step"] is None for post in state["posts"]
        ), state
        assert [
            (post["post_type"], post["slug"], post["status"])
            for post in state["posts"]
        ] == [
            (post["post_type"], post["slug"], post["status"])
            for post in posts
        ]
        assert state["slide_count"] == sum(
            len(detail["slides"]) for detail in detail_by_id.values()
        )
        assert state["asset_count"] == sum(
            len(detail["assets"]) for detail in detail_by_id.values()
        )
    finally:
        app.dependency_overrides.clear()
        if client is not None:
            client.close()
        asyncio.run(_cleanup_database(test_url, schema, protocol_id))
