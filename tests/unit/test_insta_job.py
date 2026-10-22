import os
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
os.environ.setdefault("ARTICLES_DIR", str(project_root / "app/articles"))
os.environ.setdefault("LOGS_DIR", str(project_root / "app/logs"))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import date

from app.utils.folder_utils import normalize_for_folder_name
from app.services.insta_job import (
    generate_insta_images_job,
    _get_protocol_folder,
    _check_protocol_folder_exists,
    _check_source_images_exist,
    _check_articles_with_content_exist,
)
from app.api.routes import trigger_generate_insta
from fastapi import HTTPException


class TestGenerateInstaImagesJob:
    """Test class for generate_insta_images_job function."""

    @pytest.fixture
    def mock_protocol(self):
        protocol = MagicMock()
        protocol.id = 1
        protocol.title = "Test Protocol Title"
        protocol.session_date = date(2024, 1, 15)
        protocol.processed = True
        return protocol

    @pytest.fixture
    def mock_articles_complete(self):
        article1 = MagicMock()
        article1.article_index = 0
        article1.content = "<h1>Article Title</h1><p>Content here</p>"
        article1.caption = "Caption for article 1 #test #Rosdorf"

        article2 = MagicMock()
        article2.article_index = 1
        article2.content = "<h1>Second Article</h1><p>More content</p>"
        article2.caption = "Caption for article 2 #test #Rosdorf"

        return [article1, article2]

    @pytest.fixture
    def mock_articles_no_content(self):
        article = MagicMock()
        article.article_index = 0
        article.content = None
        article.caption = "Caption"
        return [article]

    @pytest.fixture
    def setup_mock_db_single_protocol(self, mock_db_session, mock_protocol, mock_articles_complete):
        def configure_execute(query, *args, **kwargs):
            mock_result = MagicMock()
            if hasattr(mock_result, 'scalars'):
                mock_scalars = MagicMock()
                mock_scalars.all.return_value = [mock_protocol]
                mock_result.scalars.return_value = mock_scalars
            return mock_result

        protocol_result = MagicMock()
        protocol_scalars = MagicMock()
        protocol_scalars.all.return_value = [mock_protocol]
        protocol_result.scalars.return_value = protocol_scalars

        article_result = MagicMock()
        article_scalars = MagicMock()
        article_scalars.all.return_value = mock_articles_complete
        article_result.scalars.return_value = article_scalars

        mock_db_session.execute = AsyncMock(side_effect=[protocol_result, article_result])
        return mock_db_session

    async def _setup_protocol_folder(self, tmp_path, mock_protocol, with_images=True):
        normalized = mock_protocol.title.replace(' ', '_').lower()
        normalized = ''.join(c for c in normalized if c.isalnum() or c == '_')[:80]
        folder_name = f"{mock_protocol.session_date.strftime('%y%m%d')}_{normalized}"
        protocol_folder = tmp_path / folder_name
        protocol_folder.mkdir(parents=True, exist_ok=True)

        if with_images:
            (protocol_folder / "image_0.jpg").write_bytes(b"fake image data")

        return protocol_folder

    @pytest.mark.asyncio
    async def test_single_protocol_all_data_present(
        self, mock_db_session, mock_protocol, mock_articles_complete, tmp_path
    ):
        """Single protocol, all data present - Success."""
        await self._setup_protocol_folder(tmp_path, mock_protocol, with_images=True)

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

                mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_single_protocol_folder_not_found(
        self, mock_db_session, mock_protocol, mock_articles_complete, tmp_path
    ):
        """Single protocol, folder missing - Error."""
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

                mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_single_protocol_no_source_images(
        self, mock_db_session, mock_protocol, mock_articles_complete, tmp_path
    ):
        """Single protocol, no images - Error."""
        await self._setup_protocol_folder(tmp_path, mock_protocol, with_images=False)

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

                mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_single_protocol_no_content(
        self, mock_db_session, mock_protocol, tmp_path
    ):
        """Single protocol, no content - Error."""
        mock_articles_no_content = []
        article = MagicMock()
        article.article_index = 0
        article.content = None
        article.caption = "Caption"
        mock_articles_no_content.append(article)

        await self._setup_protocol_folder(tmp_path, mock_protocol, with_images=True)

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

                mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_batch_mode_mixed_results(self, mock_db_session, tmp_path):
        """Batch mode, mixed results - Only valid protocols processed."""
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

        await self._setup_protocol_folder(tmp_path, protocol_valid, with_images=True)

        await self._setup_protocol_folder(tmp_path, protocol_no_images, with_images=False)

        articles_valid = [MagicMock(article_index=0, content="<h1>Title</h1>", caption="Caption")]
        articles_no_folder = [MagicMock(article_index=0, content="<h1>Title</h1>", caption="Caption")]
        articles_no_images = [MagicMock(article_index=0, content="<h1>Title</h1>", caption="Caption")]

        protocol_result = MagicMock()
        protocol_scalars = MagicMock()
        protocol_scalars.all.return_value = protocols
        protocol_result.scalars.return_value = protocol_scalars

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

                mock_create.assert_called_once()

                detail_map = {d["protocol_id"]: d for d in result["details"]}
                assert detail_map[1]["status"] == "success"
                assert detail_map[2]["reason"] == "Protocol folder not found"
                assert detail_map[3]["reason"] == "No source images found"


