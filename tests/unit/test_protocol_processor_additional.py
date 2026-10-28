"""Additional tests for protocol_processor module to increase coverage."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import date

from app.services.protocol_processor import (
    process_protocols_job,
    process_protocol,
    process_single_article,
    save_image_to_file,
    sanitize_filename,
    _process_existing_protocol
)
from app.services import AuthenticationError


class TestProcessProtocolsJob:
    """Tests for process_protocols_job function."""

    @pytest.mark.asyncio
    async def test_process_protocols_job_no_unprocessed(self, mock_db_session):
        """Test when there are no unprocessed protocols."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        result = await process_protocols_job(mock_db_session)

        assert result == 0

    @pytest.mark.asyncio
    async def test_process_protocols_job_with_unprocessed(self, mock_db_session):
        """Test processing unprocessed protocols."""
        mock_protocol = MagicMock()
        mock_protocol.id = 1
        mock_protocol.title = "Test Protocol"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_protocol]
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        with patch('app.services.protocol_processor.process_protocol', new_callable=AsyncMock) as mock_process:
            result = await process_protocols_job(mock_db_session)

            assert result == 1
            mock_process.assert_called_once_with(mock_protocol, mock_db_session)

    @pytest.mark.asyncio
    async def test_process_protocols_job_authentication_error(self, mock_db_session):
        """Test that authentication errors stop processing."""
        mock_protocol = MagicMock()
        mock_protocol.id = 1

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_protocol]
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        with patch('app.services.protocol_processor.process_protocol', new_callable=AsyncMock) as mock_process:
            mock_process.side_effect = AuthenticationError("Auth failed")

            with pytest.raises(AuthenticationError):
                await process_protocols_job(mock_db_session)

    @pytest.mark.asyncio
    async def test_process_protocols_job_other_error_continues(self, mock_db_session):
        """Test that other errors continue processing."""
        mock_protocol1 = MagicMock()
        mock_protocol1.id = 1
        mock_protocol2 = MagicMock()
        mock_protocol2.id = 2

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_protocol1, mock_protocol2]
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        with patch('app.services.protocol_processor.process_protocol', new_callable=AsyncMock) as mock_process:
            mock_process.side_effect = [Exception("Error"), None]

            result = await process_protocols_job(mock_db_session)

            assert result == 1


class TestProcessProtocol:
    """Tests for process_protocol function."""

    @pytest.mark.asyncio
    async def test_process_protocol_with_existing_articles(self, mock_db_session):
        """Test processing protocol with existing articles."""
        mock_protocol = MagicMock()
        mock_protocol.id = 1
        mock_protocol.title = "Test"

        mock_article = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_article]
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        with patch('app.services.protocol_processor._process_existing_protocol', new_callable=AsyncMock) as mock_process_existing:
            await process_protocol(mock_protocol, mock_db_session)

            mock_process_existing.assert_called_once()


class TestProcessSingleArticle:
    """Tests for process_single_article function."""

    @pytest.mark.asyncio
    async def test_process_single_article_no_image_generated(self, mock_db_session):
        """Test when no image is generated."""
        mock_protocol = MagicMock()
        mock_protocol.id = 1
        mock_protocol.session_date = date(2024, 1, 1)
        mock_protocol.title = "Test"

        mock_article_data = MagicMock()
        mock_article_data.ueberschrift = "Test Title"
        mock_article_data.inhalt = "<p>Content</p>"

        with patch('app.services.protocol_processor.generate_image_for_article') as mock_gen_image:
            mock_gen_image.return_value = ("prompt", None)  # No image bytes

            result = await process_single_article(
                mock_protocol, mock_article_data, 1, None, mock_db_session
            )

            assert result == (None, False)

    @pytest.mark.asyncio
    async def test_process_single_article_success_returns_true(self, mock_db_session, tmp_path):
        """Test that a saved image is reported as success."""
        mock_protocol = MagicMock()
        mock_protocol.id = 1
        mock_protocol.session_date = date(2024, 1, 1)
        mock_protocol.title = "Test"

        mock_article_data = MagicMock()
        mock_article_data.ueberschrift = "Test Title"
        mock_article_data.inhalt = "<p>Content</p>"

        image_path = tmp_path / "image_01.jpg"

        with patch('app.services.protocol_processor.generate_image_for_article') as mock_gen_image:
            mock_gen_image.return_value = ("prompt", b"image-bytes")

            with patch('app.services.protocol_processor.save_image_to_file') as mock_save:
                mock_save.return_value = image_path

                with patch(
                    'app.services.protocol_processor.generate_insta_caption',
                    return_value="Caption",
                ):
                    result = await process_single_article(
                        mock_protocol, mock_article_data, 1, None, mock_db_session
                    )

        assert result == (tmp_path, True)

    @pytest.mark.asyncio
    async def test_process_single_article_exception_during_processing(self, mock_db_session):
        """Test handling of exception during article processing."""
        mock_protocol = MagicMock()
        mock_protocol.id = 1

        mock_article_data = MagicMock()
        mock_article_data.ueberschrift = "Test Title"
        mock_article_data.inhalt = "<p>Content</p>"

        with patch('app.services.protocol_processor.generate_image_for_article') as mock_gen_image:
            mock_gen_image.side_effect = Exception("Generation failed")

            with pytest.raises(Exception):
                await process_single_article(
                    mock_protocol, mock_article_data, 1, None, mock_db_session
                )


