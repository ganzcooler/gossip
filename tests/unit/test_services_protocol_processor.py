"""
Unit tests for app/services/protocol_processor.py
"""
import pytest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

from app.services.protocol_processor import (
    sanitize_filename,
    save_image_to_file,
    process_protocols_job,
)
from app.services import AuthenticationError


class TestSanitizeFilename:
    """Tests for sanitize_filename function."""

    def test_replaces_spaces_with_underscores(self):
        """Test that spaces are replaced with underscores."""
        result = sanitize_filename("test file name")
        assert " " not in result
        assert "_" in result
        assert result == "test_file_name"

    def test_removes_special_characters(self):
        """Test that special characters are removed."""
        result = sanitize_filename("test@#$%^&*()file")
        assert "@" not in result
        assert "#" not in result
        assert "$" not in result

    def test_keeps_allowed_characters(self):
        """Test that allowed characters are preserved."""
        result = sanitize_filename("test-file_name.txt")
        assert "test-file_name.txt" == result

    def test_removes_multiple_underscores(self):
        """Test that multiple consecutive underscores are reduced."""
        result = sanitize_filename("test___file____name")
        assert "___" not in result
        assert "____" not in result

    def test_strips_leading_trailing_special_chars(self):
        """Test that leading/trailing special chars are stripped."""
        result = sanitize_filename("._-test-file-_.")
        assert not result.startswith(".")
        assert not result.startswith("_")
        assert not result.startswith("-")
        assert not result.endswith(".")
        assert not result.endswith("_")
        assert not result.endswith("-")

    def test_handles_empty_string(self):
        """Test handling of empty string."""
        result = sanitize_filename("")
        assert result == ""

    def test_handles_only_special_chars(self):
        """Test handling of string with only special characters."""
        result = sanitize_filename("@#$%^&*")
        assert result == ""

    def test_preserves_unicode_letters(self):
        """Test that unicode letters are preserved."""
        result = sanitize_filename("München Köln")
        assert "München" in result or "muenchen" in result.lower()


class TestSaveImageToFile:
    """Tests for save_image_to_file function."""

    def test_creates_png_file(self, temp_directory):
        """Test that PNG file is created."""
        image_bytes = b"\x89PNG\r\n\x1a\n"  # PNG magic bytes

        result = save_image_to_file(image_bytes, temp_directory, 1)

        assert result.exists()
        assert result.suffix == ".png"

    def test_filename_contains_index(self, temp_directory):
        """Test that filename contains article index."""
        image_bytes = b"fake image data"

        result = save_image_to_file(image_bytes, temp_directory, 7)

        assert "07" in result.name

    def test_filename_with_suffix(self, temp_directory):
        """Test that suffix is added to filename."""
        image_bytes = b"fake image data"

        result = save_image_to_file(image_bytes, temp_directory, 1, suffix="_main")

        assert "_main" in result.name

    def test_saves_correct_content(self, temp_directory):
        """Test that correct bytes are saved."""
        image_bytes = b"\x89PNG\r\n\x1a\nfake image content"

        result = save_image_to_file(image_bytes, temp_directory, 1)

        saved_content = result.read_bytes()
        assert saved_content == image_bytes


class TestProcessProtocolsJobAuthError:
    """Tests for AuthenticationError handling in process_protocols_job."""

    @pytest.mark.asyncio
    async def test_authentication_error_stops_processing(self):
        """Test that AuthenticationError stops the entire job, not just the current protocol."""
        # Create mock db session
        mock_session = AsyncMock()

        # Create two mock protocols
        protocol1 = MagicMock()
        protocol1.id = 1
        protocol2 = MagicMock()
        protocol2.id = 2

        # Mock the query result to return both protocols
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [protocol1, protocol2]
        mock_session.execute.return_value = mock_result

        # Mock process_protocol to raise AuthenticationError on first call
        with patch('app.services.protocol_processor.process_protocol') as mock_process:
            mock_process.side_effect = AuthenticationError("Invalid API key")

            # The job should raise AuthenticationError
            with pytest.raises(AuthenticationError):
                await process_protocols_job(mock_session)

            # process_protocol should only be called once (for the first protocol)
            # because AuthenticationError stops the entire job
            assert mock_process.call_count == 1
            mock_process.assert_called_once_with(protocol1, mock_session)

    @pytest.mark.asyncio
    async def test_other_errors_continue_processing(self):
        """Test that non-auth errors allow processing to continue to next protocol."""
        # Create mock db session
        mock_session = AsyncMock()

        # Create two mock protocols
        protocol1 = MagicMock()
        protocol1.id = 1
        protocol2 = MagicMock()
        protocol2.id = 2

        # Mock the query result to return both protocols
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [protocol1, protocol2]
        mock_session.execute.return_value = mock_result

        # Mock process_protocol to raise generic Exception on first call, succeed on second
        with patch('app.services.protocol_processor.process_protocol') as mock_process:
            mock_process.side_effect = [Exception("Some error"), None]

            # The job should complete successfully
            result = await process_protocols_job(mock_session)

            # Both protocols should be processed
            assert mock_process.call_count == 2
            assert result == 1  # Only one protocol was successfully processed

    @pytest.mark.asyncio
    async def test_authentication_error_re_raises(self):
        """Test that AuthenticationError is re-raised to stop the job."""
        # Create mock db session
        mock_session = AsyncMock()

        # Create a mock protocol
        protocol = MagicMock()
        protocol.id = 1

        # Mock the query result
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [protocol]
        mock_session.execute.return_value = mock_result

        # Mock process_protocol to raise AuthenticationError
        with patch('app.services.protocol_processor.process_protocol') as mock_process:
            mock_process.side_effect = AuthenticationError("API key expired")

            # The error should be re-raised
            with pytest.raises(AuthenticationError, match="API key expired"):
                await process_protocols_job(mock_session)
