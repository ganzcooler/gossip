# Define exceptions first to avoid circular imports
class APIError(Exception):
    """Base class for API-related errors."""
    pass


class AuthenticationError(APIError):
    """Raised when API authentication fails (401/403).

    This error indicates an invalid or missing API key.
    It should NOT be retried - the entire job should stop immediately.
    """
    pass


class ArticleGenerationError(Exception):
    """Raised when article generation fails after all retries."""
    pass


# Import services after exception definitions
from app.services.protocol_fetcher import fetch_protocols_job
from app.services.protocol_processor import process_protocols_job
from app.services.duplicate_detector import check_duplicate

__all__ = [
    "fetch_protocols_job",
    "process_protocols_job",
    "check_duplicate",
    "APIError",
    "AuthenticationError",
    "ArticleGenerationError",
]