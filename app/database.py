from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from app.core.config import DATABASE_URL

# Create async engine
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True
)

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

# Base class for models
Base = declarative_base()


async def get_db():
    """Dependency for getting async database sessions."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def create_tables():
    """Create all database tables using SQLAlchemy's create_all().
    
    This function is called on application startup to initialize the database schema.
    It imports all models to ensure they are registered with the Base metadata.
    """
    # Import models to ensure they are registered with Base.metadata
    from app.models import (  # noqa: F401
        Article,
        EditorialPlan,
        Post,
        PostAsset,
        PostSlide,
        Protocol,
    )
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def init_db():
    """Initialize database tables on startup."""
    await create_tables()