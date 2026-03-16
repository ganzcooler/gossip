from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import logging

from app.database import AsyncSessionLocal
from app.services.protocol_fetcher import fetch_protocols_job
from app.services.protocol_processor import process_protocols_job

logger = logging.getLogger(__name__)

# Global scheduler instance
scheduler = AsyncIOScheduler()


async def fetch_protocols_wrapper():
    """Wrapper to provide database session for fetch job."""
    async with AsyncSessionLocal() as session:
        try:
            await fetch_protocols_job(session)
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error(f"Fetch protocols job failed: {e}")
            raise


async def process_protocols_wrapper():
    """Wrapper to provide database session for process job."""
    async with AsyncSessionLocal() as session:
        try:
            await process_protocols_job(session)
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error(f"Process protocols job failed: {e}")
            raise


def setup_scheduler():
    """Configure and setup the APScheduler."""
    # Job 1: Fetch protocols (10:00 & 17:00)
    scheduler.add_job(
        fetch_protocols_wrapper,
        trigger=CronTrigger(hour="10,17", minute="0"),
        id="fetch_protocols",
        name="Fetch Protocols from SessionNet",
        replace_existing=True
    )

    # Job 2: Process protocols (10:30 & 17:30)
    scheduler.add_job(
        process_protocols_wrapper,
        trigger=CronTrigger(hour="10,17", minute="30"),
        id="process_protocols",
        name="Process Unprocessed Protocols",
        replace_existing=True
    )

    logger.debug("Scheduler configured with jobs:")
    for job in scheduler.get_jobs():
        logger.debug(f"  - {job.name}: {job.trigger}")

    return scheduler


def start_scheduler():
    """Start the scheduler."""
    if not scheduler.running:
        scheduler.start()
        logger.debug("Scheduler started")


def stop_scheduler():
    """Stop the scheduler."""
    if scheduler.running:
        scheduler.shutdown()
        logger.debug("Scheduler stopped")