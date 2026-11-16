"""Shared hard Faktenprüfung gate with one repair attempt.

Summary and topic content paths call the same functions with distinct role
names. The gate is deliberately not advisory: remaining issues after repair
raise :class:`FactCheckFailedError`. The fact-check call sees only the draft
and excerpts; the repair call sees only the draft, the issues, and the
excerpts. No protocol text or conversation history is passed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from app.core.post_models import FactCheckResult, SourceExcerpt
from app.core.post_prompts import build_fact_check_prompt, build_repair_prompt
from app.services.llm_client import (
    LLMAuthenticationError,
    LLMClient,
    LLMError,
)

DEFAULT_FACT_CHECK_ROLE = "fact_check"
DEFAULT_REPAIR_ROLE = "repair"


@dataclass(frozen=True)
class FactCheckOutcome:
    """The draft that passed the gate and the repair metadata."""

    draft: BaseModel
    repaired: bool = False
    issues: tuple[str, ...] = field(default_factory=tuple)


class FactCheckError(Exception):
    """A fact-check, repair, or second-check call could not complete."""

    def __init__(
        self,
        message: str,
        *,
        step: str,
        issues: Sequence[str] = (),
    ):
        super().__init__(message)
        self.step = step
        self.issues = list(issues)


class FactCheckFailedError(FactCheckError):
    """Issues remained after the single repair attempt."""


async def _generate(
    llm: LLMClient,
    *,
    role: str,
    prompt: str,
    schema: type[BaseModel],
    step: str,
) -> BaseModel:
    try:
        response = await llm.generate_json(
            role=role, prompt=prompt, schema=schema
        )
        if isinstance(response, schema):
            return response
        return schema.model_validate(response)
    except LLMAuthenticationError:
        raise
    except (LLMError, ValidationError, TypeError, ValueError) as exc:
        raise FactCheckError(
            f"{step} call failed: {exc}", step=step
        ) from exc


async def _check(
    draft: BaseModel,
    excerpts: Sequence[SourceExcerpt],
    llm: LLMClient,
    *,
    role: str,
) -> FactCheckResult:
    prompt = build_fact_check_prompt(draft=draft, excerpts=excerpts)
    response = await _generate(
        llm,
        role=role,
        prompt=prompt,
        schema=FactCheckResult,
        step="fact_check",
    )
    assert isinstance(response, FactCheckResult)
    return response


async def _repair(
    draft: BaseModel,
    issues: Sequence[str],
    excerpts: Sequence[SourceExcerpt],
    llm: LLMClient,
    *,
    role: str,
    draft_schema: type[BaseModel],
) -> BaseModel:
    prompt = build_repair_prompt(draft=draft, issues=issues, excerpts=excerpts)
    return await _generate(
        llm,
        role=role,
        prompt=prompt,
        schema=draft_schema,
        step="repair",
    )


async def enforce_fact_check(
    draft: BaseModel,
    excerpts: Sequence[SourceExcerpt],
    llm: LLMClient,
    *,
    draft_schema: type[BaseModel],
    fact_check_role: str = DEFAULT_FACT_CHECK_ROLE,
    repair_role: str = DEFAULT_REPAIR_ROLE,
) -> FactCheckOutcome:
    """Run the fact-check gate; one repair, one re-check, then pass or fail.

    ``FactCheckError`` (with ``.step`` set to ``fact_check`` or ``repair``)
    means a call could not complete. ``FactCheckFailedError`` means the draft
    still has issues after repair; the issues are attached to the error.
    """
    result = await _check(draft, excerpts, llm, role=fact_check_role)
    if result.passed:
        return FactCheckOutcome(draft=draft)

    repaired_draft = await _repair(
        draft,
        result.issues,
        excerpts,
        llm,
        role=repair_role,
        draft_schema=draft_schema,
    )
    second = await _check(
        repaired_draft, excerpts, llm, role=fact_check_role
    )
    if not second.passed:
        raise FactCheckFailedError(
            "Faktenprüfung failed after repair: "
            + "; ".join(second.issues),
            step="fact_check",
            issues=second.issues,
        )

    return FactCheckOutcome(
        draft=repaired_draft,
        repaired=True,
        issues=(),
    )


def fact_check_json(
    *, passed: bool, issues: Sequence[str] = (), repaired: bool = False
) -> dict[str, Any]:
    """Build the deterministic ``post.fact_check_json`` payload."""
    return {
        "passed": passed,
        "issues": list(issues),
        "repaired": repaired,
    }


__all__ = [
    "DEFAULT_FACT_CHECK_ROLE",
    "DEFAULT_REPAIR_ROLE",
    "FactCheckError",
    "FactCheckFailedError",
    "FactCheckOutcome",
    "enforce_fact_check",
    "fact_check_json",
]
