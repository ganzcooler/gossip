"""The stateless Redaktionsplaner role.

The planner is the only role that receives the full protocol text. It returns
a validated :class:`~app.core.post_models.EditorialPlan`; no conversation state
is kept between calls.
"""

from pydantic import ValidationError

from app.core.post_models import EditorialPlan
from app.core.post_prompts import build_planner_prompt
from app.services.llm_client import LLMClient, LLMSchemaError

PLANNER_ROLE = "planner"


async def plan_protocol(protocol, llm: LLMClient) -> EditorialPlan:
    """Plan one protocol into Summary briefs and optional topic briefs."""
    prompt = build_planner_prompt(
        protocol_title=protocol.title,
        session_date=protocol.session_date,
        protocol_text=protocol.pdf_text,
    )
    response = await llm.generate_json(
        role=PLANNER_ROLE,
        prompt=prompt,
        schema=EditorialPlan,
    )
    if isinstance(response, EditorialPlan):
        return response

    try:
        return EditorialPlan.model_validate(response)
    except ValidationError as exc:
        raise LLMSchemaError(
            f"Planner response did not match EditorialPlan: {exc}"
        ) from exc
