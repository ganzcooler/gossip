"""Tests for scheduler module."""

import pytest
from unittest.mock import AsyncMock, patch
from apscheduler.triggers.cron import CronTrigger

from app.scheduler import (
    fetch_protocols_wrapper,
    process_protocols_wrapper,
    setup_scheduler,
    start_scheduler,
    stop_scheduler,
    scheduler
)


class TestFetchProtocolsWrapper:
    """Tests for fetch_protocols_wrapper function."""

    @pytest.mark.asyncio
    async def test_fetch_protocols_wrapper_success(self):
        """Test successful execution of fetch_protocols_wrapper."""
        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()

        with patch('app.scheduler.AsyncSessionLocal') as mock_session_local:
            mock_session_local.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_local.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch('app.scheduler.fetch_protocols_job', new_callable=AsyncMock) as mock_job:
                await fetch_protocols_wrapper()

                mock_job.assert_called_once_with(mock_session)
                mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_protocols_wrapper_rollback_on_error(self):
        """Test that fetch_protocols_wrapper rolls back on error."""
        mock_session = AsyncMock()
        mock_session.rollback = AsyncMock()

        with patch('app.scheduler.AsyncSessionLocal') as mock_session_local:
            mock_session_local.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_local.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch('app.scheduler.fetch_protocols_job', new_callable=AsyncMock) as mock_job:
                mock_job.side_effect = Exception("Test error")

                with pytest.raises(Exception, match="Test error"):
                    await fetch_protocols_wrapper()

                mock_session.rollback.assert_called_once()


class TestProcessProtocolsWrapper:
    """Tests for process_protocols_wrapper function."""

    @pytest.mark.asyncio
    async def test_process_protocols_wrapper_success(self):
        """Test successful execution of process_protocols_wrapper."""
        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()

        with patch('app.scheduler.AsyncSessionLocal') as mock_session_local:
            mock_session_local.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_local.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch('app.scheduler.process_protocols_job', new_callable=AsyncMock) as mock_job:
                await process_protocols_wrapper()

                mock_job.assert_called_once_with(mock_session)
                mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_protocols_wrapper_rollback_on_error(self):
        """Test that process_protocols_wrapper rolls back on error."""
        mock_session = AsyncMock()
        mock_session.rollback = AsyncMock()

        with patch('app.scheduler.AsyncSessionLocal') as mock_session_local:
            mock_session_local.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_local.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch('app.scheduler.process_protocols_job', new_callable=AsyncMock) as mock_job:
                mock_job.side_effect = Exception("Test error")

                with pytest.raises(Exception, match="Test error"):
                    await process_protocols_wrapper()

                mock_session.rollback.assert_called_once()


class TestSetupScheduler:
    """Tests for setup_scheduler function."""

    def test_setup_scheduler_returns_scheduler(self):
        """Test that setup_scheduler returns a scheduler instance."""
        with patch('app.scheduler.scheduler') as mock_scheduler:
            mock_scheduler.get_jobs.return_value = []
            result = setup_scheduler()
            assert result == mock_scheduler

    def test_setup_scheduler_adds_fetch_job(self):
        """Test that setup_scheduler adds the fetch_protocols job."""
        with patch('app.scheduler.scheduler') as mock_scheduler:
            mock_scheduler.get_jobs.return_value = []
            setup_scheduler()

            calls = mock_scheduler.add_job.call_args_list
            fetch_job_added = any(
                call[0][0].__name__ == 'fetch_protocols_wrapper'
                for call in calls
            )
            assert fetch_job_added, "fetch_protocols_wrapper job should be added"

    def test_setup_scheduler_adds_process_job(self):
        """Test that setup_scheduler adds the process_protocols job."""
        with patch('app.scheduler.scheduler') as mock_scheduler:
            mock_scheduler.get_jobs.return_value = []
            setup_scheduler()

            calls = mock_scheduler.add_job.call_args_list
            process_job_added = any(
                call[0][0].__name__ == 'process_protocols_wrapper'
                for call in calls
            )
            assert process_job_added, "process_protocols_wrapper job should be added"

    def test_setup_scheduler_uses_cron_trigger(self):
        """Test that jobs are configured with CronTrigger."""
        with patch('app.scheduler.scheduler') as mock_scheduler:
            mock_scheduler.get_jobs.return_value = []
            setup_scheduler()

            calls = mock_scheduler.add_job.call_args_list
            for call in calls:
                assert isinstance(call.kwargs.get('trigger'), CronTrigger)


class TestStartScheduler:
    """Tests for start_scheduler function."""

    def test_start_scheduler_when_not_running(self):
        """Test starting scheduler when it's not running."""
        with patch('app.scheduler.scheduler') as mock_scheduler:
            mock_scheduler.running = False
            start_scheduler()
            mock_scheduler.start.assert_called_once()

    def test_start_scheduler_when_already_running(self):
        """Test starting scheduler when it's already running."""
        with patch('app.scheduler.scheduler') as mock_scheduler:
            mock_scheduler.running = True
            start_scheduler()
            mock_scheduler.start.assert_not_called()


class TestStopScheduler:
    """Tests for stop_scheduler function."""

    def test_stop_scheduler_when_running(self):
        """Test stopping scheduler when it's running."""
        with patch('app.scheduler.scheduler') as mock_scheduler:
            mock_scheduler.running = True
            stop_scheduler()
            mock_scheduler.shutdown.assert_called_once()

    def test_stop_scheduler_when_not_running(self):
        """Test stopping scheduler when it's not running."""
        with patch('app.scheduler.scheduler') as mock_scheduler:
            mock_scheduler.running = False
            stop_scheduler()
            mock_scheduler.shutdown.assert_not_called()


class TestSchedulerGlobalInstance:
    """Tests for the global scheduler instance."""

    def test_scheduler_is_async_io_scheduler(self):
        """Test that the global scheduler is an AsyncIOScheduler."""
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        assert isinstance(scheduler, AsyncIOScheduler)
