import enum

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import relationship
from datetime import datetime

from app.database import Base


class PostType(str, enum.Enum):
    """The two reader-facing post types."""

    SUMMARY = "summary"
    TOPIC = "topic"


class PostStatus(str, enum.Enum):
    """Lifecycle of a generated post."""

    DRAFT = "draft"
    READY = "ready"
    FAILED = "failed"


class Protocol(Base):
    """Model for storing protocol metadata and PDF text."""

    __tablename__ = "protocols"

    id = Column(Integer, primary_key=True, index=True)
    session_date = Column(Date, nullable=False)
    title = Column(Text, nullable=False)
    getfile_id = Column(Integer, nullable=False, unique=True)
    pdf_text = Column(Text, nullable=False)
    processed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    articles = relationship(
        "Article", back_populates="protocol", cascade="all, delete-orphan"
    )
    editorial_plan = relationship(
        "EditorialPlan",
        back_populates="protocol",
        uselist=False,
        cascade="all, delete-orphan",
    )
    posts = relationship(
        "Post", back_populates="protocol", cascade="all, delete-orphan"
    )

    # Indexes
    __table_args__ = (
        Index("idx_protocols_session_date", "session_date"),
        Index("idx_protocols_getfile_id", "getfile_id"),
        Index("idx_protocols_processed", "processed"),
    )


class Article(Base):
    """Legacy model for the old one-article-per-topic pipeline."""

    __tablename__ = "articles"

    id = Column(Integer, primary_key=True, index=True)
    protocol_id = Column(
        Integer, ForeignKey("protocols.id", ondelete="CASCADE"), nullable=False
    )
    article_index = Column(Integer, nullable=True)
    content = Column(Text, nullable=False)
    caption = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    protocol = relationship("Protocol", back_populates="articles")

    # Indexes
    __table_args__ = (Index("idx_articles_protocol_id", "protocol_id"),)


class EditorialPlan(Base):
    """The editorial plan for one protocol.

    Stored separately so retries reuse the same summary focus and topic list
    instead of asking the model to select different topics.
    """

    __tablename__ = "editorial_plans"

    id = Column(Integer, primary_key=True, index=True)
    protocol_id = Column(
        Integer,
        ForeignKey("protocols.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    plan_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    protocol = relationship("Protocol", back_populates="editorial_plan")


class Post(Base):
    """A reader-facing post generated from a protocol.

    ``content_markdown`` is the complete Beitragstext. ``content_json`` is the
    structured form of the same text. Slides are a separate, derived artifact.
    """

    __tablename__ = "posts"

    id = Column(Integer, primary_key=True, index=True)
    protocol_id = Column(
        Integer, ForeignKey("protocols.id", ondelete="CASCADE"), nullable=False
    )
    post_type = Column(SQLEnum(PostType, native_enum=False), nullable=False)
    slug = Column(Text, nullable=False)
    post_index = Column(Integer, nullable=False)
    title = Column(Text, nullable=False)
    kicker = Column(Text, nullable=False)
    content_markdown = Column(Text, nullable=False)
    content_json = Column(JSON, nullable=False)
    slide_plan_json = Column(JSON, nullable=True)
    caption = Column(Text, nullable=True)
    status = Column(
        SQLEnum(PostStatus, native_enum=False),
        nullable=False,
        default=PostStatus.DRAFT,
    )
    error = Column(Text, nullable=True)
    generator_version = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    protocol = relationship("Protocol", back_populates="posts")
    slides = relationship(
        "PostSlide",
        back_populates="post",
        cascade="all, delete-orphan",
        order_by="PostSlide.slide_index",
    )
    assets = relationship(
        "PostAsset",
        back_populates="post",
        cascade="all, delete-orphan",
        order_by="PostAsset.role",
    )

    __table_args__ = (
        UniqueConstraint(
            "protocol_id", "post_type", "slug", name="uq_posts_protocol_type_slug"
        ),
        Index("idx_posts_protocol_id", "protocol_id"),
        Index("idx_posts_status", "status"),
    )


class PostSlide(Base):
    """Semantic text for one slide of a post."""

    __tablename__ = "post_slides"

    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(
        Integer, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False
    )
    slide_index = Column(Integer, nullable=False)
    pair_index = Column(Integer, nullable=True)
    label = Column(Text, nullable=True)
    headline = Column(Text, nullable=False)
    body = Column(Text, nullable=False)

    post = relationship("Post", back_populates="slides")

    __table_args__ = (
        UniqueConstraint("post_id", "slide_index", name="uq_post_slides_post_index"),
        Index("idx_post_slides_post_id", "post_id"),
    )


class PostAsset(Base):
    """A generated image asset for a post.

    Roles are ``cover``, ``artwork_1`` … for source images and ``slide_01`` …
    for rendered slides. Keeping prompts and status here makes image retries
    cheap and lets later processing inspect how an asset was produced.
    """

    __tablename__ = "post_assets"

    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(
        Integer, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False
    )
    role = Column(Text, nullable=False)
    prompt = Column(Text, nullable=True)
    path = Column(Text, nullable=True)
    status = Column(Text, nullable=False, default="pending")
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    post = relationship("Post", back_populates="assets")

    __table_args__ = (
        UniqueConstraint("post_id", "role", name="uq_post_assets_post_role"),
        Index("idx_post_assets_post_id", "post_id"),
    )
