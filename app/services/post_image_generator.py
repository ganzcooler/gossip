"""Image prompts, image generation, and captions for the new posts."""

import logging

from app.core import post_prompts
from app.core.post_models import (
    ArticleDraft,
    CaptionResult,
    CoverPlan,
    TopicSlidePair,
    TopicSlidePlan,
)
from app.services.errors import PostGenerationError
from app.services.image_generator import generate_image
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
        call_text(prompt=prompt, max_tokens=1024, temperature=0.8)
    )


def generate_topic_cover_prompt(article: ArticleDraft, cover: CoverPlan) -> str:
    prompt = post_prompts.render_prompt(
        post_prompts.TOPIC_COVER_IMAGE_PROMPT,
        COVER_HEADLINE=cover.headline,
        ARTICLE_JSON=article.model_dump_json(indent=2),
    )
    return _ensure_photorealistic(
        call_text(prompt=prompt, max_tokens=1024, temperature=0.8)
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
        call_text(prompt=prompt, max_tokens=1024, temperature=0.8)
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
        max_tokens=512,
        temperature=0.6,
    )


def generate_image_bytes(prompt: str, aspect_ratio: str) -> bytes:
    """Generate one image and fail loudly when the provider returns nothing."""
    image_bytes = generate_image(prompt, aspect_ratio=aspect_ratio)
    if not image_bytes:
        raise PostGenerationError(f"Image generation returned no data for {aspect_ratio}")
    return image_bytes
