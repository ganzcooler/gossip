import asyncio
import logging
import re
from datetime import date
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import Protocol, Article
from app.core.config import ARTICLES_DIR
from app.core.models import SingleArticle
from app.utils.folder_utils import create_protocol_folder
from app.services.article_generator import generate_articles
from app.services import ArticleGenerationError
from app.services.image_generator import generate_image_for_article
from app.services.caption_generator import generate_insta_caption
from app.services.insta_generator import create_insta_images_for_protocol
from app.services import AuthenticationError

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
        except AuthenticationError as e:
            # Authentication errors should stop the entire job immediately
            logger.critical(f"Authentication error while processing protocol {protocol.id}: {e}")
            logger.critical("Stopping protocol processing job due to authentication failure")
            raise  # Re-raise to stop the job
        except Exception as e:
            logger.error(f"Error processing protocol {protocol.id}: {e}")
            continue

    logger.info(f"Protocol processing job completed. Processed {processed_count} protocols")
    return processed_count


async def process_protocol(protocol: Protocol, db_session: AsyncSession):
    """
    Process a single protocol - generate articles, images, and Instagram content.
    """
    logger.debug(f"Processing protocol: {protocol.title} (ID: {protocol.id})")

    # Step 1: Generate articles from PDF text (sync function in thread pool)
    logger.debug(f"Generating articles for protocol {protocol.id}...")
    loop = asyncio.get_event_loop()
    
    try:
        articles = await loop.run_in_executor(None, generate_articles, protocol.pdf_text)
    except ArticleGenerationError as e:
        # Serious error (API failure) - do NOT mark as processed so it can be retried later
        logger.error(f"Article generation failed for protocol {protocol.id}: {e}")
        raise

    if not articles:
        logger.warning(f"No articles generated for protocol {protocol.id} (API returned empty result)")
        # Mark as processed anyway to avoid infinite retries for empty but valid responses
        protocol.processed = True
        await db_session.commit()
        return

    logger.debug(f"Generated {len(articles)} articles for protocol {protocol.id}")

    # Step 2: Process each article
    protocol_folder = None  # Will be set lazily when first article is saved
    for index, article_data in enumerate(articles, start=1):
        try:
            protocol_folder = await process_single_article(
                protocol=protocol,
                article_data=article_data,
                article_index=index,
                protocol_folder=protocol_folder,
                db_session=db_session
            )
        except Exception as e:
            logger.error(f"Error processing article {index} for protocol {protocol.id}: {e}")
            continue

    # Step 3: Create Instagram images for all articles in this protocol
    # Only if we have a valid protocol_folder (at least one image was generated)
    if protocol_folder is not None and protocol_folder.exists():
        try:
            # Build articles_data from the generated articles
            articles_data = [
                {
                    "index": idx,
                    "content": f"<h1>{article.ueberschrift}</h1>\n{article.inhalt}",
                    "title": article.ueberschrift
                }
                for idx, article in enumerate(articles, start=1)
            ]
            await create_insta_images_for_protocol_async(protocol_folder, articles_data, protocol.title)
        except Exception as e:
            logger.error(f"Error creating Instagram images for protocol {protocol.id}: {e}")
    else:
        logger.warning(f"No protocol folder available for Instagram generation (protocol {protocol.id})")

    # Mark protocol as processed
    protocol.processed = True
    await db_session.commit()

    logger.debug(f"Successfully processed protocol: {protocol.title}")


