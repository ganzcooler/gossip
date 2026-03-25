"""
Comprehensive unit tests for app/services/insta_job.py

Test Coverage:
- TC-001 to TC-007: Unit tests for generate_insta_images_job function
- TC-008 to TC-011: API endpoint tests for trigger_generate_insta
"""

import os
import sys
from pathlib import Path

# Environment setup before app imports (follow conftest.py pattern)
project_root = Path(__file__).parent.parent.parent
os.environ.setdefault("ARTICLES_DIR", str(project_root / "app/articles"))
os.environ.setdefault("LOGS_DIR", str(project_root / "app/logs"))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
from datetime import date
import shutil

from app.services.insta_job import (
    generate_insta_images_job,
    _get_protocol_folder,
    _check_protocol_folder_exists,
    _check_source_images_exist,
    _check_articles_with_content_exist,
    _check_all_articles_have_short_article,
)
from app.api.routes import trigger_generate_insta
from app.models import Protocol, Article
from fastapi import HTTPException


class TestGenerateInstaImagesJob:
    """Test class for generate_insta_images_job function."""

    @pytest.fixture
    def mock_protocol(self):
        """Return a mock protocol with id, title, session_date, processed."""
        protocol = MagicMock()
        protocol.id = 1
        protocol.title = "Test Protocol Title"
        protocol.session_date = date(2024, 1, 15)
        protocol.processed = True
        return protocol

    @pytest.fixture
    def mock_articles_complete(self):
        """Return list of mock articles with content, short_article, article_index."""
        article1 = MagicMock()
        article1.article_index = 0
        article1.content = "<h1>Article Title</h1><p>Content here</p>"
        article1.short_article = "Short version of article 1"

        article2 = MagicMock()
        article2.article_index = 1
        article2.content = "<h1>Second Article</h1><p>More content</p>"
        article2.short_article = "Short version of article 2"

        return [article1, article2]

    @pytest.fixture
    def mock_articles_no_content(self):
        """Return articles without content."""
        article = MagicMock()
        article.article_index = 0
        article.content = None
        article.short_article = "Short version"
        return [article]

    @pytest.fixture
    def mock_articles_no_short(self):
        """Return articles without short_article."""
        article = MagicMock()
        article.article_index = 0
        article.content = "<h1>Title</h1><p>Content</p>"
        article.short_article = None
        return [article]

    @pytest.fixture
    def setup_mock_db_single_protocol(self, mock_db_session, mock_protocol, mock_articles_complete):
        """Setup mock database for single protocol query."""
        def configure_execute(query, *args, **kwargs):
            mock_result = MagicMock()
            # First query is for Protocol
            if hasattr(mock_result, 'scalars'):
                mock_scalars = MagicMock()
                mock_scalars.all.return_value = [mock_protocol]
                mock_result.scalars.return_value = mock_scalars
            return mock_result

        # First execute returns protocols
        protocol_result = MagicMock()
        protocol_scalars = MagicMock()
        protocol_scalars.all.return_value = [mock_protocol]
        protocol_result.scalars.return_value = protocol_scalars

        # Second execute returns articles
        article_result = MagicMock()
        article_scalars = MagicMock()
        article_scalars.all.return_value = mock_articles_complete
        article_result.scalars.return_value = article_scalars

        mock_db_session.execute = AsyncMock(side_effect=[protocol_result, article_result])
        return mock_db_session

    async def _setup_protocol_folder(self, tmp_path, mock_protocol, with_images=True):
        """Helper to set up protocol folder with images."""
        normalized = mock_protocol.title.replace(' ', '_').lower()
        normalized = ''.join(c for c in normalized if c.isalnum() or c == '_')[:80]
        folder_name = f"{mock_protocol.session_date.strftime('%y%m%d')}_{normalized}"
        protocol_folder = tmp_path / folder_name
        protocol_folder.mkdir(parents=True, exist_ok=True)

        if with_images:
            # Create a dummy image file
            (protocol_folder / "image_0.jpg").write_bytes(b"fake image data")

        return protocol_folder

    @pytest.mark.asyncio
    async def test_single_protocol_all_data_present(
        self, mock_db_session, mock_protocol, mock_articles_complete, tmp_path
    ):
        """TC-001: Single protocol, all data present - Success, folders deleted and recreated."""
        # Setup protocol folder with images
        protocol_folder = await self._setup_protocol_folder(tmp_path, mock_protocol, with_images=True)

        # Create existing storys and posts folders
        (protocol_folder / "storys").mkdir(exist_ok=True)
        (protocol_folder / "posts").mkdir(exist_ok=True)
        (protocol_folder / "storys" / "old_story.jpg").write_text("old")
        (protocol_folder / "posts" / "old_post.jpg").write_text("old")

        # Setup mock database
        protocol_result = MagicMock()
        protocol_scalars = MagicMock()
        protocol_scalars.all.return_value = [mock_protocol]
        protocol_result.scalars.return_value = protocol_scalars

        article_result = MagicMock()
        article_scalars = MagicMock()
        article_scalars.all.return_value = mock_articles_complete
        article_result.scalars.return_value = article_scalars

        mock_db_session.execute = AsyncMock(side_effect=[protocol_result, article_result])

        with patch('app.services.insta_job.ARTICLES_DIR', tmp_path):
            with patch(
                'app.services.insta_job.create_insta_images_for_protocol_async',
                new_callable=AsyncMock
            ) as mock_create:
                result = await generate_insta_images_job(mock_db_session, protocol_id=1)

                assert result["status"] == "success"
                assert result["processed"] == 1
                assert result["failed"] == 0
                assert len(result["details"]) == 1
                assert result["details"][0]["status"] == "success"

                # Verify folders were deleted
                assert not (protocol_folder / "storys").exists()
                assert not (protocol_folder / "posts").exists()

                # Verify image generator was called
                mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_single_protocol_folder_not_found(
        self, mock_db_session, mock_protocol, mock_articles_complete, tmp_path
    ):
        """TC-002: Single protocol, folder missing - Error, no deletion."""
        # Setup mock database
        protocol_result = MagicMock()
        protocol_scalars = MagicMock()
        protocol_scalars.all.return_value = [mock_protocol]
        protocol_result.scalars.return_value = protocol_scalars

        article_result = MagicMock()
        article_scalars = MagicMock()
        article_scalars.all.return_value = mock_articles_complete
        article_result.scalars.return_value = article_scalars

        mock_db_session.execute = AsyncMock(side_effect=[protocol_result, article_result])

        with patch('app.services.insta_job.ARTICLES_DIR', tmp_path):
            with patch(
                'app.services.insta_job.create_insta_images_for_protocol_async',
                new_callable=AsyncMock
            ) as mock_create:
                result = await generate_insta_images_job(mock_db_session, protocol_id=1)

                assert result["status"] == "error"
                assert result["processed"] == 0
                assert result["failed"] == 1
                assert result["details"][0]["reason"] == "Protocol folder not found"

                # Verify image generator was NOT called
                mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_single_protocol_no_source_images(
        self, mock_db_session, mock_protocol, mock_articles_complete, tmp_path
    ):
        """TC-003: Single protocol, no images - Error, no deletion."""
        # Setup protocol folder WITHOUT images
        protocol_folder = await self._setup_protocol_folder(tmp_path, mock_protocol, with_images=False)

        # Create existing storys folder (should NOT be deleted)
        (protocol_folder / "storys").mkdir(exist_ok=True)
        (protocol_folder / "storys" / "old_story.jpg").write_text("old")

        # Setup mock database
        protocol_result = MagicMock()
        protocol_scalars = MagicMock()
        protocol_scalars.all.return_value = [mock_protocol]
        protocol_result.scalars.return_value = protocol_scalars

        article_result = MagicMock()
        article_scalars = MagicMock()
        article_scalars.all.return_value = mock_articles_complete
        article_result.scalars.return_value = article_scalars

        mock_db_session.execute = AsyncMock(side_effect=[protocol_result, article_result])

        with patch('app.services.insta_job.ARTICLES_DIR', tmp_path):
            with patch(
                'app.services.insta_job.create_insta_images_for_protocol_async',
                new_callable=AsyncMock
            ) as mock_create:
                result = await generate_insta_images_job(mock_db_session, protocol_id=1)

                assert result["status"] == "error"
                assert result["processed"] == 0
                assert result["failed"] == 1
                assert result["details"][0]["reason"] == "No source images found"

                # Verify storys folder was NOT deleted (validation failed before deletion)
                assert (protocol_folder / "storys").exists()

                # Verify image generator was NOT called
                mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_single_protocol_no_content(
        self, mock_db_session, mock_protocol, tmp_path
    ):
        """TC-004: Single protocol, no content - Error, no deletion."""
        # Create articles without content
        mock_articles_no_content = []
        article = MagicMock()
        article.article_index = 0
        article.content = None
        article.short_article = "Short version"
        mock_articles_no_content.append(article)

        # Setup protocol folder with images
        protocol_folder = await self._setup_protocol_folder(tmp_path, mock_protocol, with_images=True)
        (protocol_folder / "storys").mkdir(exist_ok=True)

        # Setup mock database
        protocol_result = MagicMock()
        protocol_scalars = MagicMock()
        protocol_scalars.all.return_value = [mock_protocol]
        protocol_result.scalars.return_value = protocol_scalars

        article_result = MagicMock()
        article_scalars = MagicMock()
        article_scalars.all.return_value = mock_articles_no_content
        article_result.scalars.return_value = article_scalars

        mock_db_session.execute = AsyncMock(side_effect=[protocol_result, article_result])

        with patch('app.services.insta_job.ARTICLES_DIR', tmp_path):
            with patch(
                'app.services.insta_job.create_insta_images_for_protocol_async',
                new_callable=AsyncMock
            ) as mock_create:
                result = await generate_insta_images_job(mock_db_session, protocol_id=1)

                assert result["status"] == "error"
                assert result["processed"] == 0
                assert result["failed"] == 1
                assert result["details"][0]["reason"] == "No articles in database"

                # Verify storys folder was NOT deleted
                assert (protocol_folder / "storys").exists()

                # Verify image generator was NOT called
                mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_single_protocol_no_short_article(
        self, mock_db_session, mock_protocol, tmp_path
    ):
        """TC-005: Single protocol, no short_article - Error, no deletion."""
        # Create articles without short_article
        mock_articles_no_short = []
        article = MagicMock()
        article.article_index = 0
        article.content = "<h1>Title</h1><p>Content</p>"
        article.short_article = None
        mock_articles_no_short.append(article)

        # Setup protocol folder with images
        protocol_folder = await self._setup_protocol_folder(tmp_path, mock_protocol, with_images=True)
        (protocol_folder / "storys").mkdir(exist_ok=True)

        # Setup mock database
        protocol_result = MagicMock()
        protocol_scalars = MagicMock()
        protocol_scalars.all.return_value = [mock_protocol]
        protocol_result.scalars.return_value = protocol_scalars

        article_result = MagicMock()
        article_scalars = MagicMock()
        article_scalars.all.return_value = mock_articles_no_short
        article_result.scalars.return_value = article_scalars

        mock_db_session.execute = AsyncMock(side_effect=[protocol_result, article_result])

        with patch('app.services.insta_job.ARTICLES_DIR', tmp_path):
            with patch(
                'app.services.insta_job.create_insta_images_for_protocol_async',
                new_callable=AsyncMock
            ) as mock_create:
                result = await generate_insta_images_job(mock_db_session, protocol_id=1)

                assert result["status"] == "error"
                assert result["processed"] == 0
                assert result["failed"] == 1
                assert result["details"][0]["reason"] == "No short_article in database"

                # Verify storys folder was NOT deleted
                assert (protocol_folder / "storys").exists()

                # Verify image generator was NOT called
                mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_batch_mode_mixed_results(self, mock_db_session, tmp_path):
        """TC-006: Batch mode, mixed results - Only valid protocols processed."""
        # Create multiple protocols
        protocol_valid = MagicMock()
        protocol_valid.id = 1
        protocol_valid.title = "Valid Protocol"
        protocol_valid.session_date = date(2024, 1, 15)
        protocol_valid.processed = True

        protocol_no_folder = MagicMock()
        protocol_no_folder.id = 2
        protocol_no_folder.title = "No Folder Protocol"
        protocol_no_folder.session_date = date(2024, 1, 16)
        protocol_no_folder.processed = True

        protocol_no_images = MagicMock()
        protocol_no_images.id = 3
        protocol_no_images.title = "No Images Protocol"
        protocol_no_images.session_date = date(2024, 1, 17)
        protocol_no_images.processed = True

        protocols = [protocol_valid, protocol_no_folder, protocol_no_images]

        # Setup valid protocol folder with images
        valid_folder = await self._setup_protocol_folder(tmp_path, protocol_valid, with_images=True)
        (valid_folder / "storys").mkdir(exist_ok=True)

        # Setup no_images folder without images
        no_images_folder = await self._setup_protocol_folder(tmp_path, protocol_no_images, with_images=False)

        # Create articles for all protocols
        articles_valid = [MagicMock(article_index=0, content="<h1>Title</h1>", short_article="Short")]
        articles_no_folder = [MagicMock(article_index=0, content="<h1>Title</h1>", short_article="Short")]
        articles_no_images = [MagicMock(article_index=0, content="<h1>Title</h1>", short_article="Short")]

        # Setup mock database - first query returns protocols
        protocol_result = MagicMock()
        protocol_scalars = MagicMock()
        protocol_scalars.all.return_value = protocols
        protocol_result.scalars.return_value = protocol_scalars

        # Subsequent queries return articles for each protocol
        article_results = []
        for articles in [articles_valid, articles_no_folder, articles_no_images]:
            ar = MagicMock()
            asc = MagicMock()
            asc.all.return_value = articles
            ar.scalars.return_value = asc
            article_results.append(ar)

        mock_db_session.execute = AsyncMock(side_effect=[protocol_result] + article_results)

        with patch('app.services.insta_job.ARTICLES_DIR', tmp_path):
            with patch(
                'app.services.insta_job.create_insta_images_for_protocol_async',
                new_callable=AsyncMock
            ) as mock_create:
                result = await generate_insta_images_job(mock_db_session, protocol_id=None)

                assert result["status"] == "partial_success"
                assert result["processed"] == 1
                assert result["failed"] == 2
                assert len(result["details"]) == 3

                # Verify only valid protocol was processed
                mock_create.assert_called_once()

                # Verify details contain correct reasons
                detail_map = {d["protocol_id"]: d for d in result["details"]}
                assert detail_map[1]["status"] == "success"
                assert detail_map[2]["reason"] == "Protocol folder not found"
                assert detail_map[3]["reason"] == "No source images found"

    @pytest.mark.asyncio
    async def test_folder_deletion_permission_error(
        self, mock_db_session, mock_protocol, mock_articles_complete, tmp_path, caplog
    ):
        """TC-007: Folder deletion, PermissionError - Log error, Protocol as failed."""
        # Setup protocol folder with images
        protocol_folder = await self._setup_protocol_folder(tmp_path, mock_protocol, with_images=True)

        # Create storys folder with a file
        storys_folder = protocol_folder / "storys"
        storys_folder.mkdir(exist_ok=True)
        (storys_folder / "existing.jpg").write_text("data")

        # Setup mock database
        protocol_result = MagicMock()
        protocol_scalars = MagicMock()
        protocol_scalars.all.return_value = [mock_protocol]
        protocol_result.scalars.return_value = protocol_scalars

        article_result = MagicMock()
        article_scalars = MagicMock()
        article_scalars.all.return_value = mock_articles_complete
        article_result.scalars.return_value = article_scalars

        mock_db_session.execute = AsyncMock(side_effect=[protocol_result, article_result])

        with patch('app.services.insta_job.ARTICLES_DIR', tmp_path):
            with patch(
                'app.services.insta_job.create_insta_images_for_protocol_async',
                new_callable=AsyncMock
            ):
                with patch('shutil.rmtree', side_effect=PermissionError("Access denied")):
                    with caplog.at_level("ERROR"):
                        result = await generate_insta_images_job(mock_db_session, protocol_id=1)

                        assert result["status"] == "error"
                        assert result["processed"] == 0
                        assert result["failed"] == 1
                        assert "Access denied" in result["details"][0]["reason"]


