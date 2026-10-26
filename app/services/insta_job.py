import logging
from pathlib import Path
from sqlalchemy import select
from app.core.config import ARTICLES_DIR
from app.models import Protocol, Article
from app.services.protocol_processor import create_insta_images_for_protocol_async
from app.utils.folder_utils import normalize_for_folder_name

logger = logging.getLogger(__name__)


def _get_protocol_folder(protocol: Protocol) -> Path:
    """
    Reconstruct the protocol folder path from protocol data.
    Uses shared normalization utility for consistency.
    """
    normalized = normalize_for_folder_name(protocol.title)
    folder_name = f"{protocol.session_date.strftime('%y%m%d')}_{normalized}"
    return ARTICLES_DIR / folder_name


def _check_protocol_folder_exists(protocol_folder: Path) -> bool:
    """Check if protocol folder exists."""
    return protocol_folder.exists()


def _check_source_images_exist(protocol_folder: Path) -> bool:
    """Check if at least one image_*.jpg or image_*.png exists."""
    existing_images = list(protocol_folder.glob("image_*.jpg")) + list(protocol_folder.glob("image_*.png"))
    return len(existing_images) > 0


def _check_articles_with_content_exist(articles: list[Article]) -> bool:
    """Check if articles with content exist in database."""
    if not articles:
        return False
    return any(article.content for article in articles)


async def generate_insta_images_job(db_session, protocol_id=None):
    """
    Job to generate Instagram images for protocols.
    
    Args:
        db_session: SQLAlchemy async session
        protocol_id: Optional specific protocol ID to process. If None, processes all
                     protocols where processed=True and have articles.
    
    Returns:
        dict with status, processed count, failed count, and per-protocol details
    """
    logger.info(f"Starting Instagram image generation job (protocol_id={protocol_id})")
    
    if protocol_id is not None:
        result = await db_session.execute(
            select(Protocol).where(Protocol.id == protocol_id)
        )
        protocols = result.scalars().all()
    else:
        result = await db_session.execute(
            select(Protocol)
            .where(Protocol.processed.is_(True))
            .where(Protocol.articles.any())
        )
        protocols = result.scalars().all()
    
    processed_count = 0
    failed_count = 0
    details = []
    
    for protocol in protocols:
        protocol_detail = {
            "protocol_id": protocol.id,
            "title": protocol.title,
            "status": "failed",
            "reason": None
        }
        
        try:
            logger.debug(f"Processing protocol {protocol.id}: {protocol.title}")
            
            protocol_folder = _get_protocol_folder(protocol)
            logger.debug(f"Protocol {protocol.id}: folder path = {protocol_folder}")
            
            if not _check_protocol_folder_exists(protocol_folder):
                reason = "Protocol folder not found"
                logger.debug(f"Protocol {protocol.id}: {reason}")
                protocol_detail["reason"] = reason
                details.append(protocol_detail)
                failed_count += 1
                logger.debug(f"Protocol {protocol.id}: {reason}")
                continue
            
            if not _check_source_images_exist(protocol_folder):
                reason = "No source images found"
                logger.debug(f"Protocol {protocol.id}: {reason}")
                protocol_detail["reason"] = reason
                details.append(protocol_detail)
                failed_count += 1
                logger.debug(f"Protocol {protocol.id}: {reason}")
                continue
            
            result = await db_session.execute(
                select(Article)
                .where(Article.protocol_id == protocol.id)
                .order_by(Article.article_index)
            )
            articles = result.scalars().all()
            
            if not _check_articles_with_content_exist(articles):
                reason = "No articles in database"
                logger.debug(f"Protocol {protocol.id}: {reason}")
                protocol_detail["reason"] = reason
                details.append(protocol_detail)
                failed_count += 1
                logger.debug(f"Protocol {protocol.id}: {reason}")
                continue
            
            articles_data = [
                {
                    "index": article.article_index,
                    "content": article.content,
                    "title": article.content.split('</h1>')[0].replace('<h1>', ''),
                    "caption": article.caption
                }
                for article in articles
            ]
            logger.debug(f"Protocol {protocol.id}: Prepared {len(articles_data)} articles for generation")
            
            await create_insta_images_for_protocol_async(protocol_folder, articles_data, protocol.title)
            
            protocol_detail["status"] = "success"
            protocol_detail["reason"] = None
            details.append(protocol_detail)
            processed_count += 1
            logger.info(f"Protocol {protocol.id}: Instagram images generated successfully")
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Protocol {protocol.id}: Unexpected error: {error_msg}")
            protocol_detail["reason"] = error_msg
            details.append(protocol_detail)
            failed_count += 1
            continue
    
    if failed_count == 0:
        status = "success"
    elif processed_count > 0:
        status = "partial_success"
    else:
        status = "error"
    
    logger.info(
        f"Instagram image generation job completed. "
        f"Processed: {processed_count}, Failed: {failed_count}, Total: {len(protocols)}"
    )
    
    return {
        "status": status,
        "processed": processed_count,
        "failed": failed_count,
        "details": details
    }
