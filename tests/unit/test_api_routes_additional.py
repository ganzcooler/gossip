"""Additional tests for API routes to increase coverage."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException

from app.api.routes import (
    trigger_fetch_protocols,
    trigger_process_protocols,
    trigger_pipeline_run,
    get_pipeline_status
)


class TestTriggerFetchProtocols:
    """Tests for trigger_fetch_protocols endpoint."""

    @pytest.mark.asyncio
    async def test_trigger_fetch_protocols_success(self, mock_db_session):
        """Test successful triggering of fetch protocols."""
        with patch('app.api.routes.fetch_protocols_job', new_callable=AsyncMock) as mock_job:
            mock_job.return_value = 5

            result = await trigger_fetch_protocols(mock_db_session)

            assert result["status"] == "success"
            assert result["protocols_found"] == 5
            assert "5 new protocols fetched" in result["message"]

    @pytest.mark.asyncio
    async def test_trigger_fetch_protocols_zero_found(self, mock_db_session):
        """Test when no new protocols are found."""
        with patch('app.api.routes.fetch_protocols_job', new_callable=AsyncMock) as mock_job:
            mock_job.return_value = 0

            result = await trigger_fetch_protocols(mock_db_session)

            assert result["status"] == "success"
            assert result["protocols_found"] == 0

    @pytest.mark.asyncio
    async def test_trigger_fetch_protocols_error(self, mock_db_session):
        """Test handling of error during fetch."""
        with patch('app.api.routes.fetch_protocols_job', new_callable=AsyncMock) as mock_job:
            mock_job.side_effect = Exception("Fetch failed")

            with pytest.raises(HTTPException) as exc_info:
                await trigger_fetch_protocols(mock_db_session)

            assert exc_info.value.status_code == 500
            assert "Fetch failed" in exc_info.value.detail


class TestTriggerProcessProtocols:
    """Tests for trigger_process_protocols endpoint."""

    @pytest.mark.asyncio
    async def test_trigger_process_protocols_success(self, mock_db_session):
        """Test successful triggering of process protocols."""
        with patch('app.api.routes.process_protocols_job', new_callable=AsyncMock) as mock_job:
            mock_job.return_value = 3

            result = await trigger_process_protocols(mock_db_session)

            assert result["status"] == "success"
            assert result["processed"] == 3
            assert "3 protocols processed" in result["message"]

    @pytest.mark.asyncio
    async def test_trigger_process_protocols_zero_processed(self, mock_db_session):
        """Test when no protocols are processed."""
        with patch('app.api.routes.process_protocols_job', new_callable=AsyncMock) as mock_job:
            mock_job.return_value = 0

            result = await trigger_process_protocols(mock_db_session)

            assert result["status"] == "success"
            assert result["processed"] == 0

    @pytest.mark.asyncio
    async def test_trigger_process_protocols_error(self, mock_db_session):
        """Test handling of error during process."""
        with patch('app.api.routes.process_protocols_job', new_callable=AsyncMock) as mock_job:
            mock_job.side_effect = Exception("Process failed")

            with pytest.raises(HTTPException) as exc_info:
                await trigger_process_protocols(mock_db_session)

            assert exc_info.value.status_code == 500
            assert "Process failed" in exc_info.value.detail


class TestTriggerPipelineRun:
    """Tests for trigger_pipeline_run endpoint."""

    @pytest.mark.asyncio
    async def test_trigger_pipeline_run_success(self, mock_db_session):
        """Test successful full pipeline run."""
        with patch('app.api.routes.fetch_protocols_job', new_callable=AsyncMock) as mock_fetch:
            with patch('app.api.routes.process_protocols_job', new_callable=AsyncMock) as mock_process:
                mock_fetch.return_value = 5
                mock_process.return_value = 3

                result = await trigger_pipeline_run(mock_db_session)

                assert result["status"] == "success"
                assert result["fetch_result"]["protocols_found"] == 5
                assert result["process_result"]["processed"] == 3
                assert "5 fetched" in result["message"]
                assert "3 processed" in result["message"]

    @pytest.mark.asyncio
    async def test_trigger_pipeline_run_fetch_error(self, mock_db_session):
        """Test handling of fetch error during pipeline run."""
        with patch('app.api.routes.fetch_protocols_job', new_callable=AsyncMock) as mock_fetch:
            mock_fetch.side_effect = Exception("Fetch failed")

            with pytest.raises(HTTPException) as exc_info:
                await trigger_pipeline_run(mock_db_session)

            assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_trigger_pipeline_run_process_error(self, mock_db_session):
        """Test handling of process error during pipeline run."""
        with patch('app.api.routes.fetch_protocols_job', new_callable=AsyncMock) as mock_fetch:
            with patch('app.api.routes.process_protocols_job', new_callable=AsyncMock) as mock_process:
                mock_fetch.return_value = 5
                mock_process.side_effect = Exception("Process failed")

                with pytest.raises(HTTPException) as exc_info:
                    await trigger_pipeline_run(mock_db_session)

                assert exc_info.value.status_code == 500


class TestGetPipelineStatus:
    """Tests for get_pipeline_status endpoint."""

    @pytest.mark.asyncio
    async def test_get_pipeline_status_empty(self, mock_db_session):
        """Test pipeline status with no protocols."""
        mock_total = MagicMock()
        mock_total.scalar.return_value = 0

        mock_unprocessed = MagicMock()
        mock_unprocessed.scalar.return_value = 0

        mock_articles = MagicMock()
        mock_articles.scalar.return_value = 0

        mock_db_session.execute = AsyncMock(side_effect=[mock_total, mock_unprocessed, mock_articles])

        result = await get_pipeline_status(mock_db_session)

        assert result["total_protocols"] == 0
        assert result["unprocessed_protocols"] == 0
        assert result["total_articles"] == 0

    @pytest.mark.asyncio
    async def test_get_pipeline_status_with_data(self, mock_db_session):
        """Test pipeline status with protocols."""
        mock_total = MagicMock()
        mock_total.scalar.return_value = 10

        mock_unprocessed = MagicMock()
        mock_unprocessed.scalar.return_value = 3

        mock_articles = MagicMock()
        mock_articles.scalar.return_value = 25

        mock_db_session.execute = AsyncMock(side_effect=[mock_total, mock_unprocessed, mock_articles])

        result = await get_pipeline_status(mock_db_session)

        assert result["total_protocols"] == 10
        assert result["unprocessed_protocols"] == 3
        assert result["total_articles"] == 25


class TestGetStats:
    """Tests for get_stats endpoint."""

    @pytest.mark.asyncio
    async def test_get_stats_comprehensive(self, mock_db_session):
        """Test comprehensive stats calculation."""
        from app.api.routes import get_stats

        mock_total = MagicMock()
        mock_total.scalar.return_value = 100

        mock_processed = MagicMock()
        mock_processed.scalar.return_value = 75

        mock_articles = MagicMock()
        mock_articles.scalar.return_value = 250

        mock_db_session.execute = AsyncMock(side_effect=[mock_total, mock_processed, mock_articles])

        result = await get_stats(mock_db_session)

        assert result["total_protocols"] == 100
        assert result["processed_protocols"] == 75
        assert result["unprocessed_protocols"] == 25
        assert result["total_articles"] == 250
