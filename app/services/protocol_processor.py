import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models import Protocol, Article
from app.config import ARTICLES_DIR, GENERATED_IMAGES_DIR, INSTA_IMAGES_DIR
from app.utils.folder_utils import create_protocol_folder

logger = logging.getLogger(__name__)


async def process_protocols_job(db_session: AsyncSession):
    """Job to process unprocessed protocols."""
    logger.info("Starting protocol processing job")

    # Get all unprocessed protocols
    result = await db_session.execute(
        select(Protocol).where(Protocol.processed == False)
    )
    unprocessed = result.scalars().all()

    processed_count = 0
    for protocol in unprocessed:
        try:
            await process_protocol(protocol, db_session)
            processed_count += 1
        except Exception as e:
            logger.error(f"Error processing protocol {protocol.id}: {e}")
            continue

    logger.info(f"Protocol processing job completed. Processed {processed_count} protocols")
    return processed_count


async def process_protocol(protocol: Protocol, db_session: AsyncSession):
    """Process a single protocol - generate articles, images, etc."""
    logger.info(f"Processing protocol: {protocol.title}")

    # Create folder for this protocol
    protocol_folder = create_protocol_folder(
        ARTICLES_DIR,
        protocol.session_date,
        protocol.title
    )

    # TODO: Integrate existing pipeline logic here
    # This would call the existing pipeline functions from src/
    # For now, this is a placeholder that creates a basic article

    # Generate article content using existing pipeline
    article_content = await generate_article_content(protocol)

    # Save article to database
    article = Article(
        protocol_id=protocol.id,
        article_index=1,
        content=article_content
    )
    db_session.add(article)

    # Mark protocol as processed
    protocol.processed = True
    await db_session.commit()

    logger.info(f"Successfully processed protocol: {protocol.title}")


async def generate_article_content(protocol: Protocol) -> str:
    """
    Generate article content from protocol.
    This integrates with the existing pipeline logic.
    """
    # TODO: Integrate with src/pipeline.py and src/pipeline_steps/
    # For now, return a placeholder

    # Import existing pipeline functions
    try:
        from src.pipeline_steps.generate_articles import generate_articles
        from src.pipeline_steps.generate_image_prompt import generate_image_prompt
        from src.pipeline_steps.generate_image import generate_image
        from src.pipeline_steps.generate_insta_caption import generate_insta_caption

        # This would need to be adapted to work with the new async structure
        # and database models
        logger.info(f"Would generate article for: {protocol.title}")

    except ImportError as e:
        logger.warning(f"Could not import pipeline modules: {e}")

    return f"Article generated for: {protocol.title}\n\n{protocol.pdf_text[:500]}..."