class TestGenerateInstaImagesJobEdgeCases:
    """Additional edge case tests for generate_insta_images_job."""

    @pytest.mark.asyncio
    async def test_empty_articles_list(self, mock_db_session, tmp_path):
        """Test when articles list is empty."""
        protocol = MagicMock()
        protocol.id = 1
        protocol.title = "Test Protocol"
        protocol.session_date = date(2024, 1, 15)
        protocol.processed = True

        # Setup protocol folder with images
        normalized = protocol.title.replace(' ', '_').lower()
        normalized = ''.join(c for c in normalized if c.isalnum() or c == '_')[:80]
        folder_name = f"{protocol.session_date.strftime('%y%m%d')}_{normalized}"
        protocol_folder = tmp_path / folder_name
        protocol_folder.mkdir(parents=True, exist_ok=True)
        (protocol_folder / "image_0.jpg").write_bytes(b"fake")

        # Setup mock database
        protocol_result = MagicMock()
        protocol_scalars = MagicMock()
        protocol_scalars.all.return_value = [protocol]
        protocol_result.scalars.return_value = protocol_scalars

        article_result = MagicMock()
        article_scalars = MagicMock()
        article_scalars.all.return_value = []  # Empty articles
        article_result.scalars.return_value = article_scalars

        mock_db_session.execute = AsyncMock(side_effect=[protocol_result, article_result])

        with patch('app.services.insta_job.ARTICLES_DIR', tmp_path):
            result = await generate_insta_images_job(mock_db_session, protocol_id=1)

            assert result["status"] == "error"
            assert result["details"][0]["reason"] == "No articles in database"

    @pytest.mark.asyncio
    async def test_umlauts_in_protocol_title(self, mock_db_session, tmp_path):
        """Test protocol folder name with umlauts normalization."""
        protocol = MagicMock()
        protocol.id = 1
        protocol.title = "Möting mit Änderungen und Übersicht"
        protocol.session_date = date(2024, 1, 15)
        protocol.processed = True

        # The folder should be created with normalized name
        normalized = "Moeting_mit_Aenderungen_und_Uebersicht"
        folder_name = f"240115_{normalized}"
        protocol_folder = tmp_path / folder_name
        protocol_folder.mkdir(parents=True, exist_ok=True)
        (protocol_folder / "image_0.jpg").write_bytes(b"fake")

        articles = [MagicMock(article_index=0, content="<h1>Title</h1>", short_article="Short")]

        # Setup mock database
        protocol_result = MagicMock()
        protocol_scalars = MagicMock()
        protocol_scalars.all.return_value = [protocol]
        protocol_result.scalars.return_value = protocol_scalars

        article_result = MagicMock()
        article_scalars = MagicMock()
        article_scalars.all.return_value = articles
        article_result.scalars.return_value = article_scalars

        mock_db_session.execute = AsyncMock(side_effect=[protocol_result, article_result])

        with patch('app.services.insta_job.ARTICLES_DIR', tmp_path):
            with patch(
                'app.services.insta_job.create_insta_images_for_protocol_async',
                new_callable=AsyncMock
            ) as mock_create:
                result = await generate_insta_images_job(mock_db_session, protocol_id=1)

                assert result["status"] == "success"
                mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_png_images(self, mock_db_session, tmp_path):
        """Test that PNG images are also recognized as source images."""
        protocol = MagicMock()
        protocol.id = 1
        protocol.title = "Test Protocol"
        protocol.session_date = date(2024, 1, 15)
        protocol.processed = True

        normalized = "test_protocol"
        folder_name = f"240115_{normalized}"
        protocol_folder = tmp_path / folder_name
        protocol_folder.mkdir(parents=True, exist_ok=True)
        (protocol_folder / "image_0.png").write_bytes(b"fake png")  # PNG instead of JPG

        articles = [MagicMock(article_index=0, content="<h1>Title</h1>", short_article="Short")]

        # Setup mock database
        protocol_result = MagicMock()
        protocol_scalars = MagicMock()
        protocol_scalars.all.return_value = [protocol]
        protocol_result.scalars.return_value = protocol_scalars

        article_result = MagicMock()
        article_scalars = MagicMock()
        article_scalars.all.return_value = articles
        article_result.scalars.return_value = article_scalars

        mock_db_session.execute = AsyncMock(side_effect=[protocol_result, article_result])

        with patch('app.services.insta_job.ARTICLES_DIR', tmp_path):
            with patch(
                'app.services.insta_job.create_insta_images_for_protocol_async',
                new_callable=AsyncMock
            ) as mock_create:
                result = await generate_insta_images_job(mock_db_session, protocol_id=1)

                assert result["status"] == "success"
                mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_protocols_found_single_mode(self, mock_db_session, tmp_path):
        """Test when no protocol found for specific protocol_id."""
        # Setup mock database returning empty list
        protocol_result = MagicMock()
        protocol_scalars = MagicMock()
        protocol_scalars.all.return_value = []
        protocol_result.scalars.return_value = protocol_scalars

        mock_db_session.execute = AsyncMock(return_value=protocol_result)

        with patch('app.services.insta_job.ARTICLES_DIR', tmp_path):
            result = await generate_insta_images_job(mock_db_session, protocol_id=999)

            assert result["status"] == "success"  # No protocols to process is success
            assert result["processed"] == 0
            assert result["failed"] == 0

    @pytest.mark.asyncio
    async def test_all_batch_protocols_fail(self, mock_db_session, tmp_path):
        """Test when all protocols in batch mode fail."""
        protocol1 = MagicMock()
        protocol1.id = 1
        protocol1.title = "Protocol 1"
        protocol1.session_date = date(2024, 1, 15)
        protocol1.processed = True

        protocol2 = MagicMock()
        protocol2.id = 2
        protocol2.title = "Protocol 2"
        protocol2.session_date = date(2024, 1, 16)
        protocol2.processed = True

        protocols = [protocol1, protocol2]

        articles1 = [MagicMock(article_index=0, content="<h1>Title</h1>", short_article="Short")]
        articles2 = [MagicMock(article_index=0, content="<h1>Title</h1>", short_article="Short")]

        # Setup mock database
        protocol_result = MagicMock()
        protocol_scalars = MagicMock()
        protocol_scalars.all.return_value = protocols
        protocol_result.scalars.return_value = protocol_scalars

        article_result1 = MagicMock()
        article_scalars1 = MagicMock()
        article_scalars1.all.return_value = articles1
        article_result1.scalars.return_value = article_scalars1

        article_result2 = MagicMock()
        article_scalars2 = MagicMock()
        article_scalars2.all.return_value = articles2
        article_result2.scalars.return_value = article_scalars2

        mock_db_session.execute = AsyncMock(side_effect=[protocol_result, article_result1, article_result2])

        with patch('app.services.insta_job.ARTICLES_DIR', tmp_path):
            # No folders created - both will fail
            result = await generate_insta_images_job(mock_db_session, protocol_id=None)

            assert result["status"] == "error"
            assert result["processed"] == 0
            assert result["failed"] == 2


