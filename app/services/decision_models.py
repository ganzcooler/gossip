"""Typed request and response models for the OpenRouter Decisions API.

The Decisions API is not the chat endpoint: callers send one ``state`` and a
map of typed questions, and receive one typed answer per question. These
models are the small, strict subset the post pipeline needs (binary ``noul``
questions about an image).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class ImageURL(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str


class ImagePart(BaseModel):
    """One image content part in the Decisions API ``state`` array."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["image_url"] = "image_url"
    image_url: ImageURL


class NoulCriteria(BaseModel):
    """Custom definitions for what counts as true and false."""

    model_config = ConfigDict(extra="forbid")

    true: str
    false: str


class NoulQuestion(BaseModel):
    """Ask whether a condition holds and receive a probability of true."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["noul"] = "noul"
    instructions: str
    criteria: NoulCriteria | None = None


class NoulAnswer(BaseModel):
    """Probability that the condition holds, between 0.0 and 1.0."""

    model_config = ConfigDict(extra="allow")

    type: Literal["noul"]
    noul: float = Field(ge=0.0, le=1.0)
    confidence: float | None = None


class RefusalAnswer(BaseModel):
    """The provider declined to answer this question."""

    model_config = ConfigDict(extra="allow")

    type: Literal["refusal"]


DecisionAnswer = Annotated[NoulAnswer | RefusalAnswer, Field(discriminator="type")]


class DecisionUsage(BaseModel):
    model_config = ConfigDict(extra="allow")

    input_tokens: int | None = None
    output_tokens: int | None = None
    cost: float | None = None


class DecisionResponse(BaseModel):
    """One typed answer per requested question plus billing metadata."""

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    model: str | None = None
    provider: str | None = None
    answers: dict[str, DecisionAnswer]
    usage: DecisionUsage | None = None


DecisionState = str | list[str | ImagePart]


__all__ = [
    "DecisionAnswer",
    "DecisionResponse",
    "DecisionState",
    "DecisionUsage",
    "ImagePart",
    "ImageURL",
    "NoulAnswer",
    "NoulCriteria",
    "NoulQuestion",
    "RefusalAnswer",
]
