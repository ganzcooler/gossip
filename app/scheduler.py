from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import logging

from sqlalchemy import select

from app.core.config import ARTICLES_DIR
from app.database import AsyncSessionLocal
from app.models import EditorialPlan, Protocol
from app.services.llm_client import LLMAuthenticationError, OpenRouterLLMClient
from app.services.post_pipeline import PostPipeline
from app.services.protocol_fetcher import fetch_protocols_job

logger = logging.getLogger(__name__)

# Global scheduler instance
scheduler = AsyncIOScheduler(timezone="Europe/Berlin")


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


async def _unprocessed_protocol_ids(session) -> list[int]:
    result = await session.execute(
        select(Protocol.id)
        .where(Protocol.processed.is_not(True))
        .order_by(Protocol.session_date, Protocol.id)
    )
    return list(result.scalars().all())


async def _editorial_plan_status(session, protocol_id: int) -> str | None:
    result = await session.execute(
        select(EditorialPlan.status).where(
            EditorialPlan.protocol_id == protocol_id
        )
    )
    return result.scalar_one_or_none()


async def process_protocols_wrapper():
    """Process unprocessed protocols through the stateless post pipeline.

    Each protocol runs in its own fresh session and is committed on its own.
    A failed editorial plan is skipped so the scheduler never enters an
    automatic replan loop; a manual reprocess handles those protocols. Failed
    posts are terminal and are never retried automatically. Authentication and
    account errors stop the whole job immediately, while any other
    per-protocol error is logged and the remaining protocols still run.
    """
    async with AsyncSessionLocal() as session:
        protocol_ids = await _unprocessed_protocol_ids(session)

    for protocol_id in protocol_ids:
        outcome = await _process_protocol(protocol_id)
        if outcome == "auth":
            return


async def _process_protocol(protocol_id: int) -> str:
    """Process one protocol in a fresh session. Returns ok/skip/error/auth."""
    async with AsyncSessionLocal() as session:
        if await _editorial_plan_status(session, protocol_id) == "failed":
            logger.info(
                "Skipping protocol %s: editorial plan failed; "
                "a manual reprocess is required",
                protocol_id,
            )
            return "skip"

        protocol = await session.get(Protocol, protocol_id)
        if protocol is None:
            return "skip"

        try:
            pipeline = PostPipeline(OpenRouterLLMClient(), ARTICLES_DIR)
            await pipeline.run(protocol, session)
            await session.commit()
        except LLMAuthenticationError as exc:
            await session.rollback()
            logger.error(
                "Post pipeline stopped on an authentication/account "
                "error at protocol %s: %s",
                protocol_id,
                exc,
            )
            return "auth"
        except Exception:
            await session.rollback()
            logger.exception(
                "Post pipeline failed for protocol %s; continuing with "
                "the remaining protocols",
                protocol_id,
            )
            return "error"
        return "ok"


def setup_scheduler():
    """Configure and setup the APScheduler."""
    # Job 1: Fetch protocols (10:00 & 17:00)
    scheduler.add_job(
        fetch_protocols_wrapper,
        trigger=CronTrigger(hour="10,17", minute="0", timezone="Europe/Berlin"),
        id="fetch_protocols",
        name="Fetch Protocols from SessionNet",
        replace_existing=True
    )

    # Job 2: Process protocols (10:30 & 17:30)
    # Failed plans are skipped (manual reprocess), failed posts are never
    # retried automatically, and authentication errors stop the job.
    scheduler.add_job(
        process_protocols_wrapper,
        trigger=CronTrigger(hour="10,17", minute="30", timezone="Europe/Berlin"),
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