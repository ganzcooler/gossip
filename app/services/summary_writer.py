"""The stateless Summary-Writer role.

The writer receives only the planner's Summary-Briefs and the deterministic
source excerpts. A schema, structure, or budget violation gets exactly one
fresh retry with the validation feedback appended; after that the post fails
with a clear writer error. Authentication and transport errors are not writer
retries and propagate to the pipeline.
"""

from collections.abc import Sequence

from pydantic import ValidationError

from app.core.post_models import SourceExcerpt, SummaryBrief, SummaryDraft
from app.core.post_prompts import build_summary_writer_prompt
from app.services.llm_client import LLMClient, LLMSchemaError

SUMMARY_WRITER_ROLE = "summary_writer"


class SummaryWriterError(Exception):
    """The Summary-Writer did not produce a valid draft after its retry."""


async def write_summary(
    briefs: Sequence[SummaryBrief],
    excerpts: Sequence[SourceExcerpt],
    llm: LLMClient,
) -> SummaryDraft:
    """Write one Summary draft from Summary-Briefs and excerpts."""
    feedback: str | None = None

    for attempt in (1, 2):
        prompt = build_summary_writer_prompt(
            briefs=briefs, excerpts=excerpts, feedback=feedback
        )
        try:
            response = await llm.generate_json(
                role=SUMMARY_WRITER_ROLE,
                prompt=prompt,
                schema=SummaryDraft,
            )
            if isinstance(response, SummaryDraft):
                return response
            return SummaryDraft.model_validate(response)
        except (LLMSchemaError, ValidationError, ValueError) as exc:
            if attempt == 1:
                feedback = str(exc)
                continue
            raise SummaryWriterError(
                f"Summary writer failed after retry: {exc}"
            ) from exc

    raise AssertionError("unreachable")


__all__ = ["SUMMARY_WRITER_ROLE", "SummaryWriterError", "write_summary"]