class TestSaveImageToFile:
    """Tests for save_image_to_file function."""

    def test_save_image_to_file_io_error(self, tmp_path):
        """Test handling of IO error when saving image."""
        image_bytes = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100

        with patch('app.services.protocol_processor.create_protocol_folder') as mock_create:
            mock_create.return_value = tmp_path

            with patch('PIL.Image.open') as mock_open:
                mock_image = MagicMock()
                mock_image.mode = "RGB"
                mock_image.convert.return_value = mock_image
                mock_image.save.side_effect = IOError("Disk full")
                mock_open.return_value = mock_image

                with pytest.raises(IOError):
                    save_image_to_file(
                        image_bytes, None, 1, date(2024, 1, 1), "Test"
                    )

    def test_save_image_to_file_creates_folder(self, tmp_path):
        """Test that folder is created when it doesn't exist."""
        image_bytes = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100

        with patch('app.services.protocol_processor.create_protocol_folder') as mock_create:
            mock_create.return_value = tmp_path

            with patch('PIL.Image.open') as mock_open:
                mock_image = MagicMock()
                mock_image.mode = "RGB"
                mock_image.convert.return_value = mock_image
                mock_open.return_value = mock_image

                result = save_image_to_file(
                    image_bytes, None, 1, date(2024, 1, 1), "Test"
                )

                assert result.parent == tmp_path
                mock_create.assert_called_once()


class TestSanitizeFilename:
    """Tests for sanitize_filename function."""

    def test_sanitize_filename_with_spaces(self):
        """Test replacing spaces with underscores."""
        result = sanitize_filename("file name with spaces")
        assert result == "file_name_with_spaces"

    def test_sanitize_filename_with_special_chars(self):
        """Test removing special characters."""
        result = sanitize_filename("file@name#with$special%chars")
        assert "@" not in result
        assert "#" not in result
        assert "$" not in result
        assert "%" not in result

    def test_sanitize_filename_multiple_underscores(self):
        """Test collapsing multiple underscores."""
        result = sanitize_filename("file___name")
        assert "___" not in result

    def test_sanitize_filename_strips_special_ends(self):
        """Test stripping special characters from ends."""
        result = sanitize_filename("._-filename-_.")
        assert not result.startswith(".")
        assert not result.startswith("_")
        assert not result.startswith("-")
        assert not result.endswith(".")
        assert not result.endswith("_")
        assert not result.endswith("-")

    def test_sanitize_filename_preserves_allowed(self):
        """Test that allowed characters are preserved."""
        result = sanitize_filename("Test_File-Name.txt")
        assert "Test_File-Name" in result


