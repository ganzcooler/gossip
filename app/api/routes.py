from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List

from app.database import get_db
from app.models import Protocol, Article

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