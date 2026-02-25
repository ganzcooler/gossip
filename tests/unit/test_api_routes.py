"""
Unit tests for app/api/routes.py
"""
import pytest
from datetime import datetime, date
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db


# Create test client
client = TestClient(app)


class TestHealthCheck:
    """Tests for health check endpoint."""

    def test_health_check_returns_healthy(self):
        """Test that health check returns healthy status."""
        response = client.get("/api/health")
        
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}


class TestListProtocols:
    """Tests for list_protocols endpoint."""

    def test_list_protocols_returns_list(self):
        """Test that protocols are returned as a list."""
        mock_protocols = [
            MagicMock(
                id=1,
                session_date=date(2024, 1, 15),
                title="Test Protocol 1",
                getfile_id=12345,
                processed=False,
                created_at=datetime(2024, 1, 15, 10, 0, 0)
            ),
            MagicMock(
                id=2,
                session_date=date(2024, 1, 20),
                title="Test Protocol 2",
                getfile_id=67890,
                processed=True,
                created_at=datetime(2024, 1, 20, 10, 0, 0)
            ),
        ]
        
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_protocols
        mock_session.execute.return_value = mock_result
        
        async def override_get_db():
            yield mock_session
        
        app.dependency_overrides[get_db] = override_get_db
        
        try:
            response = client.get("/api/protocols")
            
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
        finally:
            app.dependency_overrides.clear()

    def test_list_protocols_with_processed_filter(self):
        """Test filtering protocols by processed status."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result
        
        async def override_get_db():
            yield mock_session
        
        app.dependency_overrides[get_db] = override_get_db
        
        try:
            response = client.get("/api/protocols?processed=true")
            
            assert response.status_code == 200
        finally:
            app.dependency_overrides.clear()

    def test_list_protocols_with_pagination(self):
        """Test pagination parameters."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result
        
        async def override_get_db():
            yield mock_session
        
        app.dependency_overrides[get_db] = override_get_db
        
        try:
            response = client.get("/api/protocols?skip=10&limit=5")
            
            assert response.status_code == 200
        finally:
            app.dependency_overrides.clear()


class TestGetProtocol:
    """Tests for get_protocol endpoint."""

    def test_get_existing_protocol(self):
        """Test retrieving an existing protocol."""
        mock_protocol = MagicMock(
            id=1,
            session_date=date(2024, 1, 15),
            title="Test Protocol",
            getfile_id=12345,
            pdf_text="PDF content",
            processed=False,
            created_at=datetime(2024, 1, 15, 10, 0, 0)
        )
        
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_protocol
        mock_session.execute.return_value = mock_result
        
        async def override_get_db():
            yield mock_session
        
        app.dependency_overrides[get_db] = override_get_db
        
        try:
            response = client.get("/api/protocols/1")
            
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == 1
            assert data["title"] == "Test Protocol"
        finally:
            app.dependency_overrides.clear()

    def test_get_nonexistent_protocol(self):
        """Test retrieving a non-existent protocol returns 404."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result
        
        async def override_get_db():
            yield mock_session
        
        app.dependency_overrides[get_db] = override_get_db
        
        try:
            response = client.get("/api/protocols/999")
            
            assert response.status_code == 404
            assert "not found" in response.json()["detail"].lower()
        finally:
            app.dependency_overrides.clear()


class TestGetProtocolArticles:
    """Tests for get_protocol_articles endpoint."""

    def test_get_articles_for_protocol(self):
        """Test retrieving articles for a protocol."""
        mock_articles = [
            MagicMock(
                id=1,
                article_index=1,
                content="<h1>Article 1</h1><p>Content</p>",
                created_at=datetime(2024, 1, 15, 10, 0, 0)
            ),
            MagicMock(
                id=2,
                article_index=2,
                content="<h1>Article 2</h1><p>Content</p>",
                created_at=datetime(2024, 1, 15, 10, 0, 0)
            ),
        ]
        
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_articles
        mock_session.execute.return_value = mock_result
        
        async def override_get_db():
            yield mock_session
        
        app.dependency_overrides[get_db] = override_get_db
        
        try:
            response = client.get("/api/protocols/1/articles")
            
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            assert len(data) == 2
        finally:
            app.dependency_overrides.clear()

    def test_get_articles_for_protocol_no_articles(self):
        """Test retrieving articles when none exist."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result
        
        async def override_get_db():
            yield mock_session
        
        app.dependency_overrides[get_db] = override_get_db
        
        try:
            response = client.get("/api/protocols/1/articles")
            
            assert response.status_code == 200
            data = response.json()
            assert data == []
        finally:
            app.dependency_overrides.clear()


class TestGetStats:
    """Tests for get_stats endpoint."""

    def test_get_stats_returns_statistics(self):
        """Test that stats endpoint returns system statistics."""
        mock_session = AsyncMock()
        
        # Mock counts
        mock_total = MagicMock()
        mock_total.scalar.return_value = 10
        
        mock_processed = MagicMock()
        mock_processed.scalar.return_value = 7
        
        mock_articles = MagicMock()
        mock_articles.scalar.return_value = 15
        
        mock_session.execute.side_effect = [mock_total, mock_processed, mock_articles]
        
        async def override_get_db():
            yield mock_session
        
        app.dependency_overrides[get_db] = override_get_db
        
        try:
            response = client.get("/api/stats")
            
            assert response.status_code == 200
            data = response.json()
            assert "total_protocols" in data
            assert "processed_protocols" in data
            assert "unprocessed_protocols" in data
            assert "total_articles" in data
        finally:
            app.dependency_overrides.clear()


class TestPipelineEndpoints:
    """Tests for pipeline trigger endpoints."""

    @patch('app.api.routes.fetch_protocols_job')
    def test_trigger_fetch_protocols(self, mock_fetch):
        """Test triggering protocol fetch."""
        mock_fetch.return_value = 5
        mock_session = AsyncMock()
        
        async def override_get_db():
            yield mock_session
        
        app.dependency_overrides[get_db] = override_get_db
        
        try:
            response = client.post("/api/pipeline/fetch")
            
            # Should return 200 OK
            assert response.status_code == 200
        finally:
            app.dependency_overrides.clear()

    @patch('app.api.routes.process_protocols_job')
    def test_trigger_process_protocols(self, mock_process):
        """Test triggering protocol processing."""
        mock_process.return_value = 3
        mock_session = AsyncMock()
        
        async def override_get_db():
            yield mock_session
        
        app.dependency_overrides[get_db] = override_get_db
        
        try:
            response = client.post("/api/pipeline/process")
            
            # Should return 200 OK
            assert response.status_code == 200
        finally:
            app.dependency_overrides.clear()

    def test_get_pipeline_status(self):
        """Test getting pipeline status."""
        mock_session = AsyncMock()
        
        mock_total = MagicMock()
        mock_total.scalar.return_value = 10
        
        mock_unprocessed = MagicMock()
        mock_unprocessed.scalar.return_value = 3
        
        mock_articles = MagicMock()
        mock_articles.scalar.return_value = 15
        
        mock_session.execute.side_effect = [mock_total, mock_unprocessed, mock_articles]
        
        async def override_get_db():
            yield mock_session
        
        app.dependency_overrides[get_db] = override_get_db
        
        try:
            response = client.get("/api/pipeline/status")
            
            assert response.status_code == 200
            data = response.json()
            assert "unprocessed_protocols" in data
            assert "total_protocols" in data
            assert "total_articles" in data
            assert "ready_to_process" in data
        finally:
            app.dependency_overrides.clear()