class TestProcessExistingProtocol:
    """Tests for _process_existing_protocol function."""

    @pytest.mark.asyncio
    async def test_process_existing_protocol_regenerates_images(self, mock_db_session, tmp_path):
        """Test regenerating images when none exist."""
        mock_protocol = MagicMock()
        mock_protocol.id = 1
        mock_protocol.session_date = date(2024, 1, 1)
        mock_protocol.title = "Test Protocol"

        mock_article = MagicMock()
        mock_article.article_index = 1
        mock_article.content = "<h1>Title</h1><p>Content</p>"
        mock_article.caption = "Caption"

        existing_articles = [mock_article]
        protocol_folder = tmp_path / "240101_test_protocol"
        protocol_folder.mkdir()

        with patch('app.services.protocol_processor.create_protocol_folder') as mock_create:
            mock_create.return_value = protocol_folder

            with patch('app.services.protocol_processor.generate_image_for_article') as mock_gen:
                mock_gen.return_value = ("prompt", b'image_bytes')

                with patch('app.services.protocol_processor.save_image_to_file') as mock_save:
                    mock_save.return_value = protocol_folder / "image_01.jpg"

                    with patch('app.services.protocol_processor.create_insta_images_for_protocol_async', new_callable=AsyncMock):
                        await _process_existing_protocol(mock_protocol, existing_articles, mock_db_session)

                        mock_gen.assert_called_once()
                        assert mock_protocol.processed is True

    @pytest.mark.asyncio
    async def test_process_existing_protocol_skips_image_regeneration(self, mock_db_session, tmp_path):
        """Test skipping image regeneration when images exist."""
        mock_protocol = MagicMock()
        mock_protocol.id = 1
        mock_protocol.session_date = date(2024, 1, 1)
        mock_protocol.title = "Test Protocol"

        mock_article = MagicMock()
        mock_article.article_index = 1
        mock_article.content = "<h1>Title</h1><p>Content</p>"
        mock_article.caption = "Caption"

        existing_articles = [mock_article]
        protocol_folder = tmp_path / "240101_test_protocol"
        protocol_folder.mkdir()
        (protocol_folder / "image_01.jpg").write_bytes(b"existing")

        with patch('app.services.protocol_processor.create_protocol_folder') as mock_create:
            mock_create.return_value = protocol_folder

            with patch('app.services.protocol_processor.generate_image_for_article') as mock_gen:
                with patch('app.services.protocol_processor.create_insta_images_for_protocol_async', new_callable=AsyncMock):
                    await _process_existing_protocol(mock_protocol, existing_articles, mock_db_session)

                    mock_gen.assert_not_called()
                    assert mock_protocol.processed is True

    @pytest.mark.asyncio
    async def test_process_existing_protocol_leaves_unprocessed_on_image_failure(
        self, mock_db_session, tmp_path
    ):
        """Failed image generation must not mark the protocol as processed."""
        mock_protocol = MagicMock()
        mock_protocol.id = 55
        mock_protocol.session_date = date(2026, 8, 26)
        mock_protocol.title = "Jugendausschuss"

        mock_article = MagicMock()
        mock_article.article_index = 1
        mock_article.content = "<h1>Title</h1><p>Content</p>"
        mock_article.caption = None

        protocol_folder = tmp_path / "260826_jugendausschuss"
        protocol_folder.mkdir()

        with patch('app.services.protocol_processor.create_protocol_folder') as mock_create:
            mock_create.return_value = protocol_folder

            with patch('app.services.protocol_processor.generate_image_for_article') as mock_gen:
                mock_gen.return_value = ("prompt", b"")

                with patch(
                    'app.services.protocol_processor.create_insta_images_for_protocol_async',
                    new_callable=AsyncMock,
                ) as mock_insta:
                    await _process_existing_protocol(
                        mock_protocol, [mock_article], mock_db_session
                    )

                    assert mock_protocol.processed is False
                    mock_db_session.commit.assert_awaited()
                    mock_insta.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_existing_protocol_regenerates_only_missing_images(
        self, mock_db_session, tmp_path
    ):
        """Only articles without an existing image should be regenerated."""
        mock_protocol = MagicMock()
        mock_protocol.id = 1
        mock_protocol.session_date = date(2024, 1, 1)
        mock_protocol.title = "Test Protocol"

        article_one = MagicMock()
        article_one.article_index = 1
        article_one.content = "<h1>One</h1><p>Content</p>"
        article_one.caption = None

        article_two = MagicMock()
        article_two.article_index = 2
        article_two.content = "<h1>Two</h1><p>Content</p>"
        article_two.caption = None

        protocol_folder = tmp_path / "240101_test_protocol"
        protocol_folder.mkdir()
        (protocol_folder / "image_01.jpg").write_bytes(b"existing")

        with patch('app.services.protocol_processor.create_protocol_folder') as mock_create:
            mock_create.return_value = protocol_folder

            with patch('app.services.protocol_processor.generate_image_for_article') as mock_gen:
                mock_gen.return_value = ("prompt", b"image_bytes")

                with patch('app.services.protocol_processor.save_image_to_file') as mock_save:
                    mock_save.return_value = protocol_folder / "image_02.jpg"

                    with patch(
                        'app.services.protocol_processor.create_insta_images_for_protocol_async',
                        new_callable=AsyncMock,
                    ):
                        await _process_existing_protocol(
                            mock_protocol, [article_one, article_two], mock_db_session
                        )

        mock_gen.assert_called_once()
        generated_article = mock_gen.call_args.args[0]
        assert generated_article.ueberschrift == "Two"
