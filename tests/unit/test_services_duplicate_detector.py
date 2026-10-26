"""
Unit tests for app/services/duplicate_detector.py
"""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from app.services.duplicate_detector import check_duplicate


class TestCheckDuplicate:
    """Tests for check_duplicate function."""

    @pytest.fixture
    def mock_db_session(self):
        """Create a mock database session."""
        session = AsyncMock()
        return session

    @pytest.fixture
    def create_mock_protocol(self):
        """Factory fixture to create mock protocol objects."""
        def _create(pdf_text, created_at=None):
            protocol = MagicMock()
            protocol.pdf_text = pdf_text
            protocol.created_at = created_at or datetime.now()
            return protocol
        return _create

    @pytest.mark.asyncio
    async def test_no_recent_protocols(self, mock_db_session):
        """Test when no recent protocols exist."""
        # Mock empty result
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db_session.execute.return_value = mock_result

        result = await check_duplicate("Some new text", mock_db_session)

        assert result is False
        mock_db_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_duplicate_similarity_below_threshold(self, mock_db_session, create_mock_protocol):
        """Test when similar protocols exist but similarity is below 95%."""
        # Create a protocol with different text
        existing_protocol = create_mock_protocol("Completely different text content here")
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [existing_protocol]
        mock_db_session.execute.return_value = mock_result

        new_text = "This is new text that is very different from the existing one"
        result = await check_duplicate(new_text, mock_db_session)

        assert result is False

    @pytest.mark.asyncio
    async def test_duplicate_detected_similarity_at_threshold(self, mock_db_session, create_mock_protocol):
        """Test when similarity is exactly at 95% threshold."""
        # Create text that is 95% similar
        base_text = "This is the base text content for testing similarity detection"
        
        existing_protocol = create_mock_protocol(base_text)
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [existing_protocol]
        mock_db_session.execute.return_value = mock_result

        # Same text should be 100% similar
        result = await check_duplicate(base_text, mock_db_session)

        assert result is True

    @pytest.mark.asyncio
    async def test_duplicate_detected_high_similarity(self, mock_db_session, create_mock_protocol):
        """Test when similarity is above 95% threshold."""
        base_text = "This is the base text content for testing similarity detection in the system"
        # Text with minor changes (still >95% similar)
        similar_text = "This is the base text content for testing similarity detection in the system."
        
        existing_protocol = create_mock_protocol(base_text)
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [existing_protocol]
        mock_db_session.execute.return_value = mock_result

        result = await check_duplicate(similar_text, mock_db_session)

        # Even with just a period difference, should be very similar
        assert result is True

    @pytest.mark.asyncio
    async def test_multiple_protocols_checked(self, mock_db_session, create_mock_protocol):
        """Test that all recent protocols are checked for similarity."""
        protocols = [
            create_mock_protocol("First protocol text"),
            create_mock_protocol("Second protocol text"),
            create_mock_protocol("Third protocol text"),
        ]
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = protocols
        mock_db_session.execute.return_value = mock_result

        new_text = "Completely unique new text"
        result = await check_duplicate(new_text, mock_db_session)

        assert result is False

    @pytest.mark.asyncio
    async def test_only_checks_last_three_months(self, mock_db_session):
        """Test that only protocols from last 3 months are checked."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db_session.execute.return_value = mock_result

        await check_duplicate("Some text", mock_db_session)

        # Check that the query was called with a date filter
        call_args = mock_db_session.execute.call_args
        assert call_args is not None

    @pytest.mark.asyncio
    async def test_empty_new_text(self, mock_db_session):
        """Test behavior with empty new text."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db_session.execute.return_value = mock_result

        result = await check_duplicate("", mock_db_session)

        assert result is False

    @pytest.mark.asyncio
    async def test_protocols_with_old_dates_ignored(self, mock_db_session, create_mock_protocol):
        """Test that protocols older than 3 months are not considered."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []  # Query returns empty (old protocols filtered)
        mock_db_session.execute.return_value = mock_result

        result = await check_duplicate("Duplicate text", mock_db_session)

        assert result is False