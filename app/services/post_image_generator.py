"""Image prompts, image generation, and captions for the new posts."""

import logging
import time

from app.core import config, post_prompts
from app.core.post_models import (
    ArticleDraft,
    CaptionResult,
    CoverPlan,
    TopicSlidePair,
    TopicSlidePlan,
)
from app.services.errors import PostGenerationError
from app.services import openrouter_client
from app.services.cost_tracker import record_usage
from app.services.llm_json import call_json, call_text

logger = logging.getLogger(__name__)


def _ensure_photorealistic(prompt: str) -> str:
    """Cheap guard against comic/animation prompts without an extra LLM call."""
    cleaned = prompt.strip()
    lower = cleaned.lower()
    if "photorealistic" in lower or "photo-realistic" in lower:
        return cleaned
    return f"{cleaned} Photorealistic editorial photography, natural light."


def generate_summary_cover_prompt(article: ArticleDraft, cover: CoverPlan) -> str:
    prompt = post_prompts.render_prompt(
        post_prompts.SUMMARY_COVER_IMAGE_PROMPT,
        COVER_HEADLINE=cover.headline,
        ARTICLE_JSON=article.model_dump_json(indent=2),
    )
    return _ensure_photorealistic(
        call_text(
            prompt=prompt,
            call_label="summary_cover_prompt",
            max_tokens=4096,
            temperature=0.8,
            reasoning_effort="medium",
        )
    )


def generate_topic_cover_prompt(article: ArticleDraft, cover: CoverPlan) -> str:
    prompt = post_prompts.render_prompt(
        post_prompts.TOPIC_COVER_IMAGE_PROMPT,
        COVER_HEADLINE=cover.headline,
        ARTICLE_JSON=article.model_dump_json(indent=2),
    )
    return _ensure_photorealistic(
        call_text(
            prompt=prompt,
            call_label="topic_cover_prompt",
            max_tokens=4096,
            temperature=0.8,
            reasoning_effort="medium",
        )
    )


def generate_topic_artwork_prompt(
    article: ArticleDraft, pair: TopicSlidePair
) -> str:
    prompt = post_prompts.render_prompt(
        post_prompts.TOPIC_ARTWORK_IMAGE_PROMPT,
        PAIR_JSON=pair.model_dump_json(indent=2),
        ARTICLE_JSON=article.model_dump_json(indent=2),
    )
    return _ensure_photorealistic(
        call_text(
            prompt=prompt,
            call_label="topic_artwork_prompt",
            max_tokens=4096,
            temperature=0.8,
            reasoning_effort="medium",
        )
    )


def generate_topic_caption(
    article: ArticleDraft, plan: TopicSlidePlan
) -> CaptionResult:
    prompt = post_prompts.render_prompt(
        post_prompts.TOPIC_CAPTION_PROMPT,
        ARTICLE_JSON=article.model_dump_json(indent=2),
        SLIDE_PLAN_JSON=plan.model_dump_json(indent=2),
    )
    return call_json(
        prompt=prompt,
        model=CaptionResult,
        call_label="topic_caption",
        max_tokens=2048,
        temperature=0.6,
        reasoning_effort="medium",
    )


def generate_image_bytes(prompt: str, aspect_ratio: str) -> bytes:
    """Generate one image and fail loudly when the provider returns nothing."""
    logger.info(
        "Image generation start aspect=%s prompt_chars=%s", aspect_ratio, len(prompt)
    )
    last_error: Exception | None = None
    for attempt in range(1, 6):
        try:
            result = openrouter_client.generate_image_result(
                model=config.OPENROUTER_IMAGE_MODEL,
                prompt=prompt,
                aspect_ratio=aspect_ratio,
            )
            record_usage(result.usage)
            cost = result.usage.get("cost")
            logger.info(
                "Image generation ok aspect=%s bytes=%s attempt=%s/5 cost_usd=%s",
                aspect_ratio,
                len(result.image_bytes),
                attempt,
                f"{cost:.6f}" if isinstance(cost, (int, float)) else "n/a",
            )
            return result.image_bytes
        except Exception as exc:
            last_error = exc
            logger.error(
                "Image generation failed on attempt %s/5: %s",
                attempt,
                exc,
                exc_info=True,
            )
            if attempt < 5:
                time.sleep(config.API_CALL_DELAY_SECONDS)

    raise PostGenerationError(
        f"Image generation failed after 5 attempts for {aspect_ratio}: {last_error}"
    )
