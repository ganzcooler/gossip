"""Tests for scheduler module."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from apscheduler.triggers.cron import CronTrigger

from app.services.llm_client import LLMAuthenticationError
from app.scheduler import (
    _process_protocol,
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
    """Tests for the scheduled stateless post-pipeline job."""

    @staticmethod
    def _session_context(session):
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=session)
        context.__aexit__ = AsyncMock(return_value=False)
        return context

    @staticmethod
    def _ids_result(ids):
        result = MagicMock()
        result.scalars.return_value.all.return_value = list(ids)
        return result

    @staticmethod
    def _status_result(status):
        result = MagicMock()
        result.scalar_one_or_none.return_value = status
        return result

    @pytest.mark.asyncio
    async def test_wrapper_processes_ids_and_stops_on_auth(self):
        session = AsyncMock()
        session.execute.return_value = self._ids_result([1, 2, 3])

        with patch('app.scheduler.AsyncSessionLocal') as session_local:
            session_local.return_value = self._session_context(session)
            with patch(
                'app.scheduler._process_protocol', new_callable=AsyncMock
            ) as process:
                process.side_effect = ["ok", "auth", "ok"]

                await process_protocols_wrapper()

        assert [call.args[0] for call in process.await_args_list] == [1, 2]

    @pytest.mark.asyncio
    async def test_wrapper_continues_after_non_auth_errors(self):
        session = AsyncMock()
        session.execute.return_value = self._ids_result([1, 2])

        with patch('app.scheduler.AsyncSessionLocal') as session_local:
            session_local.return_value = self._session_context(session)
            with patch(
                'app.scheduler._process_protocol', new_callable=AsyncMock
            ) as process:
                process.side_effect = ["error", "ok"]

                await process_protocols_wrapper()

        assert [call.args[0] for call in process.await_args_list] == [1, 2]

    @pytest.mark.asyncio
    async def test_process_protocol_skips_a_failed_plan(self):
        session = AsyncMock()
        session.execute.return_value = self._status_result("failed")

        with patch('app.scheduler.AsyncSessionLocal') as session_local:
            session_local.return_value = self._session_context(session)
            with patch('app.scheduler.PostPipeline') as pipeline_cls:
                outcome = await _process_protocol(1)

        assert outcome == "skip"
        pipeline_cls.assert_not_called()
        session.get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_process_protocol_runs_and_commits_in_a_fresh_session(self):
        session = AsyncMock()
        session.execute.return_value = self._status_result(None)
        protocol = MagicMock(id=1)
        session.get.return_value = protocol

        with patch('app.scheduler.AsyncSessionLocal') as session_local:
            session_local.return_value = self._session_context(session)
            with patch('app.scheduler.OpenRouterLLMClient'):
                with patch('app.scheduler.PostPipeline') as pipeline_cls:
                    run = AsyncMock()
                    pipeline_cls.return_value.run = run

                    outcome = await _process_protocol(1)

        assert outcome == "ok"
        run.assert_awaited_once_with(protocol, session)
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_process_protocol_returns_auth_and_rolls_back(self):
        session = AsyncMock()
        session.execute.return_value = self._status_result(None)
        session.get.return_value = MagicMock(id=1)

        with patch('app.scheduler.AsyncSessionLocal') as session_local:
            session_local.return_value = self._session_context(session)
            with patch('app.scheduler.OpenRouterLLMClient'):
                with patch('app.scheduler.PostPipeline') as pipeline_cls:
                    pipeline_cls.return_value.run = AsyncMock(
                        side_effect=LLMAuthenticationError("no credits")
                    )

                    outcome = await _process_protocol(1)

        assert outcome == "auth"
        session.rollback.assert_awaited_once()
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_process_protocol_returns_error_and_rolls_back(self):
        session = AsyncMock()
        session.execute.return_value = self._status_result(None)
        session.get.return_value = MagicMock(id=1)

        with patch('app.scheduler.AsyncSessionLocal') as session_local:
            session_local.return_value = self._session_context(session)
            with patch('app.scheduler.OpenRouterLLMClient'):
                with patch('app.scheduler.PostPipeline') as pipeline_cls:
                    pipeline_cls.return_value.run = AsyncMock(
                        side_effect=RuntimeError("boom")
                    )

                    outcome = await _process_protocol(1)

        assert outcome == "error"
        session.rollback.assert_awaited_once()
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_unprocessed_protocols_does_not_process_anything(self):
        session = AsyncMock()
        session.execute.return_value = self._ids_result([])

        with patch('app.scheduler.AsyncSessionLocal') as session_local:
            session_local.return_value = self._session_context(session)
            with patch(
                'app.scheduler._process_protocol', new_callable=AsyncMock
            ) as process:
                await process_protocols_wrapper()

        process.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_process_protocols_wrapper_no_longer_references_old_processor(self):
        """The old processor job must be gone from the scheduler module."""
        import app.scheduler as scheduler_module

        assert not hasattr(scheduler_module, "process_protocols_job")


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
