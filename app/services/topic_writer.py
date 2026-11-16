"""The stateless Themen-Writer role.

The writer receives only one Themenbrief and its deterministic source
excerpts. A schema, structure, or budget violation gets exactly one fresh
retry with the validation feedback appended. When a composition callback is
supplied, a slide-count/structure violation is fed back through the same single
retry; after that the post fails with a clear writer error and the step that
caused it (``writer`` or ``slide_composer``). Authentication and transport
errors are not writer retries and propagate to the pipeline.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from pydantic import ValidationError

from app.core.post_models import SourceExcerpt, TopicBrief, TopicDraft
from app.core.post_prompts import build_topic_writer_prompt
from app.services.llm_client import LLMClient, LLMSchemaError
from app.services.slide_composer import TopicCompositionError

TOPIC_WRITER_ROLE = "topic_writer"


class TopicWriterError(Exception):
    """The Themen-Writer did not produce a valid draft after its retry."""

    def __init__(self, message: str, *, step: str = "writer"):
        super().__init__(message)
        self.step = step


async def write_topic(
    brief: TopicBrief,
    excerpts: Sequence[SourceExcerpt],
    llm: LLMClient,
    *,
    compose: Callable[[TopicDraft], object] | None = None,
) -> TopicDraft:
    """Write one topic draft from one Themenbrief and its excerpts."""
    feedback: str | None = None

    for attempt in (1, 2):
        prompt = build_topic_writer_prompt(
            brief=brief, excerpts=excerpts, feedback=feedback
        )
        step = "writer"
        failure: Exception
        try:
            response = await llm.generate_json(
                role=TOPIC_WRITER_ROLE,
                prompt=prompt,
                schema=TopicDraft,
            )
            draft = (
                response
                if isinstance(response, TopicDraft)
                else TopicDraft.model_validate(response)
            )
            if compose is not None:
                compose(draft)
            return draft
        except TopicCompositionError as exc:
            failure = exc
            step = "slide_composer"
        except (LLMSchemaError, ValidationError, ValueError) as exc:
            failure = exc

        if attempt == 1:
            feedback = str(failure)
            continue
        raise TopicWriterError(
            f"Topic writer failed after retry: {failure}", step=step
        ) from failure

    raise AssertionError("unreachable")


__all__ = ["TOPIC_WRITER_ROLE", "TopicWriterError", "write_topic"]
