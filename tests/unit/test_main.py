"""Tests for main module."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI

from app.main import (
    lifespan,
    app
)


class TestLifespan:
    """Tests for lifespan context manager."""

    @pytest.mark.asyncio
    async def test_lifespan_initializes_database(self):
        """Test that lifespan initializes the database on startup."""
        mock_app = MagicMock(spec=FastAPI)

        with patch('app.main.ensure_directories') as mock_ensure_dirs:
            with patch('app.main.init_db', new_callable=AsyncMock) as mock_init_db:
                with patch('app.main.setup_scheduler') as mock_setup_scheduler:
                    with patch('app.main.start_scheduler') as mock_start_scheduler:
                        with patch('app.main.stop_scheduler') as mock_stop_scheduler:
                            async with lifespan(mock_app):
                                pass

                            mock_init_db.assert_called_once()

    @pytest.mark.asyncio
    async def test_lifespan_creates_directories(self):
        """Test that lifespan creates necessary directories."""
        mock_app = MagicMock(spec=FastAPI)

        with patch('app.main.ensure_directories') as mock_ensure_dirs:
            with patch('app.main.init_db', new_callable=AsyncMock):
                with patch('app.main.setup_scheduler'):
                    with patch('app.main.start_scheduler'):
                        with patch('app.main.stop_scheduler'):
                            async with lifespan(mock_app):
                                pass

                            mock_ensure_dirs.assert_called_once()

    @pytest.mark.asyncio
    async def test_lifespan_starts_scheduler(self):
        """Test that lifespan starts the scheduler."""
        mock_app = MagicMock(spec=FastAPI)

        with patch('app.main.ensure_directories'):
            with patch('app.main.init_db', new_callable=AsyncMock):
                with patch('app.main.setup_scheduler') as mock_setup_scheduler:
                    with patch('app.main.start_scheduler') as mock_start_scheduler:
                        with patch('app.main.stop_scheduler') as mock_stop_scheduler:
                            async with lifespan(mock_app):
                                pass

                            mock_setup_scheduler.assert_called_once()
                            mock_start_scheduler.assert_called_once()

    @pytest.mark.asyncio
    async def test_lifespan_stops_scheduler_on_shutdown(self):
        """Test that lifespan stops the scheduler on shutdown."""
        mock_app = MagicMock(spec=FastAPI)

        with patch('app.main.ensure_directories'):
            with patch('app.main.init_db', new_callable=AsyncMock):
                with patch('app.main.setup_scheduler'):
                    with patch('app.main.start_scheduler'):
                        with patch('app.main.stop_scheduler') as mock_stop_scheduler:
                            async with lifespan(mock_app):
                                pass

                            mock_stop_scheduler.assert_called_once()


class TestFastAPIApp:
    """Tests for the FastAPI application instance."""

    def test_app_is_fastapi_instance(self):
        """Test that app is a FastAPI instance."""
        assert isinstance(app, FastAPI)

    def test_app_has_correct_title(self):
        """Test that app has the correct title."""
        assert app.title == "Gossip"

    def test_app_has_api_routes(self):
        """Test that app includes API routes."""
        routes = [route.path for route in app.routes]
        assert any('/api' in route for route in routes) or any('/health' in route for route in routes)

    def test_app_has_lifespan(self):
        """Test that app has lifespan configured."""
        assert app.router.lifespan_context is not None
