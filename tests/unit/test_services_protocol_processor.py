"""
Unit tests for app/services/protocol_processor.py
"""
import io
import pytest
from datetime import date
from unittest.mock import MagicMock, patch, AsyncMock
from PIL import Image

from app.services.protocol_processor import (
    sanitize_filename,
    save_image_to_file,
    process_protocols_job,
)
from app.services import AuthenticationError


def create_test_png_bytes() -> bytes:
    """Create a minimal valid PNG for testing."""
    img = Image.new('RGB', (10, 10), color='red')
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    return buffer.getvalue()


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

    def test_creates_jpg_file(self, temp_directory):
        """Test that JPG file is created."""
        image_bytes = create_test_png_bytes()
        session_date = date(2024, 1, 15)
        title = "Test Protocol"

        result = save_image_to_file(image_bytes, temp_directory, 1, session_date, title)

        assert result.exists()
        assert result.suffix == ".jpg"

    def test_filename_contains_index(self, temp_directory):
        """Test that filename contains article index."""
        image_bytes = create_test_png_bytes()
        session_date = date(2024, 1, 15)
        title = "Test Protocol"

        result = save_image_to_file(image_bytes, temp_directory, 7, session_date, title)

        assert "07" in result.name

    def test_filename_with_suffix(self, temp_directory):
        """Test that suffix is added to filename."""
        image_bytes = create_test_png_bytes()
        session_date = date(2024, 1, 15)
        title = "Test Protocol"

        result = save_image_to_file(image_bytes, temp_directory, 1, session_date, title, suffix="_main")

        assert "_main" in result.name

    def test_saves_valid_jpg(self, temp_directory):
        """Test that valid JPG is saved."""
        image_bytes = create_test_png_bytes()
        session_date = date(2024, 1, 15)
        title = "Test Protocol"

        result = save_image_to_file(image_bytes, temp_directory, 1, session_date, title)

        # Verify it's a valid JPEG by opening it
        saved_image = Image.open(result)
        assert saved_image.format == 'JPEG'

    def test_creates_folder_when_none_provided(self, temp_directory):
        """Test that folder is created when protocol_folder is None."""
        import time
        image_bytes = create_test_png_bytes()
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
        image_bytes = create_test_png_bytes()
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
        
        image_bytes = create_test_png_bytes()
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


class TestProcessExistingProtocol:
    """Tests for the _process_existing_protocol function."""

    @pytest.mark.asyncio
    async def test_regenerates_images_when_missing(self, tmp_path):
        """Test that images are regenerated when they don't exist."""
        from app.services.protocol_processor import _process_existing_protocol
        from app.models import Article
        from unittest.mock import AsyncMock, MagicMock, patch
        from datetime import date

        # Create mock protocol
        mock_protocol = MagicMock()
        mock_protocol.id = 1
        mock_protocol.title = "Test Protocol"
        mock_protocol.session_date = date(2024, 1, 1)
        mock_protocol.processed = False

        # Create mock existing article
        mock_article = MagicMock(spec=Article)
        mock_article.id = 1
        mock_article.protocol_id = 1
        mock_article.article_index = 1
        mock_article.content = "<h1>Test Article</h1><p>Content</p>"
        mock_article.caption = None

        # Create mock session
        mock_session = AsyncMock()

        # Create protocol folder (no images)
        protocol_folder = tmp_path / "240101_test_protocol"
        protocol_folder.mkdir()

        with patch('app.services.protocol_processor.create_protocol_folder') as mock_create_folder:
            mock_create_folder.return_value = protocol_folder
            
            with patch('app.services.protocol_processor.generate_image_for_article') as mock_gen_img:
                mock_gen_img.return_value = ("prompt", create_test_png_bytes())
                
                with patch('app.services.protocol_processor.save_image_to_file') as mock_save:
                    with patch('app.services.protocol_processor.create_insta_images_for_protocol_async'):
                        # Process existing protocol
                        await _process_existing_protocol(mock_protocol, [mock_article], mock_session)

                        # Image generation should be called since no images exist
                        mock_gen_img.assert_called_once()
                        mock_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_image_regeneration_when_images_exist(self, tmp_path):
        """Test that image regeneration is skipped when images already exist."""
        from app.services.protocol_processor import _process_existing_protocol
        from app.models import Article
        from unittest.mock import AsyncMock, MagicMock, patch
        from datetime import date
        from PIL import Image

        # Create mock protocol
        mock_protocol = MagicMock()
        mock_protocol.id = 1
        mock_protocol.title = "Test Protocol"
        mock_protocol.session_date = date(2024, 1, 1)
        mock_protocol.processed = False

        # Create mock existing article
        mock_article = MagicMock(spec=Article)
        mock_article.id = 1
        mock_article.article_index = 1
        mock_article.content = "<h1>Test Article</h1>"
        mock_article.caption = None

        # Create mock session
        mock_session = AsyncMock()

        # Create protocol folder with existing image
        protocol_folder = tmp_path / "240101_test_protocol"
        protocol_folder.mkdir()
        img = Image.new('RGB', (100, 100))
        img.save(protocol_folder / "image_01.jpg")

        with patch('app.services.protocol_processor.create_protocol_folder') as mock_create_folder:
            mock_create_folder.return_value = protocol_folder
            
            with patch('app.services.protocol_processor.generate_image_for_article') as mock_gen_img:
                with patch('app.services.protocol_processor.create_insta_images_for_protocol_async'):
                    # Process existing protocol
                    await _process_existing_protocol(mock_protocol, [mock_article], mock_session)

                    # Image generation should NOT be called since images exist
                    mock_gen_img.assert_not_called()
