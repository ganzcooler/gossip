"""Fact-check gate between writing and slide planning."""

import logging

from app.core import post_prompts
from app.core.post_models import ArticleDraft, FactCheckResult
from app.services.llm_json import call_json

logger = logging.getLogger(__name__)


def fact_check_article(protocol_text: str, article: ArticleDraft) -> FactCheckResult:
    """Compare an article against the protocol and report clear problems."""
    prompt = post_prompts.render_prompt(
        post_prompts.FACT_CHECK_PROMPT,
        ARTICLE_JSON=article.model_dump_json(indent=2),
        PROTOCOL_TEXT=protocol_text,
    )
    logger.debug("Fact-checking article '%s'", article.title)
    return call_json(
        prompt=prompt,
        model=FactCheckResult,
        call_label=f"fact_check:{article.title[:60]}",
        max_tokens=8192,
        temperature=0.2,
        reasoning_effort=None,
    )
