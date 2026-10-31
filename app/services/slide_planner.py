"""Semantic slide planning and deterministic fallback pagination.

The planner decides *what* text belongs on each slide. It never decides line
breaks, font sizes, or pixel positions. If the planner output is structurally
invalid, a deterministic `<h2>`/paragraph paginator produces a safe plan.
"""

import logging
import re

from app.core import post_prompts
from app.core.post_models import (
    ArticleDraft,
    CoverPlan,
    SlideContent,
    SummarySlidePlan,
    TopicSlidePair,
    TopicSlidePlan,
)
from app.services.errors import AuthenticationError, PostGenerationError, SlidePlanError
from app.services.llm_json import call_json

logger = logging.getLogger(__name__)

MIN_SUMMARY_SLIDES = 3
MAX_SUMMARY_SLIDES = 8
MIN_TOPIC_SLIDES = 2
MAX_TOPIC_SLIDES = 8
MAX_SLIDE_BODY = 300
MAX_SLIDE_HEADLINE = 120
MAX_SLIDE_LABEL = 40
MAX_COVER_HEADLINE = 120


def _normalise_summary_plan(plan: SummarySlidePlan) -> SummarySlidePlan:
    plan.cover.kicker = "SITZUNG KOMPAKT"
    return plan


def _normalise_topic_plan(plan: TopicSlidePlan) -> TopicSlidePlan:
    plan.cover.kicker = "THEMA IM FOKUS"
    return plan


def validate_summary_plan(plan: SummarySlidePlan) -> None:
    if not plan.cover.headline.strip() or not plan.cover.image_brief.strip():
        raise SlidePlanError("Summary cover is missing headline or image brief")
    if len(plan.cover.headline) > MAX_COVER_HEADLINE:
        raise SlidePlanError("Summary cover headline is too long")
    if not (MIN_SUMMARY_SLIDES <= len(plan.slides) <= MAX_SUMMARY_SLIDES):
        raise SlidePlanError(
            f"Summary plan has {len(plan.slides)} slides; expected "
            f"{MIN_SUMMARY_SLIDES}-{MAX_SUMMARY_SLIDES}"
        )
    for slide in plan.slides:
        _validate_slide(slide)


def validate_topic_plan(plan: TopicSlidePlan) -> None:
    if not plan.cover.headline.strip() or not plan.cover.image_brief.strip():
        raise SlidePlanError("Topic cover is missing headline or image brief")
    if len(plan.cover.headline) > MAX_COVER_HEADLINE:
        raise SlidePlanError("Topic cover headline is too long")
    slide_count = len(plan.pairs) * 2
    if not (MIN_TOPIC_SLIDES <= slide_count <= MAX_TOPIC_SLIDES):
        raise SlidePlanError(
            f"Topic plan has {slide_count} content slides; expected "
            f"{MIN_TOPIC_SLIDES}-{MAX_TOPIC_SLIDES}"
        )
    for pair in plan.pairs:
        if len(pair.slides) != 2:
            raise SlidePlanError("Every topic pair must contain exactly two slides")
        if not pair.artwork_brief.strip():
            raise SlidePlanError("Topic pair is missing an artwork brief")
        for slide in pair.slides:
            _validate_slide(slide)


def _validate_slide(slide: SlideContent) -> None:
    if not slide.headline.strip() or not slide.body.strip():
        raise SlidePlanError("Slide is missing headline or body")
    if len(slide.headline) > MAX_SLIDE_HEADLINE:
        raise SlidePlanError("Slide headline is too long")
    if len(slide.body) > MAX_SLIDE_BODY:
        raise SlidePlanError("Slide body is too long")
    if slide.label and len(slide.label) > MAX_SLIDE_LABEL:
        raise SlidePlanError("Slide label is too long")


def plan_summary_slides(
    article: ArticleDraft, *, allow_fallback: bool = True
) -> SummarySlidePlan:
    """Ask the planner for summary slides, falling back deterministically."""
    prompt = post_prompts.render_prompt(
        post_prompts.SUMMARY_SLIDE_PLAN_PROMPT,
        ARTICLE_JSON=article.model_dump_json(indent=2),
    )
    try:
        plan = call_json(
            prompt=prompt,
            model=SummarySlidePlan,
            call_label="summary_slide_plan",
            max_tokens=8192,
            temperature=0.4,
            reasoning_effort="medium",
        )
        plan = _normalise_summary_plan(plan)
        validate_summary_plan(plan)
        return plan
    except AuthenticationError:
        raise
    except (PostGenerationError, SlidePlanError) as exc:
        logger.warning("Summary slide planning failed: %s", exc)
        if not allow_fallback:
            raise
        return fallback_summary_slides(article)


