import logging
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import Protocol, Article
from app.config import ARTICLES_DIR, GENERATED_IMAGES_DIR, INSTA_IMAGES_DIR
from app.utils.folder_utils import create_protocol_folder
from app.services.pipeline_adapter import (
    generate_articles_async,
    generate_image_prompt_async,
    generate_image_async,
    generate_insta_caption_async,
    save_article_to_file,
    save_image_to_file,
    create_insta_images_for_protocol
)

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
    """
    Process a single protocol - generate articles, images, and Instagram content.
    This integrates the existing pipeline logic from src/.
    """
    logger.info(f"Processing protocol: {protocol.title} (ID: {protocol.id})")

    # Create folder for this protocol
    protocol_folder = create_protocol_folder(
        ARTICLES_DIR,
        protocol.session_date,
        protocol.title
    )
    logger.info(f"Created protocol folder: {protocol_folder}")

    # Step 1: Generate articles from PDF text
    logger.info(f"Generating articles for protocol {protocol.id}...")
    articles = await generate_articles_async(protocol.pdf_text)

    if not articles:
        logger.warning(f"No articles generated for protocol {protocol.id}")
        # Mark as processed anyway to avoid infinite retries
        protocol.processed = True
        await db_session.commit()
        return

    logger.info(f"Generated {len(articles)} articles for protocol {protocol.id}")

    # Step 2: Process each article
    for index, article_data in enumerate(articles, start=1):
        try:
            await process_single_article(
                protocol=protocol,
                article_data=article_data,
                article_index=index,
                protocol_folder=protocol_folder,
                db_session=db_session
            )
        except Exception as e:
            logger.error(f"Error processing article {index} for protocol {protocol.id}: {e}")
            continue

    # Mark protocol as processed
    protocol.processed = True
    await db_session.commit()

    logger.info(f"Successfully processed protocol: {protocol.title}")


async def process_single_article(
    protocol: Protocol,
    article_data,
    article_index: int,
    protocol_folder: Path,
    db_session: AsyncSession
):
    """
    Process a single article: save HTML, generate image, create Instagram content.
    """
    logger.info(f"Processing article {article_index}: {article_data.ueberschrift}")

    # Step 2a: Save article to file
    article_path = save_article_to_file(article_data, protocol_folder, article_index)

    # Step 2b: Save article to database
    article_content = f"<h1>{article_data.ueberschrift}</h1>\n{article_data.inhalt}"
    article_record = Article(
        protocol_id=protocol.id,
        article_index=article_index,
        content=article_content
    )
    db_session.add(article_record)
    await db_session.flush()  # Get the ID without committing

    # Step 2c: Generate image prompt
    logger.info(f"Generating image prompt for article {article_index}...")
    image_prompt = await generate_image_prompt_async(article_data)

    if not image_prompt:
        logger.warning(f"No image prompt generated for article {article_index}")
        return

    # Step 2d: Generate image
    logger.info(f"Generating image for article {article_index}...")
    image_bytes = await generate_image_async(image_prompt)

    if not image_bytes:
        logger.warning(f"No image generated for article {article_index}")
        return

    # Step 2e: Save image
    image_path = save_image_to_file(image_bytes, protocol_folder, article_index)
    logger.info(f"Saved image to: {image_path}")

    # Step 2f: Generate Instagram caption
    article_stem = article_path.stem
    await generate_insta_caption_async(article_content, article_stem, protocol_folder)

    logger.info(f"Successfully processed article {article_index}: {article_data.ueberschrift}")


async def create_insta_images_for_protocol_async(protocol_folder: Path):
    """
    Async wrapper for creating Instagram images.
    This runs the synchronous insta image creation in a thread pool.
    """
    import asyncio
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, create_insta_images_for_protocol, protocol_folder)