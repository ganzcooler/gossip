"""Tests for the protocol ``processed`` state in the two-post pipeline."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import AuthenticationError
from app.services.protocol_processor import process_protocol


@pytest.mark.asyncio
async def test_process_protocol_delegates_to_post_pipeline():
    protocol = MagicMock()
    protocol.id = 1
    session = AsyncMock()

    with patch(
        "app.services.protocol_processor.process_protocol_posts",
        new_callable=AsyncMock,
    ) as mock_pipeline:
        await process_protocol(protocol, session)

    mock_pipeline.assert_awaited_once_with(protocol, session)


@pytest.mark.asyncio
async def test_process_protocol_propagates_authentication_error():
    protocol = MagicMock()
    protocol.id = 1
    session = AsyncMock()

    with patch(
        "app.services.protocol_processor.process_protocol_posts",
        new_callable=AsyncMock,
    ) as mock_pipeline:
        mock_pipeline.side_effect = AuthenticationError("Payment required")

        with pytest.raises(AuthenticationError):
            await process_protocol(protocol, session)
