from contextlib import asynccontextmanager
from fastapi import FastAPI
import logging

from app.database import init_db
from app.logging_config import setup_logging
from app.scheduler import setup_scheduler, start_scheduler, stop_scheduler
from app.api.routes import router
from app.utils.folder_utils import ensure_directories
from app.core.config import ARTICLES_DIR, LOGS_DIR

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    logger.debug("Starting up Gossip application...")

    # Ensure directories exist
    ensure_directories([
        ARTICLES_DIR,
        LOGS_DIR
    ])

    # Initialize database
    logger.debug("Initializing database...")
    await init_db()
    logger.debug("Database initialized")

    # Setup and start scheduler
    setup_scheduler()
    start_scheduler()

    logger.debug("Gossip application started successfully")

    yield

    # Shutdown
    logger.debug("Shutting down Gossip application...")
    stop_scheduler()
    logger.debug("Gossip application stopped")


# Create FastAPI application
app = FastAPI(
    title="Gossip",
    description="Automated protocol processing and article generation",
    version="1.0.0",
    lifespan=lifespan
)

# Include API routes
app.include_router(router, prefix="/api")


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "Gossip API",
        "version": "1.0.0",
        "docs": "/docs"
    }