class TestGenerateInstaImagesJobEdgeCases:
    """Additional edge case tests for generate_insta_images_job."""

    @pytest.mark.asyncio
    async def test_empty_articles_list(self, mock_db_session, tmp_path):
        protocol = MagicMock()
        protocol.id = 1
        protocol.title = "Test Protocol"
        protocol.session_date = date(2024, 1, 15)
        protocol.processed = True

        normalized = protocol.title.replace(' ', '_').lower()
        normalized = ''.join(c for c in normalized if c.isalnum() or c == '_')[:80]
        folder_name = f"{protocol.session_date.strftime('%y%m%d')}_{normalized}"
        protocol_folder = tmp_path / folder_name
        protocol_folder.mkdir(parents=True, exist_ok=True)
        (protocol_folder / "image_0.jpg").write_bytes(b"fake")

        protocol_result = MagicMock()
        protocol_scalars = MagicMock()
        protocol_scalars.all.return_value = [protocol]
        protocol_result.scalars.return_value = protocol_scalars

        article_result = MagicMock()
        article_scalars = MagicMock()
        article_scalars.all.return_value = []
        article_result.scalars.return_value = article_scalars

        mock_db_session.execute = AsyncMock(side_effect=[protocol_result, article_result])

        with patch('app.services.insta_job.ARTICLES_DIR', tmp_path):
            result = await generate_insta_images_job(mock_db_session, protocol_id=1)

            assert result["status"] == "error"
            assert result["details"][0]["reason"] == "No articles in database"

    @pytest.mark.asyncio
    async def test_umlauts_in_protocol_title(self, mock_db_session, tmp_path):
        protocol = MagicMock()
        protocol.id = 1
        protocol.title = "Möting mit Änderungen und Übersicht"
        protocol.session_date = date(2024, 1, 15)
        protocol.processed = True

        normalized = normalize_for_folder_name(protocol.title)
        folder_name = f"240115_{normalized}"
        protocol_folder = tmp_path / folder_name
        protocol_folder.mkdir(parents=True, exist_ok=True)
        (protocol_folder / "image_0.jpg").write_bytes(b"fake")

        articles = [MagicMock(article_index=0, content="<h1>Title</h1>", caption="Caption")]

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
        protocol = MagicMock()
        protocol.id = 1
        protocol.title = "Test Protocol"
        protocol.session_date = date(2024, 1, 15)
        protocol.processed = True

        normalized = "test_protocol"
        folder_name = f"240115_{normalized}"
        protocol_folder = tmp_path / folder_name
        protocol_folder.mkdir(parents=True, exist_ok=True)
        (protocol_folder / "image_0.png").write_bytes(b"fake png")

        articles = [MagicMock(article_index=0, content="<h1>Title</h1>", caption="Caption")]

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
        protocol_result = MagicMock()
        protocol_scalars = MagicMock()
        protocol_scalars.all.return_value = []
        protocol_result.scalars.return_value = protocol_scalars

        mock_db_session.execute = AsyncMock(return_value=protocol_result)

        with patch('app.services.insta_job.ARTICLES_DIR', tmp_path):
            result = await generate_insta_images_job(mock_db_session, protocol_id=999)

            assert result["status"] == "success"
            assert result["processed"] == 0
            assert result["failed"] == 0

    @pytest.mark.asyncio
    async def test_all_batch_protocols_fail(self, mock_db_session, tmp_path):
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

        articles1 = [MagicMock(article_index=0, content="<h1>Title</h1>", caption="Caption")]
        articles2 = [MagicMock(article_index=0, content="<h1>Title</h1>", caption="Caption")]

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
            result = await generate_insta_images_job(mock_db_session, protocol_id=None)

            assert result["status"] == "error"
            assert result["processed"] == 0
            assert result["failed"] == 2


