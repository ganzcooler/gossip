from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional

from app.database import get_db
from app.models import Protocol, Article
from app.services.protocol_fetcher import fetch_protocols_job
from app.services.protocol_processor import process_protocols_job
from app.services import generate_insta_images_job

router = APIRouter()


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@router.get("/protocols")
async def list_protocols(
    skip: int = 0,
    limit: int = 100,
    processed: bool = None,
    db: AsyncSession = Depends(get_db)
):
    """List all protocols with optional filtering."""
    query = select(Protocol)

    if processed is not None:
        query = query.where(Protocol.processed == processed)

    query = query.offset(skip).limit(limit).order_by(Protocol.session_date.desc())

    result = await db.execute(query)
    protocols = result.scalars().all()

    return [
        {
            "id": p.id,
            "session_date": p.session_date.isoformat(),
            "title": p.title,
            "getfile_id": p.getfile_id,
            "processed": p.processed,
            "created_at": p.created_at.isoformat()
        }
        for p in protocols
    ]


@router.get("/protocols/{protocol_id}")
async def get_protocol(protocol_id: int, db: AsyncSession = Depends(get_db)):
    """Get a specific protocol by ID."""
    result = await db.execute(
        select(Protocol).where(Protocol.id == protocol_id)
    )
    protocol = result.scalar_one_or_none()

    if not protocol:
        raise HTTPException(status_code=404, detail="Protocol not found")

    return {
        "id": protocol.id,
        "session_date": protocol.session_date.isoformat(),
        "title": protocol.title,
        "getfile_id": protocol.getfile_id,
        "pdf_text": protocol.pdf_text,
        "processed": protocol.processed,
        "created_at": protocol.created_at.isoformat()
    }


@router.get("/protocols/{protocol_id}/articles")
async def get_protocol_articles(protocol_id: int, db: AsyncSession = Depends(get_db)):
    """Get articles for a specific protocol."""
    result = await db.execute(
        select(Article).where(Article.protocol_id == protocol_id)
    )
    articles = result.scalars().all()

    return [
        {
            "id": a.id,
            "article_index": a.article_index,
            "content": a.content,
            "created_at": a.created_at.isoformat()
        }
        for a in articles
    ]


@router.get("/stats")
async def get_stats(db: AsyncSession = Depends(get_db)):
    """Get system statistics."""
    # Total protocols
    total_protocols_result = await db.execute(select(func.count(Protocol.id)))
    total_protocols = total_protocols_result.scalar()

    # Processed protocols
    processed_result = await db.execute(
        select(func.count(Protocol.id)).where(Protocol.processed == True)
    )
    processed_protocols = processed_result.scalar()

    # Total articles
    total_articles_result = await db.execute(select(func.count(Article.id)))
    total_articles = total_articles_result.scalar()

    return {
        "total_protocols": total_protocols,
        "processed_protocols": processed_protocols,
        "unprocessed_protocols": total_protocols - processed_protocols,
        "total_articles": total_articles
    }


# ============================================================================
# Pipeline Trigger Endpoints
# ============================================================================

@router.post("/pipeline/fetch")
async def trigger_fetch_protocols(db: AsyncSession = Depends(get_db)):
    """
    Manually trigger fetching protocols from SessionNet.
    This is the same operation that runs automatically via the scheduler.
    """
    try:
        protocols_found = await fetch_protocols_job(db)
        return {
            "status": "success",
            "protocols_found": protocols_found,
            "message": f"{protocols_found} new protocols fetched"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch protocols: {str(e)}")


@router.post("/pipeline/process")
async def trigger_process_protocols(db: AsyncSession = Depends(get_db)):
    """
    Manually trigger processing unprocessed protocols.
    This generates articles, images, and Instagram content.
    """
    try:
        processed_count = await process_protocols_job(db)
        return {
            "status": "success",
            "processed": processed_count,
            "message": f"{processed_count} protocols processed"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process protocols: {str(e)}")


@router.post("/pipeline/run")
async def trigger_pipeline_run(db: AsyncSession = Depends(get_db)):
    """
    Manually trigger a full pipeline run:
    1. Fetch protocols from SessionNet
    2. Process unprocessed protocols
    """
    try:
        # Step 1: Fetch protocols
        protocols_found = await fetch_protocols_job(db)

        # Step 2: Process protocols
        processed_count = await process_protocols_job(db)

        return {
            "status": "success",
            "fetch_result": {
                "protocols_found": protocols_found
            },
            "process_result": {
                "processed": processed_count
            },
            "message": f"Pipeline completed: {protocols_found} fetched, {processed_count} processed"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline run failed: {str(e)}")


@router.post("/pipeline/generate-insta")
async def trigger_generate_insta(
    protocol_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Manually trigger Instagram image generation.
    - Gate 1: Folder exists on disk	({ARTICLES_DIR}/{session_date}_{normalized_title})
    - Gate 2: Source images exist (image_*.jpg or image_*.png)
    - Gate 3: Articles with content (articles with non-empty content in SQL-DB)
    
    Args:
        protocol_id: Optional specific protocol ID to process.
                    If not provided, processes all eligible protocols.
    """
    # Check if specific protocol exists (404 case)
    if protocol_id is not None:
        result = await db.execute(
            select(Protocol).where(Protocol.id == protocol_id)
        )
        protocol = result.scalar_one_or_none()
        if not protocol:
            raise HTTPException(
                status_code=404,
                detail=f"Protocol {protocol_id} not found"
            )
    
    # Run the job
    result = await generate_insta_images_job(db, protocol_id)
    
    # Handle validation failure for specific protocol (400 case)
    if protocol_id is not None and result["failed"] == 1:
        # Find the failed protocol detail
        for detail in result.get("details", []):
            if detail.get("protocol_id") == protocol_id and detail.get("reason"):
                raise HTTPException(
                    status_code=400,
                    detail=f"Validation failed: {detail['reason']}"
                )
    
    return result


@router.get("/pipeline/status")
async def get_pipeline_status(db: AsyncSession = Depends(get_db)):
    """
    Get the current pipeline status including:
    - Number of unprocessed protocols
    - Total protocols
    - Total articles
    """
    # Total protocols
    total_protocols_result = await db.execute(select(func.count(Protocol.id)))
    total_protocols = total_protocols_result.scalar()

    # Unprocessed protocols
    unprocessed_result = await db.execute(
        select(func.count(Protocol.id)).where(Protocol.processed == False)
    )
    unprocessed_protocols = unprocessed_result.scalar()

    # Total articles
    total_articles_result = await db.execute(select(func.count(Article.id)))
    total_articles = total_articles_result.scalar()

    return {
        "unprocessed_protocols": unprocessed_protocols,
        "total_protocols": total_protocols,
        "total_articles": total_articles,
        "ready_to_process": unprocessed_protocols > 0
    }
