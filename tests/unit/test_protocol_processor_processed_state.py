"""Regression tests for the protocol ``processed`` state around image generation."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.models import SingleArticle
from app.services import AuthenticationError
from app.services.protocol_processor import process_protocol


def _query_result(items):
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    return result


def _protocol():
    protocol = MagicMock()
    protocol.id = 1
    protocol.title = "Test Protocol"
    protocol.pdf_text = "Protocol text"
    protocol.processed = False
    return protocol


@pytest.mark.asyncio
async def test_process_protocol_leaves_unprocessed_when_image_fails():
    protocol = _protocol()
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_query_result([]))

    article = SingleArticle(ueberschrift="Test", inhalt="<p>Content</p>")
    loop = MagicMock()
    loop.run_in_executor = AsyncMock(return_value=[article])

    with patch(
        "app.services.protocol_processor.asyncio.get_event_loop", return_value=loop
    ), patch(
        "app.services.protocol_processor.process_single_article",
        new_callable=AsyncMock,
    ) as mock_single:
        mock_single.return_value = (None, False)

        await process_protocol(protocol, session)

    assert protocol.processed is False
    session.commit.assert_awaited()
    mock_single.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_protocol_marks_processed_when_images_succeed(tmp_path):
    protocol = _protocol()
    protocol_folder = tmp_path / "240101_test_protocol"
    protocol_folder.mkdir()

    article = SingleArticle(ueberschrift="Test", inhalt="<p>Content</p>")
    article_record = MagicMock()
    article_record.article_index = 1
    article_record.content = "<h1>Test</h1><p>Content</p>"
    article_record.caption = None

    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[_query_result([]), _query_result([article_record])]
    )

    loop = MagicMock()
    loop.run_in_executor = AsyncMock(return_value=[article])

    with patch(
        "app.services.protocol_processor.asyncio.get_event_loop", return_value=loop
    ), patch(
        "app.services.protocol_processor.process_single_article",
        new_callable=AsyncMock,
    ) as mock_single, patch(
        "app.services.protocol_processor.create_insta_images_for_protocol_async",
        new_callable=AsyncMock,
    ) as mock_insta:
        mock_single.return_value = (protocol_folder, True)

        await process_protocol(protocol, session)

    assert protocol.processed is True
    mock_insta.assert_awaited_once()
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_process_protocol_propagates_authentication_error():
    protocol = _protocol()
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_query_result([]))

    article = SingleArticle(ueberschrift="Test", inhalt="<p>Content</p>")
    loop = MagicMock()
    loop.run_in_executor = AsyncMock(return_value=[article])

    with patch(
        "app.services.protocol_processor.asyncio.get_event_loop", return_value=loop
    ), patch(
        "app.services.protocol_processor.process_single_article",
        new_callable=AsyncMock,
    ) as mock_single:
        mock_single.side_effect = AuthenticationError("Payment required")

        with pytest.raises(AuthenticationError):
            await process_protocol(protocol, session)

    assert protocol.processed is False