class TestHelperFunctions:
    """Tests for helper functions in insta_job module."""

    def test_get_protocol_folder(self, tmp_path):
        protocol = MagicMock()
        protocol.title = "Test Protocol"
        protocol.session_date = date(2024, 1, 15)

        with patch('app.services.insta_job.ARTICLES_DIR', tmp_path):
            folder = _get_protocol_folder(protocol)
            assert folder.name == "240115_test_protocol"
            assert folder.parent == tmp_path

    def test_get_protocol_folder_with_umlauts(self, tmp_path):
        protocol = MagicMock()
        protocol.title = "Möting Änderung Übergriff"
        protocol.session_date = date(2024, 1, 15)

        with patch('app.services.insta_job.ARTICLES_DIR', tmp_path):
            folder = _get_protocol_folder(protocol)
            assert "moeting" in folder.name.lower()
            assert "aenderung" in folder.name.lower()
            assert "uebergriff" in folder.name.lower()

    def test_check_protocol_folder_exists(self, tmp_path):
        existing_folder = tmp_path / "existing"
        existing_folder.mkdir()
        non_existing_folder = tmp_path / "non_existing"

        assert _check_protocol_folder_exists(existing_folder) is True
        assert _check_protocol_folder_exists(non_existing_folder) is False

    def test_check_source_images_exist_jpg(self, tmp_path):
        folder = tmp_path / "test"
        folder.mkdir()
        (folder / "image_0.jpg").write_bytes(b"fake")

        assert _check_source_images_exist(folder) is True

    def test_check_source_images_exist_png(self, tmp_path):
        folder = tmp_path / "test"
        folder.mkdir()
        (folder / "image_0.png").write_bytes(b"fake")

        assert _check_source_images_exist(folder) is True

    def test_check_source_images_exist_none(self, tmp_path):
        folder = tmp_path / "test"
        folder.mkdir()

        assert _check_source_images_exist(folder) is False

    def test_check_articles_with_content_exist_true(self):
        articles = [
            MagicMock(content="Some content"),
            MagicMock(content=None),
        ]
        assert _check_articles_with_content_exist(articles) is True

    def test_check_articles_with_content_exist_false(self):
        articles = [
            MagicMock(content=None),
            MagicMock(content=None),
        ]
        assert _check_articles_with_content_exist(articles) is False

    def test_check_articles_with_content_exist_empty(self):
        assert _check_articles_with_content_exist([]) is False


class TestGenerateInstaEndpoint:
    """Test class for the API endpoint trigger_generate_insta."""

    @pytest.mark.asyncio
    async def test_endpoint_valid_protocol_id(self, mock_db_session, tmp_path):
        protocol = MagicMock()
        protocol.id = 1
        protocol.title = "Test Protocol"
        protocol.session_date = date(2024, 1, 15)
        protocol.processed = True

        normalized = "test_protocol"
        folder_name = f"240115_{normalized}"
        protocol_folder = tmp_path / folder_name
        protocol_folder.mkdir(parents=True, exist_ok=True)
        (protocol_folder / "image_0.jpg").write_bytes(b"fake")

        articles = [MagicMock(article_index=0, content="<h1>Title</h1>", caption="Caption")]

        check_result = MagicMock()
        check_result.scalar_one_or_none.return_value = protocol

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
        check_result = MagicMock()
        check_result.scalar_one_or_none.return_value = None

        mock_db_session.execute = AsyncMock(return_value=check_result)

        with pytest.raises(HTTPException) as exc_info:
            await trigger_generate_insta(protocol_id=999, db=mock_db_session)

        assert exc_info.value.status_code == 404
        assert "Protocol 999 not found" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_endpoint_batch_mode(self, mock_db_session, tmp_path):
        protocol = MagicMock()
        protocol.id = 1
        protocol.title = "Test Protocol"
        protocol.session_date = date(2024, 1, 15)
        protocol.processed = True

        normalized = "test_protocol"
        folder_name = f"240115_{normalized}"
        protocol_folder = tmp_path / folder_name
        protocol_folder.mkdir(parents=True, exist_ok=True)
        (protocol_folder / "image_0.jpg").write_bytes(b"fake")

        articles = [MagicMock(article_index=0, content="<h1>Title</h1>", caption="Caption")]

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
        protocol = MagicMock()
        protocol.id = 1
        protocol.title = "Test Protocol"
        protocol.session_date = date(2024, 1, 15)
        protocol.processed = True

        check_result = MagicMock()
        check_result.scalar_one_or_none.return_value = protocol

        protocol_result = MagicMock()
        protocol_scalars = MagicMock()
        protocol_scalars.all.return_value = [protocol]
        protocol_result.scalars.return_value = protocol_scalars

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
