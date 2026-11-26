"""Typed request and response models for the OpenRouter Decisions API.

The Decisions API is not the chat endpoint: callers send one ``state`` and a
map of typed questions, and receive one typed answer per question. These
models are the small, strict subset the post pipeline needs (binary ``noul``
image checks and ``choice`` kicker ranking).
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


class ChoiceQuestion(BaseModel):
    """Ask for exactly one option; the criteria keys are the options."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["choice"] = "choice"
    instructions: str | None = None
    criteria: dict[str, str | None]


class NoulAnswer(BaseModel):
    """Probability that the condition holds, between 0.0 and 1.0."""

    model_config = ConfigDict(extra="allow")

    type: Literal["noul"]
    noul: float = Field(ge=0.0, le=1.0)
    confidence: float | None = None


class ChoiceAnswer(BaseModel):
    """The selected option plus its confidence and optional probabilities."""

    model_config = ConfigDict(extra="allow")

    type: Literal["choice"]
    choice: str
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    probabilities: dict[str, Annotated[float, Field(ge=0.0, le=1.0)]] | None = None


class RefusalAnswer(BaseModel):
    """The provider declined to answer this question."""

    model_config = ConfigDict(extra="allow")

    type: Literal["refusal"]


DecisionQuestion = NoulQuestion | ChoiceQuestion
DecisionAnswer = Annotated[
    NoulAnswer | ChoiceAnswer | RefusalAnswer, Field(discriminator="type")
]


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
    "ChoiceAnswer",
    "ChoiceQuestion",
    "DecisionAnswer",
    "DecisionQuestion",
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
