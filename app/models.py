from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base


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
    articles = relationship("Article", back_populates="protocol", cascade="all, delete-orphan")
    editorial_plan = relationship(
        "EditorialPlan",
        back_populates="protocol",
        cascade="all, delete-orphan",
        uselist=False,
    )
    posts = relationship(
        "Post",
        back_populates="protocol",
        cascade="all, delete-orphan",
        order_by="Post.post_index",
    )

    # Indexes
    __table_args__ = (
        Index('idx_protocols_session_date', 'session_date'),
        Index('idx_protocols_getfile_id', 'getfile_id'),
        Index('idx_protocols_processed', 'processed'),
    )


class Article(Base):
    """Model for storing generated articles."""
    __tablename__ = "articles"

    id = Column(Integer, primary_key=True, index=True)
    protocol_id = Column(Integer, ForeignKey("protocols.id", ondelete="CASCADE"), nullable=False)
    article_index = Column(Integer, nullable=True)
    content = Column(Text, nullable=False)
    caption = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    protocol = relationship("Protocol", back_populates="articles")

    # Indexes
    __table_args__ = (
        Index('idx_articles_protocol_id', 'protocol_id'),
    )


class EditorialPlan(Base):
    """The Redaktionsplan for one protocol."""

    __tablename__ = "editorial_plans"

    id = Column(Integer, primary_key=True, index=True)
    protocol_id = Column(
        Integer,
        ForeignKey("protocols.id", ondelete="CASCADE"),
        nullable=False,
    )
    plan_json = Column(JSON, nullable=True)
    status = Column(Text, nullable=False, default="draft")
    failed_step = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    generator_version = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # Relationships
    protocol = relationship("Protocol", back_populates="editorial_plan")

    # Constraints and indexes
    __table_args__ = (
        UniqueConstraint("protocol_id", name="uq_editorial_plans_protocol_id"),
        CheckConstraint(
            "status IN ('draft', 'ready', 'failed')",
            name="ck_editorial_plans_status",
        ),
    )


class Post(Base):
    """One reader-facing Beitrag: a Summary or a topic post."""

    __tablename__ = "posts"

    id = Column(Integer, primary_key=True, index=True)
    protocol_id = Column(
        Integer,
        ForeignKey("protocols.id", ondelete="CASCADE"),
        nullable=False,
    )
    post_type = Column(Text, nullable=False)
    slug = Column(Text, nullable=False)
    post_index = Column(Integer, nullable=False)
    title = Column(Text, nullable=True)
    content_json = Column(JSON, nullable=True)
    content_markdown = Column(Text, nullable=True)
    slide_plan_json = Column(JSON, nullable=True)
    caption = Column(Text, nullable=True)
    alt_text_json = Column(JSON, nullable=True)
    fact_check_json = Column(JSON, nullable=True)
    status = Column(Text, nullable=False, default="draft")
    failed_step = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    generator_version = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # Relationships
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
        order_by="PostAsset.id",
    )

    # Constraints and indexes
    __table_args__ = (
        UniqueConstraint(
            "protocol_id",
            "post_type",
            "slug",
            name="uq_posts_protocol_type_slug",
        ),
        CheckConstraint(
            "post_type IN ('summary', 'topic')",
            name="ck_posts_post_type",
        ),
        CheckConstraint(
            "status IN ('draft', 'ready', 'failed')",
            name="ck_posts_status",
        ),
        Index("idx_posts_protocol_id", "protocol_id"),
        Index("idx_posts_protocol_index", "protocol_id", "post_index"),
        Index("idx_posts_status", "status"),
    )


class PostSlide(Base):
    """One rendered Folie of a Beitrag."""

    __tablename__ = "post_slides"

    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(
        Integer,
        ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
    )
    slide_index = Column(Integer, nullable=False)
    slide_type = Column(Text, nullable=False)
    pair_index = Column(Integer, nullable=True)
    label = Column(Text, nullable=True)
    headline = Column(Text, nullable=True)
    body = Column(Text, nullable=True)
    alt_text = Column(Text, nullable=True)

    # Relationships
    post = relationship("Post", back_populates="slides")

    # Constraints and indexes
    __table_args__ = (
        UniqueConstraint("post_id", "slide_index", name="uq_post_slides_post_index"),
        CheckConstraint(
            "slide_type IN ('cover', 'heading', 'continuation')",
            name="ck_post_slides_slide_type",
        ),
        Index("idx_post_slides_post_id", "post_id"),
    )


class PostAsset(Base):
    """One generated image asset belonging to a Beitrag."""

    __tablename__ = "post_assets"

    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(
        Integer,
        ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
    )
    role = Column(Text, nullable=False)
    prompt = Column(Text, nullable=True)
    path = Column(Text, nullable=True)
    status = Column(Text, nullable=False, default="pending")
    error = Column(Text, nullable=True)
    model = Column(Text, nullable=True)

    # Relationships
    post = relationship("Post", back_populates="assets")

    # Constraints and indexes
    __table_args__ = (
        UniqueConstraint("post_id", "role", name="uq_post_assets_post_role"),
        CheckConstraint(
            "status IN ('pending', 'ready', 'fallback', 'failed')",
            name="ck_post_assets_status",
        ),
        Index("idx_post_assets_post_id", "post_id"),
    )
