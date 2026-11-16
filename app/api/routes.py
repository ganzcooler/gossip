from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.core.config import ARTICLES_DIR
from app.database import get_db
from app.models import Protocol, Article, Post
from app.services.llm_client import OpenRouterLLMClient
from app.services.post_pipeline import PostPipeline
from app.services.protocol_fetcher import fetch_protocols_job

router = APIRouter()


def get_post_pipeline() -> PostPipeline:
    """Build the default pipeline for the API; tests override this dependency."""
    return PostPipeline(OpenRouterLLMClient(), ARTICLES_DIR)


def _isoformat(value):
    return value.isoformat() if value is not None else None


def _serialize_post_summary(post):
    """Compact post representation for protocol post listings."""
    return {
        "id": post.id,
        "protocol_id": post.protocol_id,
        "post_type": post.post_type,
        "slug": post.slug,
        "post_index": post.post_index,
        "title": post.title,
        "status": post.status,
        "failed_step": post.failed_step,
        "caption": post.caption,
        "slide_count": len(post.slides),
        "created_at": _isoformat(post.created_at),
        "updated_at": _isoformat(post.updated_at),
    }


def _serialize_slide(slide):
    return {
        "id": slide.id,
        "slide_index": slide.slide_index,
        "slide_type": slide.slide_type,
        "pair_index": slide.pair_index,
        "label": slide.label,
        "headline": slide.headline,
        "body": slide.body,
        "alt_text": slide.alt_text,
    }


def _serialize_asset(asset):
    return {
        "id": asset.id,
        "role": asset.role,
        "prompt": asset.prompt,
        "path": asset.path,
        "status": asset.status,
        "error": asset.error,
        "model": asset.model,
    }


def _serialize_post_detail(post):
    """Full post representation including ordered Folien and assets."""
    data = _serialize_post_summary(post)
    data.update(
        {
            "content_json": post.content_json,
            "content_markdown": post.content_markdown,
            "slide_plan_json": post.slide_plan_json,
            "alt_text_json": post.alt_text_json,
            "fact_check_json": post.fact_check_json,
            "error": post.error,
            "generator_version": post.generator_version,
            "slides": [_serialize_slide(slide) for slide in post.slides],
            "assets": [_serialize_asset(asset) for asset in post.assets],
        }
    )
    return data


async def _get_post_counts(db):
    """Count Beiträge per status, with all three statuses always present."""
    result = await db.execute(
        select(Post.status, func.count(Post.id)).group_by(Post.status)
    )
    counts = {"draft": 0, "ready": 0, "failed": 0}
    for status, count in result.all():
        if status in counts:
            counts[status] = count
    return counts


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


@router.get("/protocols/{protocol_id}/posts")
async def get_protocol_posts(protocol_id: int, db: AsyncSession = Depends(get_db)):
    """List a protocol's Beiträge ordered by their position."""
    protocol_result = await db.execute(
        select(Protocol.id).where(Protocol.id == protocol_id)
    )
    if protocol_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Protocol not found")

    result = await db.execute(
        select(Post)
        .options(selectinload(Post.slides))
        .where(Post.protocol_id == protocol_id)
        .order_by(Post.post_index, Post.id)
    )
    posts = result.scalars().all()

    return [_serialize_post_summary(post) for post in posts]


@router.get("/posts/{post_id}")
async def get_post(post_id: int, db: AsyncSession = Depends(get_db)):
    """Get one Beitrag with its ordered Folien and assets."""
    result = await db.execute(
        select(Post)
        .options(selectinload(Post.slides), selectinload(Post.assets))
        .where(Post.id == post_id)
    )
    post = result.scalar_one_or_none()

    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    return _serialize_post_detail(post)


@router.post("/posts/{post_id}/retry")
async def retry_post(
    post_id: int,
    force: bool = False,
    db: AsyncSession = Depends(get_db),
    pipeline: PostPipeline = Depends(get_post_pipeline),
):
    """Retry one failed Beitrag, optionally restarting at the writer."""
    result = await db.execute(
        select(Post)
        .options(selectinload(Post.slides), selectinload(Post.assets))
        .where(Post.id == post_id)
    )
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    await pipeline.retry_post(post, db, force=force)

    refreshed = await db.execute(
        select(Post)
        .options(selectinload(Post.slides), selectinload(Post.assets))
        .where(Post.id == post_id)
        .execution_options(populate_existing=True)
    )
    post = refreshed.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    return _serialize_post_detail(post)


@router.post("/protocols/{protocol_id}/reprocess")
async def reprocess_protocol(
    protocol_id: int,
    db: AsyncSession = Depends(get_db),
    pipeline: PostPipeline = Depends(get_post_pipeline),
):
    """Rebuild a protocol's Redaktionsplan and all Beiträge."""
    result = await db.execute(
        select(Protocol).where(Protocol.id == protocol_id)
    )
    protocol = result.scalar_one_or_none()
    if not protocol:
        raise HTTPException(status_code=404, detail="Protocol not found")

    pipeline_result = await pipeline.reprocess_protocol(protocol, db)

    counts = {"draft": 0, "ready": 0, "failed": 0}
    for post in pipeline_result.posts:
        if post.status in counts:
            counts[post.status] += 1

    return {
        "protocol_id": protocol.id,
        "processed": bool(protocol.processed),
        "plan_status": pipeline_result.plan_status,
        "post_counts": counts,
        "posts": [
            {
                "post_id": post.post_id,
                "post_type": post.post_type,
                "slug": post.slug,
                "status": post.status,
                "failed_step": post.failed_step,
                "error": post.error,
            }
            for post in pipeline_result.posts
        ],
    }


@router.get("/stats")
async def get_stats(db: AsyncSession = Depends(get_db)):
    """Get system statistics."""
    # Total protocols
    total_protocols_result = await db.execute(select(func.count(Protocol.id)))
    total_protocols = total_protocols_result.scalar()

    # Processed protocols
    processed_result = await db.execute(
        select(func.count(Protocol.id)).where(Protocol.processed.is_(True))
    )
    processed_protocols = processed_result.scalar()

    # Total articles
    total_articles_result = await db.execute(select(func.count(Article.id)))
    total_articles = total_articles_result.scalar()

    return {
        "total_protocols": total_protocols,
        "processed_protocols": processed_protocols,
        "unprocessed_protocols": total_protocols - processed_protocols,
        "total_articles": total_articles,
        "post_counts": await _get_post_counts(db),
    }


# ============================================================================
# Protocol Ingestion Trigger Endpoints
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
        select(func.count(Protocol.id)).where(Protocol.processed.is_(False))
    )
    unprocessed_protocols = unprocessed_result.scalar()

    # Total articles
    total_articles_result = await db.execute(select(func.count(Article.id)))
    total_articles = total_articles_result.scalar()

    return {
        "unprocessed_protocols": unprocessed_protocols,
        "total_protocols": total_protocols,
        "total_articles": total_articles,
        "ready_to_process": unprocessed_protocols > 0,
        "post_counts": await _get_post_counts(db),
    }
