"""Pydantic models for the two-post pipeline.

These models are both the validation layer for LLM responses and the
structured form of the text persisted in the database.
"""

from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class PostType(str, Enum):
    SUMMARY = "summary"
    TOPIC = "topic"


class PostStatus(str, Enum):
    DRAFT = "draft"
    READY = "ready"
    FAILED = "failed"


class SummaryBrief(BaseModel):
    """Editorial brief for the session summary."""

    working_title: str
    focus: str
    key_points: List[str]


class TopicBrief(BaseModel):
    """Editorial brief for one topic post."""

    slug: str
    working_title: str
    focus: str
    why_relevant: str
    protocol_anchors: List[str]


class EditorialPlan(BaseModel):
    """The editorial plan for one protocol."""

    session_label: Optional[str] = None
    summary: SummaryBrief
    topics: List[TopicBrief]


class ArticleSection(BaseModel):
    heading: str
    paragraphs: List[str]


class ArticleDraft(BaseModel):
    """A complete Beitragstext, written before any slide planning."""

    title: str
    kicker: str
    lead: str
    sections: List[ArticleSection]
    key_takeaways: List[str]


class CoverPlan(BaseModel):
    kicker: str
    headline: str
    image_brief: str


class SlideContent(BaseModel):
    label: Optional[str] = None
    headline: str
    body: str


class SummarySlidePlan(BaseModel):
    cover: CoverPlan
    slides: List[SlideContent]


class TopicSlidePair(BaseModel):
    slides: List[SlideContent] = Field(min_length=2, max_length=2)
    artwork_brief: str


class TopicSlidePlan(BaseModel):
    cover: CoverPlan
    pairs: List[TopicSlidePair]


class FactCheckIssue(BaseModel):
    claim: str
    problem: str
    evidence: Optional[str] = None


class FactCheckResult(BaseModel):
    issues: List[FactCheckIssue]
    verdict: Literal["ok", "needs_repair"]


class CaptionResult(BaseModel):
    caption: str
