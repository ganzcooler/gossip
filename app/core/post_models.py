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


class SummaryPoint(PipelineModel):
    """One Summary-Punkt: kicker, heading and a 120–320 character body."""

    kicker: str
    heading: str
    body: str

    @field_validator("kicker")
    @classmethod
    def _one_word_kicker(cls, value: str) -> str:
        value = value.strip()
        if len(value.split()) != 1:
            raise ValueError("kicker must be exactly one word")
        return value

    @field_validator("heading")
    @classmethod
    def _require_heading(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("heading must not be empty")
        return value

    @field_validator("body")
    @classmethod
    def _body_length(cls, value: str) -> str:
        value = value.strip()
        if not 120 <= len(value) <= 320:
            raise ValueError(
                "body must contain 120 to 320 characters including spaces"
            )
        return value


class SummaryDraft(PipelineModel):
    """The Summary-Writer's complete draft: cover title plus two to six points."""

    cover_title: str
    points: list[SummaryPoint] = Field(min_length=2, max_length=6)

    @field_validator("cover_title")
    @classmethod
    def _cover_title_length(cls, value: str) -> str:
        value = value.strip()
        if not 20 <= len(value) <= 100:
            raise ValueError(
                "cover_title must contain 20 to 100 characters including spaces"
            )
        return value


class TopicSection(PipelineModel):
    """One H2 Themenabschnitt with its paragraphs."""

    h2: str
    paragraphs: list[str] = Field(min_length=1)

    @field_validator("h2")
    @classmethod
    def _h2_length(cls, value: str) -> str:
        value = value.strip()
        if not 20 <= len(value) <= 60:
            raise ValueError(
                "h2 must contain 20 to 60 characters including spaces"
            )
        return value

    @field_validator("paragraphs")
    @classmethod
    def _require_paragraphs(cls, paragraphs: list[str]) -> list[str]:
        cleaned = [paragraph.strip() for paragraph in paragraphs]
        if not cleaned or any(not paragraph for paragraph in cleaned):
            raise ValueError("paragraphs must contain at least one non-empty paragraph")
        return cleaned


class TopicDraft(PipelineModel):
    """The Themen-Writer's article: H1 plus two to six H2 sections."""

    title: str
    sections: list[TopicSection] = Field(min_length=2, max_length=6)

    @field_validator("title")
    @classmethod
    def _title_length(cls, value: str) -> str:
        value = value.strip()
        if not 20 <= len(value) <= 100:
            raise ValueError(
                "title must contain 20 to 100 characters including spaces"
            )
        return value

    @model_validator(mode="after")
    def _total_text_budget(self) -> "TopicDraft":
        total = len(self.title) + sum(
            len(section.h2)
            + sum(len(paragraph) for paragraph in section.paragraphs)
            for section in self.sections
        )
        if total > 3000:
            raise ValueError(
                "topic article text must not exceed 3000 characters including "
                f"spaces (got {total})"
            )
        return self


class FactCheckResult(PipelineModel):
    """The Faktenprüfung result; an empty issue list means the draft passes."""

    issues: list[str] = Field(default_factory=list)

    @field_validator("issues")
    @classmethod
    def _actionable_issues(cls, issues: list[str]) -> list[str]:
        cleaned = [issue.strip() for issue in issues]
        if any(not issue for issue in cleaned):
            raise ValueError("each issue must be a non-empty, actionable sentence")
        return cleaned

    @property
    def passed(self) -> bool:
        return not self.issues


class CaptionDraft(PipelineModel):
    """The LLM-written caption body before deterministic source/link composition."""

    body: str

    @field_validator("body")
    @classmethod
    def _require_body(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("caption body must not be empty")
        return value


class VisualPrompts(PipelineModel):
    """The Visual-Prompt-Writer's cover plus optional artwork prompts.

    The Summary-Beitrag uses only the cover prompt; its cards reuse the cover
    art. Topic posts use one artwork prompt per pair.
    """

    cover_prompt: str
    artwork_prompts: list[str] = Field(default_factory=list)

    @field_validator("cover_prompt")
    @classmethod
    def _require_cover_prompt(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("cover_prompt must not be empty")
        return value

    @field_validator("artwork_prompts")
    @classmethod
    def _require_artwork_prompts(cls, prompts: list[str]) -> list[str]:
        cleaned = [prompt.strip() for prompt in prompts]
        if any(not prompt for prompt in cleaned):
            raise ValueError("artwork_prompts must contain non-empty prompts")
        return cleaned