def plan_topic_slides(
    article: ArticleDraft, *, allow_fallback: bool = True
) -> TopicSlidePlan:
    """Ask the planner for topic slides, falling back deterministically."""
    prompt = post_prompts.render_prompt(
        post_prompts.TOPIC_SLIDE_PLAN_PROMPT,
        ARTICLE_JSON=article.model_dump_json(indent=2),
    )
    try:
        plan = call_json(
            prompt=prompt,
            model=TopicSlidePlan,
            call_label="topic_slide_plan",
            max_tokens=8192,
            temperature=0.4,
            reasoning_effort="medium",
        )
        plan = _normalise_topic_plan(plan)
        validate_topic_plan(plan)
        return plan
    except AuthenticationError:
        raise
    except (PostGenerationError, SlidePlanError) as exc:
        logger.warning("Topic slide planning failed: %s", exc)
        if not allow_fallback:
            raise
        return fallback_topic_slides(article)


def repair_summary_slides(
    article: ArticleDraft, plan: SummarySlidePlan, overflow: str
) -> SummarySlidePlan:
    """Repair overflowing summary slides, then fall back if needed."""
    prompt = post_prompts.render_prompt(
        post_prompts.SLIDE_REPAIR_PROMPT,
        OVERFLOW=overflow,
        PLAN_JSON=plan.model_dump_json(indent=2),
        ARTICLE_JSON=article.model_dump_json(indent=2),
    )
    try:
        repaired = call_json(
            prompt=prompt,
            model=SummarySlidePlan,
            call_label="summary_slide_repair",
            max_tokens=8192,
            temperature=0.3,
            reasoning_effort="medium",
        )
        repaired = _normalise_summary_plan(repaired)
        validate_summary_plan(repaired)
        return repaired
    except AuthenticationError:
        raise
    except (PostGenerationError, SlidePlanError) as exc:
        logger.warning("Summary slide repair failed: %s", exc)
        return fallback_summary_slides(article)


def repair_topic_slides(
    article: ArticleDraft, plan: TopicSlidePlan, overflow: str
) -> TopicSlidePlan:
    """Repair overflowing topic slides, then fall back if needed."""
    prompt = post_prompts.render_prompt(
        post_prompts.SLIDE_REPAIR_PROMPT,
        OVERFLOW=overflow,
        PLAN_JSON=plan.model_dump_json(indent=2),
        ARTICLE_JSON=article.model_dump_json(indent=2),
    )
    try:
        repaired = call_json(
            prompt=prompt,
            model=TopicSlidePlan,
            call_label="topic_slide_repair",
            max_tokens=8192,
            temperature=0.3,
            reasoning_effort="medium",
        )
        repaired = _normalise_topic_plan(repaired)
        validate_topic_plan(repaired)
        return repaired
    except AuthenticationError:
        raise
    except (PostGenerationError, SlidePlanError) as exc:
        logger.warning("Topic slide repair failed: %s", exc)
        return fallback_topic_slides(article)


def fallback_summary_slides(article: ArticleDraft) -> SummarySlidePlan:
    """Deterministic `<h2>`/paragraph pagination for summaries."""
    slides: list[SlideContent] = []
    for section in article.sections:
        slides.append(
            SlideContent(
                label=_label_from_heading(section.heading),
                headline=_shorten(section.heading, 60),
                body=_condense_text(section.paragraphs, 220),
            )
        )

    for takeaway in article.key_takeaways:
        if len(slides) >= MIN_SUMMARY_SLIDES:
            break
        slides.append(
            SlideContent(
                label="KERNPUNKT",
                headline=_shorten(takeaway, 60),
                body=_shorten(takeaway, 220),
            )
        )

    if not slides:
        slides.append(
            SlideContent(
                label="ÜBERBLICK",
                headline=_shorten(article.title, 60),
                body=_shorten(article.lead, 220),
            )
        )

    while len(slides) < MIN_SUMMARY_SLIDES:
        slides.append(
            SlideContent(
                label="ÜBERBLICK",
                headline=_shorten(article.title, 60),
                body=_shorten(article.lead, 220),
            )
        )

    if len(slides) > MAX_SUMMARY_SLIDES:
        tail = " ".join(slide.headline for slide in slides[7:])
        slides = slides[:7] + [
            SlideContent(
                label="AUSBLICK",
                headline="Das Wichtigste im Überblick",
                body=_shorten(tail, 220),
            )
        ]

    cover = CoverPlan(
        kicker="SITZUNG KOMPAKT",
        headline=_shorten(article.title, 80),
        image_brief=article.lead,
    )
    return SummarySlidePlan(cover=cover, slides=slides)


