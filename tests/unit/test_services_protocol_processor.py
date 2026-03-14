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
        session_date = date(2024, 1, 15)
        title = "Test Protocol"

        result = save_image_to_file(image_bytes, temp_directory, 1, session_date, title)

        assert result.exists()
        assert result.suffix == ".png"

    def test_filename_contains_index(self, temp_directory):
        """Test that filename contains article index."""
        image_bytes = b"fake image data"
        session_date = date(2024, 1, 15)
        title = "Test Protocol"

        result = save_image_to_file(image_bytes, temp_directory, 7, session_date, title)

        assert "07" in result.name

    def test_filename_with_suffix(self, temp_directory):
        """Test that suffix is added to filename."""
        image_bytes = b"fake image data"
        session_date = date(2024, 1, 15)
        title = "Test Protocol"

        result = save_image_to_file(image_bytes, temp_directory, 1, session_date, title, suffix="_main")

        assert "_main" in result.name

    def test_saves_correct_content(self, temp_directory):
        """Test that correct bytes are saved."""
        image_bytes = b"\x89PNG\r\n\x1a\nfake image content"
        session_date = date(2024, 1, 15)
        title = "Test Protocol"

        result = save_image_to_file(image_bytes, temp_directory, 1, session_date, title)

        saved_content = result.read_bytes()
        assert saved_content == image_bytes

    def test_creates_folder_when_none_provided(self, temp_directory):
        """Test that folder is created when protocol_folder is None."""
        import time
        image_bytes = b"\x89PNG\r\n\x1a\n"
        session_date = date(2024, 1, 15)
        # Use timestamp to avoid folder name collision with previous test runs
        title = f"Test Protocol Lazy {int(time.time() * 1000)}"

        # Pass None - folder should be created lazily in ARTICLES_DIR
        result = save_image_to_file(image_bytes, None, 1, session_date, title)

        assert result.exists()
        assert result.is_file()
        # The folder should be created under ARTICLES_DIR based on session_date and title
        # Folder format is DDMMM_Y title (e.g., 240115_test_protocol_lazy_1234567890)
        assert "240115" in result.parent.name

    def test_reuses_existing_folder(self, temp_directory):
        """Test that existing folder path is reused when it exists."""
        image_bytes = b"\x89PNG\r\n\x1a\n"
        session_date = date(2024, 3, 10)
        title = "Existing Folder Test"
        
        # Create the folder first
        existing_folder = temp_directory / "2024-03-10_Existing_Folder_Test"
        existing_folder.mkdir(parents=True)

        # Pass existing folder - should reuse it
        result = save_image_to_file(image_bytes, existing_folder, 1, session_date, title)

        assert result.exists()
        assert result.parent == existing_folder

    def test_reuses_existing_folder_on_retry(self, temp_directory, monkeypatch):
        """Test that folder is reused when it already exists from a previous run."""
        import time
        from unittest.mock import patch
        from app.core.config import ARTICLES_DIR
        
        image_bytes = b"\x89PNG\r\n\x1a\n"
        session_date = date(2024, 1, 15)
        # Use timestamp to avoid folder name collision with previous test runs
        title = f"Test Protocol Retry {int(time.time() * 1000)}"
        
        # Normalize title the same way create_protocol_folder does
        normalized = title.replace(' ', '_').lower()
        folder_name = f"240115_{normalized}"
        existing_folder = temp_directory / folder_name
        existing_folder.mkdir(parents=True)
        
        # Mock ARTICLES_DIR to use temp_directory
        monkeypatch.setattr('app.services.protocol_processor.ARTICLES_DIR', temp_directory)
        
        # Now call save_image_to_file with None - should reuse existing folder
        # instead of trying to create a new one and getting FileExistsError
        result = save_image_to_file(image_bytes, None, 1, session_date, title)

        assert result.exists()
        assert result.is_file()
        # Should have used the existing folder, not created a new one
        assert result.parent == existing_folder


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