class TestHelperFunctions:
    """Tests for helper functions in insta_job module."""

    def test_get_protocol_folder(self, tmp_path):
        """Test _get_protocol_folder generates correct path."""
        protocol = MagicMock()
        protocol.title = "Test Protocol"
        protocol.session_date = date(2024, 1, 15)

        with patch('app.services.insta_job.ARTICLES_DIR', tmp_path):
            folder = _get_protocol_folder(protocol)
            assert folder.name == "240115_test_protocol"
            assert folder.parent == tmp_path

    def test_get_protocol_folder_with_umlauts(self, tmp_path):
        """Test _get_protocol_folder normalizes umlauts."""
        protocol = MagicMock()
        protocol.title = "Möting Änderung Übergriff"
        protocol.session_date = date(2024, 1, 15)

        with patch('app.services.insta_job.ARTICLES_DIR', tmp_path):
            folder = _get_protocol_folder(protocol)
            assert "moeting" in folder.name.lower()
            assert "aenderung" in folder.name.lower()
            assert "uebergriff" in folder.name.lower()

    def test_check_protocol_folder_exists(self, tmp_path):
        """Test _check_protocol_folder_exists."""
        existing_folder = tmp_path / "existing"
        existing_folder.mkdir()
        non_existing_folder = tmp_path / "non_existing"

        assert _check_protocol_folder_exists(existing_folder) is True
        assert _check_protocol_folder_exists(non_existing_folder) is False

    def test_check_source_images_exist_jpg(self, tmp_path):
        """Test _check_source_images_exist with JPG files."""
        folder = tmp_path / "test"
        folder.mkdir()
        (folder / "image_0.jpg").write_bytes(b"fake")

        assert _check_source_images_exist(folder) is True

    def test_check_source_images_exist_png(self, tmp_path):
        """Test _check_source_images_exist with PNG files."""
        folder = tmp_path / "test"
        folder.mkdir()
        (folder / "image_0.png").write_bytes(b"fake")

        assert _check_source_images_exist(folder) is True

    def test_check_source_images_exist_none(self, tmp_path):
        """Test _check_source_images_exist with no images."""
        folder = tmp_path / "test"
        folder.mkdir()

        assert _check_source_images_exist(folder) is False

    def test_check_articles_with_content_exist_true(self):
        """Test _check_articles_with_content_exist with content."""
        articles = [
            MagicMock(content="Some content"),
            MagicMock(content=None),
        ]
        assert _check_articles_with_content_exist(articles) is True

    def test_check_articles_with_content_exist_false(self):
        """Test _check_articles_with_content_exist without content."""
        articles = [
            MagicMock(content=None),
            MagicMock(content=None),
        ]
        assert _check_articles_with_content_exist(articles) is False

    def test_check_articles_with_content_exist_empty(self):
        """Test _check_articles_with_content_exist with empty list."""
        assert _check_articles_with_content_exist([]) is False

    def test_check_all_articles_have_short_article_true(self):
        """Test _check_all_articles_have_short_article all have."""
        articles = [
            MagicMock(short_article="Short 1"),
            MagicMock(short_article="Short 2"),
        ]
        assert _check_all_articles_have_short_article(articles) is True

    def test_check_all_articles_have_short_article_false(self):
        """Test _check_all_articles_have_short_article one missing."""
        articles = [
            MagicMock(short_article="Short 1"),
            MagicMock(short_article=None),
        ]
        assert _check_all_articles_have_short_article(articles) is False

    def test_check_all_articles_have_short_article_empty(self):
        """Test _check_all_articles_have_short_article with empty list."""
        assert _check_all_articles_have_short_article([]) is False