def fallback_topic_slides(article: ArticleDraft) -> TopicSlidePlan:
    """Deterministic `<h2>`/paragraph pagination for topic posts."""
    slides: list[SlideContent] = []
    for section in article.sections:
        slides.append(
            SlideContent(
                label=_label_from_heading(section.heading),
                headline=_shorten(section.heading, 50),
                body=_condense_text(section.paragraphs, 160),
            )
        )

    if not slides:
        slides.append(
            SlideContent(
                label="ÜBERBLICK",
                headline=_shorten(article.title, 50),
                body=_shorten(article.lead, 160),
            )
        )

    while len(slides) < MIN_TOPIC_SLIDES:
        slides.append(
            SlideContent(
                label="AUSBLICK",
                headline="Was als Nächstes passiert",
                body=_shorten(article.lead, 160),
            )
        )

    if len(slides) % 2 == 1:
        fallback_body = " ".join(article.key_takeaways) or article.lead
        slides.append(
            SlideContent(
                label="AUSBLICK",
                headline="Was als Nächstes passiert",
                body=_shorten(fallback_body, 160),
            )
        )

    if len(slides) > MAX_TOPIC_SLIDES:
        slides = slides[:MAX_TOPIC_SLIDES]
        if len(slides) % 2 == 1:
            slides = slides[:-1]

    pairs = []
    for index in range(0, len(slides), 2):
        pair_slides = slides[index : index + 2]
        pairs.append(
            TopicSlidePair(
                slides=pair_slides,
                artwork_brief=_fallback_artwork_brief(pair_slides),
            )
        )

    cover = CoverPlan(
        kicker="THEMA IM FOKUS",
        headline=_shorten(article.title, 80),
        image_brief=article.lead,
    )
    return TopicSlidePlan(cover=cover, pairs=pairs)


def _fallback_artwork_brief(pair: list[SlideContent]) -> str:
    headlines = " / ".join(slide.headline for slide in pair)
    return (
        f"Editorial scene illustrating {headlines}. One coherent composition "
        "with a calm vertical center, no text."
    )


_LABEL_HINTS = {
    "was": "BESCHLUSS",
    "wie": "AUSBLICK",
    "warum": "HINTERGRUND",
    "das": "HINTERGRUND",
    "optik": "KOSTEN",
    "finanzierung": "FINANZEN",
    "kosten": "KOSTEN",
    "fragen": "BÜRGERFRAGEN",
    "weitere": "WEITERE",
    "sachstand": "SACHSTAND",
    "anträge": "ANTRÄGE",
}

_STOPWORDS = {
    "der",
    "die",
    "das",
    "und",
    "in",
    "am",
    "aus",
    "mit",
    "für",
    "von",
    "im",
    "zur",
    "zum",
}


def _label_from_heading(heading: str) -> str:
    cleaned = re.sub(r"[^\w\sÄÖÜäöüß-]", "", heading).strip()
    words = cleaned.split()
    if not words:
        return "ÜBERBLICK"
    first = re.sub(r"[^\wÄÖÜäöüß-]", "", words[0]).lower()
    if first in _LABEL_HINTS:
        return _LABEL_HINTS[first]
    filtered = [word for word in words if word.lower() not in _STOPWORDS]
    label = " ".join((filtered or words)[:2]).upper()
    return label[:MAX_SLIDE_LABEL] or "ÜBERBLICK"


def _shorten(text: str, max_length: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_length:
        return text
    cut = text[: max_length - 1].rsplit(" ", 1)[0].rstrip(".,;:")
    return f"{cut}…"


def _condense_text(paragraphs: list[str], max_length: int) -> str:
    text = re.sub(r"\s+", " ", " ".join(p.strip() for p in paragraphs if p.strip()))
    if len(text) <= max_length:
        return text

    # Do not split after a day number ("24. September") or inside common
    # abbreviations. The old naive split produced fragments such as
    # "In der Sitzung am 24." and then dropped the rest of the sentence.
    sentences = re.split(r"(?<!\d)(?<=[.!?])\s+(?=[A-ZÄÖÜ])", text)
    abbreviations = ("z.B.", "d.h.", "Nr.", "Dr.", "ca.", "bzw.", "u.a.", "vgl.", "etc.")
    merged: list[str] = []
    for sentence in sentences:
        if merged and merged[-1].endswith(abbreviations):
            merged[-1] = f"{merged[-1]} {sentence}"
        else:
            merged.append(sentence)

    result = ""
    for sentence in merged:
        candidate = f"{result} {sentence}".strip()
        if len(candidate) <= max_length:
            result = candidate
        elif not result:
            return _shorten(sentence, max_length)
        else:
            break
    return result or _shorten(text, max_length)
