from sqlalchemy import Column, Integer, Text, Boolean, DateTime, Date, ForeignKey, Index
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