class TestGenerateInstaEndpoint:
    """Test class for the API endpoint trigger_generate_insta."""

    @pytest.mark.asyncio
    async def test_endpoint_valid_protocol_id(self, mock_db_session, tmp_path):
        """TC-008: Endpoint with valid protocol_id - HTTP 200, success."""
        protocol = MagicMock()
        protocol.id = 1
        protocol.title = "Test Protocol"
        protocol.session_date = date(2024, 1, 15)
        protocol.processed = True

        # Setup folder
        normalized = "test_protocol"
        folder_name = f"240115_{normalized}"
        protocol_folder = tmp_path / folder_name
        protocol_folder.mkdir(parents=True, exist_ok=True)
        (protocol_folder / "image_0.jpg").write_bytes(b"fake")

        articles = [MagicMock(article_index=0, content="<h1>Title</h1>", short_article="Short")]

        # Setup mock database for endpoint
        # First query checks if protocol exists
        check_result = MagicMock()
        check_result.scalar_one_or_none.return_value = protocol

        # Second query is for the job
        protocol_result = MagicMock()
        protocol_scalars = MagicMock()
        protocol_scalars.all.return_value = [protocol]
        protocol_result.scalars.return_value = protocol_scalars

        article_result = MagicMock()
        article_scalars = MagicMock()
        article_scalars.all.return_value = articles
        article_result.scalars.return_value = article_scalars

        mock_db_session.execute = AsyncMock(side_effect=[check_result, protocol_result, article_result])

        with patch('app.services.insta_job.ARTICLES_DIR', tmp_path):
            with patch(
                'app.services.insta_job.create_insta_images_for_protocol_async',
                new_callable=AsyncMock
            ):
                result = await trigger_generate_insta(protocol_id=1, db=mock_db_session)

                assert result["status"] == "success"
                assert result["processed"] == 1
                assert result["failed"] == 0

    @pytest.mark.asyncio
    async def test_endpoint_invalid_protocol_id(self, mock_db_session):
        """TC-009: Endpoint with invalid protocol_id - HTTP 404."""
        # Setup mock database returning None for protocol check
        check_result = MagicMock()
        check_result.scalar_one_or_none.return_value = None

        mock_db_session.execute = AsyncMock(return_value=check_result)

        with pytest.raises(HTTPException) as exc_info:
            await trigger_generate_insta(protocol_id=999, db=mock_db_session)

        assert exc_info.value.status_code == 404
        assert "Protocol 999 not found" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_endpoint_batch_mode(self, mock_db_session, tmp_path):
        """TC-010: Endpoint without protocol_id (Batch) - HTTP 200, processed >= 0."""
        protocol = MagicMock()
        protocol.id = 1
        protocol.title = "Test Protocol"
        protocol.session_date = date(2024, 1, 15)
        protocol.processed = True

        # Setup folder
        normalized = "test_protocol"
        folder_name = f"240115_{normalized}"
        protocol_folder = tmp_path / folder_name
        protocol_folder.mkdir(parents=True, exist_ok=True)
        (protocol_folder / "image_0.jpg").write_bytes(b"fake")

        articles = [MagicMock(article_index=0, content="<h1>Title</h1>", short_article="Short")]

        # Setup mock database for batch mode (no protocol check needed)
        protocol_result = MagicMock()
        protocol_scalars = MagicMock()
        protocol_scalars.all.return_value = [protocol]
        protocol_result.scalars.return_value = protocol_scalars

        article_result = MagicMock()
        article_scalars = MagicMock()
        article_scalars.all.return_value = articles
        article_result.scalars.return_value = article_scalars

        mock_db_session.execute = AsyncMock(side_effect=[protocol_result, article_result])

        with patch('app.services.insta_job.ARTICLES_DIR', tmp_path):
            with patch(
                'app.services.insta_job.create_insta_images_for_protocol_async',
                new_callable=AsyncMock
            ):
                result = await trigger_generate_insta(protocol_id=None, db=mock_db_session)

                assert result["status"] == "success"
                assert result["processed"] >= 0

    @pytest.mark.asyncio
    async def test_endpoint_validation_error(self, mock_db_session, tmp_path):
        """TC-011: Endpoint with validation error protocol - HTTP 400."""
        protocol = MagicMock()
        protocol.id = 1
        protocol.title = "Test Protocol"
        protocol.session_date = date(2024, 1, 15)
        protocol.processed = True

        # Setup mock database
        # First query checks if protocol exists
        check_result = MagicMock()
        check_result.scalar_one_or_none.return_value = protocol

        # Second query for the job - returns protocol
        protocol_result = MagicMock()
        protocol_scalars = MagicMock()
        protocol_scalars.all.return_value = [protocol]
        protocol_result.scalars.return_value = protocol_scalars

        # Third query returns empty articles (validation error)
        article_result = MagicMock()
        article_scalars = MagicMock()
        article_scalars.all.return_value = []
        article_result.scalars.return_value = article_scalars

        mock_db_session.execute = AsyncMock(side_effect=[check_result, protocol_result, article_result])

        with patch('app.services.insta_job.ARTICLES_DIR', tmp_path):
            with pytest.raises(HTTPException) as exc_info:
                await trigger_generate_insta(protocol_id=1, db=mock_db_session)

            assert exc_info.value.status_code == 400
            assert "Validation failed" in exc_info.value.detail