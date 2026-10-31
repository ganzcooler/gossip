"""Writing and repairing complete Beitragstexte.

The writer deliberately never sees slide counts or layout limits. Slides are a
later, separate condensation step.
"""

import logging

from app.core import post_prompts
from app.core.post_models import ArticleDraft, FactCheckResult, SummaryBrief, TopicBrief
from app.services.llm_json import call_json

logger = logging.getLogger(__name__)


def write_summary_article(
    protocol_text: str, summary_brief: SummaryBrief
) -> ArticleDraft:
    """Write the complete summary article for a protocol."""
    prompt = post_prompts.render_prompt(
        post_prompts.SUMMARY_WRITER_PROMPT,
        SUMMARY_BRIEF=summary_brief.model_dump_json(indent=2),
        PROTOCOL_TEXT=protocol_text,
    )
    logger.debug("Writing summary article for '%s'", summary_brief.working_title)
    return call_json(
        prompt=prompt,
        model=ArticleDraft,
        call_label="summary_writer",
        max_tokens=16384,
        temperature=0.7,
    )


def write_topic_article(protocol_text: str, topic_brief: TopicBrief) -> ArticleDraft:
    """Write the complete article for one topic."""
    prompt = post_prompts.render_prompt(
        post_prompts.TOPIC_WRITER_PROMPT,
        TOPIC_BRIEF=topic_brief.model_dump_json(indent=2),
        PROTOCOL_TEXT=protocol_text,
    )
    logger.debug("Writing topic article for '%s'", topic_brief.working_title)
    return call_json(
        prompt=prompt,
        model=ArticleDraft,
        call_label=f"topic_writer:{topic_brief.slug}",
        max_tokens=16384,
        temperature=0.7,
    )


def repair_article(
    protocol_text: str,
    article: ArticleDraft,
    fact_check: FactCheckResult,
) -> ArticleDraft:
    """Rewrite an article after the fact-check gate found issues."""
    prompt = post_prompts.render_prompt(
        post_prompts.REPAIR_ARTICLE_PROMPT,
        ISSUES_JSON=fact_check.model_dump_json(indent=2),
        ARTICLE_JSON=article.model_dump_json(indent=2),
        PROTOCOL_TEXT=protocol_text,
    )
    logger.debug("Repairing article '%s'", article.title)
    return call_json(
        prompt=prompt,
        model=ArticleDraft,
        call_label="article_repair",
        max_tokens=16384,
        temperature=0.5,
    )


def article_to_markdown(article: ArticleDraft) -> str:
    """Render the structured article as a readable Markdown document."""
    parts = [f"# {article.title}", "", article.lead, ""]
    for section in article.sections:
        parts.append(f"## {section.heading}")
        parts.append("")
        for paragraph in section.paragraphs:
            parts.append(paragraph)
            parts.append("")
    if article.key_takeaways:
        parts.append("## Das Wichtigste in Kürze")
        parts.append("")
        for takeaway in article.key_takeaways:
            parts.append(f"- {takeaway}")
        parts.append("")
    return "\n".join(parts).strip()
