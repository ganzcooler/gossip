"""
Pytest configuration and shared fixtures.
"""
import os
import sys
from pathlib import Path

# Set up test directory paths BEFORE any app imports
# This ensures logging configuration works on Windows
project_root = Path(__file__).parent.parent
os.environ.setdefault("ARTICLES_DIR", str(project_root / "app/articles"))
os.environ.setdefault("LOGS_DIR", str(project_root / "app/logs"))

import pytest
from unittest.mock import MagicMock, AsyncMock

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def mock_env_vars(monkeypatch):
    """Fixture to set up mock environment variables."""
    # Get project root for test directories
    project_root = Path(__file__).parent.parent
    env_vars = {
        "GOOGLE_API_KEY": "test-api-key",
        "DB_HOST": "localhost",
        "DB_PORT": "5432",
        "DB_NAME": "test_db",
        "DB_USER": "test_user",
        "DB_PASSWORD": "test_password",
        "DATABASE_URL": "postgresql+asyncpg://test_user:test_password@localhost:5432/test_db",
        "SESSIONNET_BASE_URL": "https://test.sessionnet.example/",
        "TRAEFIK_HOST": "test.localhost",
        "LOG_LEVEL": "DEBUG",
        "ARTICLES_DIR": str(project_root / "app/articles"),
        "LOGS_DIR": str(project_root / "app/logs"),
    }
    for key, value in env_vars.items():
        monkeypatch.setenv(key, value)
    return env_vars


@pytest.fixture
def mock_async_session():
    """Fixture to create a mock async database session."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


@pytest.fixture
def temp_directory(tmp_path):
    """Fixture to provide a temporary directory for tests."""
    return tmp_path


@pytest.fixture
def sample_protocol_data():
    """Fixture to provide sample protocol data."""
    return {
        "session_date": "2024-01-15",
        "title": "Test Protocol Title",
        "getfile_id": 12345,
        "pdf_url": "https://test.sessionnet.example/getfile.asp?id=12345",
        "pdf_text": "This is a sample PDF text content for testing purposes.",
    }


@pytest.fixture
def sample_article_data():
    """Fixture to provide sample article data."""
    return {
        "ueberschrift": "Test Article Headline",
        "inhalt": "<p>This is the article content.</p><h2>Section</h2><p>More content.</p>",
    }


@pytest.fixture
def sample_html_content():
    """Fixture to provide sample HTML content for parsing tests."""
    return """
    <html>
    <body>
        <table>
            <tr class="zl11">
                <td>15.01.2024</td>
                <td>Time</td>
                <td>Test Protocol Title</td>
                <td><a href="getfile.asp?id=12345">PDF</a></td>
            </tr>
            <tr class="zl12">
                <td>20.01.2024</td>
                <td>Time</td>
                <td>Another Protocol</td>
                <td><a href="getfile.asp?id=67890">PDF</a></td>
            </tr>
        </table>
    </body>
    </html>
    """


@pytest.fixture
def mock_db_session():
    """Fixture to create a mock async database session for tests."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.close = AsyncMock()
    return session