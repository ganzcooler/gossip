"""Editorial planning for a protocol.

One fresh-context call selects the summary focus and the topic briefs. The
result is stored once per protocol so retries do not pick a different set of
topics.
"""

import logging

from app.core import post_prompts
from app.core.post_models import EditorialPlan
from app.services.llm_json import call_json

logger = logging.getLogger(__name__)


def plan_editorial(protocol_text: str) -> EditorialPlan:
    """Select the summary focus and topic briefs for one protocol."""
    prompt = post_prompts.render_prompt(
        post_prompts.EDITORIAL_PLAN_PROMPT,
        PROTOCOL_TEXT=protocol_text,
    )
    logger.debug("Generating editorial plan")
    return call_json(
        prompt=prompt,
        model=EditorialPlan,
        call_label="editorial_plan",
        max_tokens=8192,
        temperature=0.3,
        reasoning_effort="medium",
    )
