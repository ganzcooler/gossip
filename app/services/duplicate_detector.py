from difflib import SequenceMatcher
from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Protocol
import logging

logger = logging.getLogger(__name__)


async def check_duplicate(new_pdf_text: str, db_session: AsyncSession) -> bool:
    """
    Check if a similar protocol exists in the last 3 months.
    Returns True if duplicate detected (similarity >= 95%).
    """
    three_months_ago = datetime.now() - timedelta(days=90)

    result = await db_session.execute(
        select(Protocol).where(Protocol.created_at >= three_months_ago)
    )
    recent_protocols = result.scalars().all()

    for protocol in recent_protocols:
        similarity = SequenceMatcher(
            None,
            new_pdf_text,
            protocol.pdf_text
        ).ratio()

        if similarity >= 0.95:
            logger.warning(f"Duplicate detected (similarity: {similarity:.2%})")
            return True

    logger.info(f"No duplicate detected (checked {len(recent_protocols)} protocols)")
    return False