async def process_single_article(
    protocol: Protocol,
    article_data: SingleArticle,
    article_index: int,
    protocol_folder: Path | None,
    db_session: AsyncSession
) -> Path | None:
    """
    Process a single article: save HTML, generate image, create Instagram content.
    Returns the protocol_folder path (created if needed).
    """
    logger.debug(f"Processing article {article_index}: {article_data.ueberschrift}")

    # Step 2a: Save article to database
    article_content = f"<h1>{article_data.ueberschrift}</h1>\n{article_data.inhalt}"
    article_record = Article(
        protocol_id=protocol.id,
        article_index=article_index,
        content=article_content
    )
    db_session.add(article_record)
    await db_session.flush()  # Get the ID without committing

    # Step 2b: Generate image prompt and image (sync functions in thread pool)
    logger.debug(f"Generating image for article {article_index}...")
    loop = asyncio.get_event_loop()
    prompt, image_bytes = await loop.run_in_executor(
        None, generate_image_for_article, article_data
    )

    if not image_bytes:
        logger.warning(f"No image generated for article {article_index}")
        return protocol_folder  # Return existing folder path to avoid recreating it

    # Step 2c: Save image (folder will be created lazily if needed)
    image_path = save_image_to_file(
        image_bytes,
        protocol_folder,
        article_index,
        protocol.session_date,
        protocol.title
    )
    protocol_folder = image_path.parent
    logger.debug(f"Saved image to: {image_path}")

    # Step 2d: Generate Instagram caption (sync function in thread pool)
    caption = await loop.run_in_executor(
        None, generate_insta_caption, article_data.ueberschrift, article_data.inhalt
    )

    # Save caption to database if generated successfully
    if caption:
        article_record.caption = caption
        logger.debug(f"Saved caption to database for article {article_index}")

    logger.debug(f"Successfully processed article {article_index}: {article_data.ueberschrift}")
    return protocol_folder


def save_image_to_file(
    image_bytes: bytes,
    protocol_folder: Path | None,
    article_index: int,
    session_date: date,
    title: str,
    suffix: str = ""
) -> Path:
    """
    Save an image as a PNG file in the protocol folder.
    Creates the folder lazily if it doesn't exist yet.
    Returns the path to the saved file.
    """
    # Lazily create the protocol folder if it doesn't exist
    if protocol_folder is None or not protocol_folder.exists():
        try:
            protocol_folder = create_protocol_folder(
                ARTICLES_DIR,
                session_date,
                title
            )
            logger.debug(f"Created protocol folder: {protocol_folder}")
        except FileExistsError:
            # Folder exists from a previous run - reuse it
            # Reconstruct the folder path using the same naming logic as create_protocol_folder
            normalized = title
            for umlaut, replacement in [('ä', 'ae'), ('ö', 'oe'), ('ü', 'ue'), ('ß', 'ss'), ('Ä', 'Ae'), ('Ö', 'Oe'), ('Ü', 'Ue')]:
                normalized = normalized.replace(umlaut, replacement)
            normalized = normalized.replace(' ', '_').lower()
            normalized = ''.join(c for c in normalized if c.isalnum() or c == '_')[:80]
            folder_name = f"{session_date.strftime('%y%m%d')}_{normalized}"
            protocol_folder = ARTICLES_DIR / folder_name
            logger.debug(f"Reusing existing protocol folder: {protocol_folder}")
        except OSError as e:
            # Handle other OS-level errors (permission denied, disk full, etc.)
            logger.error(f"Failed to create protocol folder for '{title}': {e}")
            raise

    filename = f"image_{article_index:02d}{suffix}.png"
    filepath = protocol_folder / filename

    try:
        with open(filepath, "wb") as f:
            f.write(image_bytes)
        logger.debug(f"Saved image to: {filepath}")
        return filepath
    except IOError as e:
        logger.error(f"Error saving image to {filepath}: {e}")
        raise


def sanitize_filename(name: str) -> str:
    """
    Sanitize a string to be safe for use in filenames.
    Replaces spaces with underscores and removes special characters.
    """
    # Replace spaces with underscores
    name = name.replace(" ", "_")
    # Remove special characters
    name = re.sub(r'[^\w\-_.]', '', name)
    # Remove multiple underscores
    name = re.sub(r'_+', '_', name)
    return name.strip("_.-")


async def create_insta_images_for_protocol_async(
    protocol_folder: Path,
    articles_data: list[dict],
    protocol_title: str
):
    """
    Async wrapper for creating Instagram images.
    This runs the synchronous insta image creation in a thread pool.
    """
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, create_insta_images_for_protocol, protocol_folder, articles_data, protocol_title
    )
