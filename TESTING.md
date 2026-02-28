# Testing Guide

This document describes how to run tests and check code coverage for the Gossip project.

## Overview

The project uses:
- **pytest** - Test framework
- **pytest-asyncio** - For async test support
- **pytest-cov** - Coverage plugin for pytest
- **coverage** - Code coverage measurement

## Running Tests

### Run all tests
```bash
python -m pytest tests/unit/
```

### Run with verbose output
```bash
python -m pytest tests/unit/ -v
```

### Run specific test file
```bash
python -m pytest tests/unit/test_core_models.py -v
```

### Run with coverage report
```bash
python -m pytest tests/unit/ --cov=app --cov-report=term-missing
```

### Generate HTML coverage report
```bash
python -m pytest tests/unit/ --cov=app --cov-report=html
```
The HTML report will be generated in `htmlcov/index.html`.

## Current Coverage Status

### Modules with 100% Coverage
- `app/core/models.py` - Pydantic models
- `app/core/tags.py` - Tag definitions
- `app/core/prompts.py` - Prompt templates
- `app/models.py` - SQLAlchemy models
- `app/utils/folder_utils.py` - Directory operations
- `app/utils/sessionnet.py` - SessionNet utilities
- `app/services/duplicate_detector.py` - Duplicate detection

### Modules with Partial Coverage
- `app/core/config.py` - 79% (environment variable loading tested)
- `app/services/protocol_fetcher.py` - 50% (HTML parsing tested, async functions need integration tests)
- `app/services/protocol_processor.py` - 46% (file operations tested, async orchestration needs integration tests)

### Modules Excluded from Coverage
The following modules are excluded as they require external dependencies (AI services, database, etc.):
- `app/main.py` - FastAPI application entry point
- `app/scheduler.py` - APScheduler jobs
- `app/database.py` - Database connection
- `app/logging_config.py` - Logging setup
- `app/services/article_generator.py` - AI article generation
- `app/services/image_generator.py` - AI image generation
- `app/services/caption_generator.py` - AI caption generation
- `app/services/insta_generator.py` - Image processing (partially tested)
- `app/api/routes.py` - API endpoints (needs FastAPI test client setup)

## Test Structure

```
tests/
├── __init__.py
├── conftest.py              # Shared fixtures
├── unit/
│   ├── __init__.py
│   ├── test_core_config.py
│   ├── test_core_models.py
│   ├── test_core_tags.py
│   ├── test_utils_sessionnet.py
│   ├── test_utils_folder_utils.py
│   ├── test_services_duplicate_detector.py
│   ├── test_services_protocol_fetcher.py
│   ├── test_services_protocol_processor.py
│   ├── test_insta_generator.py
│   └── test_api_routes.py   # (excluded - requires full app context)
└── integration/
    └── __init__.py
```

## Writing New Tests

### Basic Test Structure
```python
def test_something():
    """Test description."""
    result = function_to_test()
    assert result == expected_value
```

### Async Test
```python
import pytest

@pytest.mark.asyncio
async def test_async_function():
    """Test async function."""
    result = await async_function()
    assert result == expected_value
```

### Using Fixtures
```python
def test_with_fixture(mock_db_session):
    """Test using mock database session."""
    result = function_using_db(mock_db_session)
    assert result is not None
```

## Coverage Configuration

Coverage settings are in `.coveragerc`:
- Source directory: `app/`
- HTML report: `htmlcov/`
- XML report: `coverage.xml`
- Branch coverage: Enabled

## Continuous Integration

To run tests in CI/CD:
```bash
pip install -r requirements.txt
python -m pytest tests/unit/ --cov=app --cov-report=xml --cov-fail-under=50
```

This will fail if coverage drops below 50%.