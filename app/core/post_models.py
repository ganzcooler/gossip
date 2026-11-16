"""Pydantic models for the stateless post pipeline's structured inputs.

Every model forbids unknown fields so that a provider response cannot smuggle
extra structure past a step boundary. Validators normalise surrounding
whitespace and enforce the editorial limits from the spec.
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PipelineModel(BaseModel):
    """Base class that keeps every pipeline payload strict."""

    model_config = ConfigDict(extra="forbid")


class SourceExcerpt(PipelineModel):
    """One deterministic excerpt retrieved for a Quellenanker."""

    anchor: str
    excerpt: str

    @field_validator("anchor", "excerpt")
    @classmethod
    def _require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class SummaryBrief(PipelineModel):
    """The planner's input for one Summary-Punkt."""

    point: str
    relevance: str
    source_anchors: list[str] = Field(min_length=1)

    @field_validator("point", "relevance")
    @classmethod
    def _require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @field_validator("source_anchors")
    @classmethod
    def _require_anchors(cls, anchors: list[str]) -> list[str]:
        cleaned = [anchor.strip() for anchor in anchors]
        if not cleaned or any(not anchor for anchor in cleaned):
            raise ValueError("source_anchors must contain non-empty anchors")
        return cleaned


class TopicBrief(PipelineModel):
    """The planner's brief for one Themenbeitrag."""

    slug: str = Field(pattern=r"^[a-z0-9-]+$")
    title: str
    focus: str
    relevance: str
    source_anchors: list[str] = Field(min_length=1)

    @field_validator("slug")
    @classmethod
    def _clean_slug(cls, value: str) -> str:
        return value.strip()

    @field_validator("title", "focus", "relevance")
    @classmethod
    def _require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @field_validator("source_anchors")
    @classmethod
    def _require_anchors(cls, anchors: list[str]) -> list[str]:
        cleaned = [anchor.strip() for anchor in anchors]
        if not cleaned or any(not anchor for anchor in cleaned):
            raise ValueError("source_anchors must contain non-empty anchors")
        return cleaned


class EditorialPlan(PipelineModel):
    """The Redaktionsplan for one Sitzung."""

    summary_focus: str
    summary_title: str
    summary_briefs: list[SummaryBrief] = Field(min_length=2, max_length=6)
    topic_briefs: list[TopicBrief] = Field(default_factory=list, max_length=5)

    @field_validator("summary_focus", "summary_title")
    @classmethod
    def _require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @model_validator(mode="after")
    def _topic_slugs_are_unique(self) -> "EditorialPlan":
        slugs = [brief.slug for brief in self.topic_briefs]
        if len(slugs) != len(set(slugs)):
            raise ValueError("topic_briefs must have unique slugs")
        return self
