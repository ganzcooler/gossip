"""Decision-checked image generation for the post renderers.

The injected LLM port returns raw image bytes. This module decodes them,
normalizes the result with a deterministic center fit, and substitutes the
family-pure brand fallback when the provider or the payload fails. Generated
artwork is inspected by a decision model for unintended borders, blank areas,
panels or seams, overlays, rotation and recognizable minors before it is
accepted. Deliberate satirical exaggeration, unusual proportions and invented
scene details are not treated as defects.
An authentication/account failure is never swallowed: it stops the job.
"""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from app.core import config
from app.services.image_artifact_check import (
    ArtifactFinding,
    ArtifactVerdict,
    check_image_artifacts,
)
from app.services.llm_client import LLMAuthenticationError, LLMClient
from app.services.render_common import (
    BRAND_BLUE,
    BRAND_BLUE_DEEP,
    BRAND_ORANGE,
    BRAND_ORANGE_DEEP,
    SURFACE_BASE,
    SURFACE_SUNKEN,
)

logger = logging.getLogger(__name__)

SUMMARY_COVER_ROLE = "summary_cover"
SUMMARY_ASPECT_RATIO = "9:16"
SUMMARY_IMAGE_SIZE = (1080, 1920)

TOPIC_COVER_ROLE = "topic_cover"
TOPIC_PAIR_ROLE = "topic_pair_art"
TOPIC_SINGLE_ROLE = "topic_single_art"
TOPIC_ASPECT_RATIO = "4:5"
TOPIC_IMAGE_SIZE = (1080, 1350)
TOPIC_PAIR_SIZE = (720, 1350)
TOPIC_SINGLE_SIZE = (360, 1350)
TOPIC_PAIR_CROP = (180, 0, 900, 1350)
TOPIC_SINGLE_CROP = (360, 0, 720, 1350)

ASSET_STATUS_READY = "ready"
ASSET_STATUS_FALLBACK = "fallback"

IMAGE_STYLE_SUFFIX = (
    "Photorealistic editorial reportage photography with natural light, real "
    "materials and a believable scene. Continuous scene detail across the full "
    "frame; no empty margins or flat blank areas. One single continuous "
    "photograph; no illustration, cartoon, comic, drawing, watercolour or 3D "
    "render. No frame, border, passepartout, polaroid edge, diptych, triptych, "
    "multi-panel layout, picture-in-picture, collage, split screen or vignette."
)

COVER_SATIRE_SUFFIX = (
    "Give the cover a dry, gently sarcastic, slightly exaggerated editorial "
    "twist: exaggerate props, scale or everyday details for visual humour, "
    "while keeping the scene photorealistic, good-natured and free of "
    "caricatures of real people."
)

ARTIFACT_RETRY_SUFFIX = (
    "One single continuous full-bleed photograph that fills the entire frame "
    "edge to edge, with real scene detail all the way into every corner. "
    "Absolutely no white border, frame, blank band, white block, diptych, "
    "triptych, multi-panel layout, split-screen seam or empty margin."
)
MAX_IMAGE_ATTEMPTS = 2


class ImageGenerationError(Exception):
    """The provider payload or the deterministic fallback could not be used."""


@dataclass(frozen=True)
class GeneratedImage:
    """A normalized image plus the asset status it should be persisted with."""

    image: Image.Image
    status: str
    error: str | None = None


def decode_image_bytes(data: bytes) -> Image.Image:
    """Decode image bytes into an RGB Pillow image or raise a clear error."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            return image.convert("RGB")
    except (OSError, ValueError, TypeError) as exc:
        raise ImageGenerationError(f"Could not decode generated image: {exc}") from exc


def normalize_image(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Center-fit an image to exactly ``size`` with deterministic LANCZOS."""
    return ImageOps.fit(
        image.convert("RGB"),
        size,
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )


def with_image_style_suffix(prompt: str) -> str:
    """Append the deterministic realism/no-frame suffix exactly once."""
    prompt = prompt.strip()
    if prompt.endswith(IMAGE_STYLE_SUFFIX):
        return prompt
    return f"{prompt}\n\n{IMAGE_STYLE_SUFFIX}"


def with_cover_satire_suffix(prompt: str) -> str:
    """Append the cover-only satire suffix exactly once, before the style suffix."""
    prompt = prompt.strip()
    if COVER_SATIRE_SUFFIX in prompt:
        return prompt
    if prompt.endswith(IMAGE_STYLE_SUFFIX):
        base = prompt[: -len(IMAGE_STYLE_SUFFIX)].rstrip()
        return f"{base}\n\n{COVER_SATIRE_SUFFIX}\n\n{IMAGE_STYLE_SUFFIX}"
    return f"{prompt}\n\n{COVER_SATIRE_SUFFIX}"


def with_artifact_retry_suffix(prompt: str) -> str:
    """Append the full-bleed/no-artifact retry suffix exactly once."""
    prompt = prompt.strip()
    if prompt.endswith(ARTIFACT_RETRY_SUFFIX):
        return prompt
    return f"{prompt}\n\n{ARTIFACT_RETRY_SUFFIX}"


def _retry_prompt(prompt: str, findings: tuple[ArtifactFinding, ...]) -> str:
    attempt_prompt = with_artifact_retry_suffix(prompt)
    if findings:
        labels = ", ".join(finding.question for finding in findings)
        attempt_prompt = (
            f"{attempt_prompt}\n\nThe previous image failed the artifact check "
            f"for: {labels}. Avoid those defects in the new image."
        )
    return attempt_prompt


def _save_rejected_attempt(
    rejected_dir: Path | None,
    *,
    name: str,
    role: str,
    attempt: int,
    prompt: str,
    image: Image.Image,
    verdict: ArtifactVerdict,
) -> None:
    """Persist a rejected candidate and its verdict for manual diagnosis."""
    if rejected_dir is None:
        return

    status = "verifier-error" if verdict.error else "rejected"
    stem = f"{name}-attempt-{attempt}-{status}"
    try:
        rejected_dir.mkdir(parents=True, exist_ok=True)
        image.convert("RGB").save(rejected_dir / f"{stem}.png", format="PNG")
        metadata = {
            "name": name,
            "role": role,
            "attempt": attempt,
            "prompt": prompt,
            "image_size": list(image.size),
            "verifier_model": verdict.model,
            "thresholds": config.IMAGE_ARTIFACT_THRESHOLDS,
            "findings": [
                {
                    "question": finding.question,
                    "probability": finding.probability,
                    "confidence": finding.confidence,
                }
                for finding in verdict.findings
            ],
            "error": verdict.error,
        }
        (rejected_dir / f"{stem}.json").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Saved rejected image attempt: %s", rejected_dir / f"{stem}.png")
    except Exception as exc:  # pragma: no cover - diagnostics must not break the run
        logger.warning("Could not save rejected image attempt %s: %s", stem, exc)


def summary_fallback_art() -> Image.Image:
    """Return the flat, family-pure Summary fallback from the design contract."""
    image = Image.new("RGB", SUMMARY_IMAGE_SIZE, SURFACE_SUNKEN)
    draw = ImageDraw.Draw(image)
    draw.rectangle((720, 0, 1079, 1919), fill=BRAND_BLUE_DEEP)
    draw.rectangle((710, 0, 719, 1919), fill=BRAND_BLUE)
    draw.rectangle((0, 1450, 709, 1459), fill=BRAND_BLUE)
    draw.rectangle((0, 1680, 239, 1919), fill=BRAND_BLUE_DEEP)
    return image


def topic_cover_fallback_art() -> Image.Image:
    """Return the flat, family-pure topic cover fallback from the design."""
    image = Image.new("RGB", TOPIC_IMAGE_SIZE, SURFACE_BASE)
    draw = ImageDraw.Draw(image)
    draw.rectangle((720, 0, 1079, 1349), fill=BRAND_ORANGE_DEEP)
    draw.rectangle((710, 0, 719, 1349), fill=BRAND_ORANGE)
    draw.rectangle((0, 900, 709, 909), fill=BRAND_ORANGE)
    draw.rectangle((0, 1150, 239, 1349), fill=BRAND_ORANGE_DEEP)
    return image


def topic_pair_fallback_art() -> Image.Image:
    """Return the flat 720x1350 topic pair fallback from the design."""
    image = Image.new("RGB", TOPIC_PAIR_SIZE, SURFACE_BASE)
    draw = ImageDraw.Draw(image)
    draw.rectangle((180, 300, 539, 1049), fill=BRAND_ORANGE_DEEP)
    draw.rectangle((355, 0, 364, 1349), fill=BRAND_ORANGE)
    draw.rectangle((0, 900, 719, 909), fill=BRAND_ORANGE)
    return image


def topic_single_fallback_art() -> Image.Image:
    """Return the standalone 360x1350 fallback for an unpaired last slide."""
    return topic_pair_fallback_art().crop((180, 0, 540, 1350))


def _fallback_result(
    error: Exception | str,
    *,
    factory: Callable[[], Image.Image],
    label: str,
    size: tuple[int, int],
) -> GeneratedImage:
    try:
        image = factory()
    except Exception as exc:  # pragma: no cover - Pillow drawing is deterministic
        raise ImageGenerationError(f"Could not build the {label} brand fallback: {exc}") from exc
    if image.size != size:
        raise ImageGenerationError(f"{label} brand fallback has size {image.size}, expected {size}")
    message = str(error) or error.__class__.__name__
    logger.warning("%s generation failed; using brand fallback: %s", label, message)
    return GeneratedImage(image=image, status=ASSET_STATUS_FALLBACK, error=message)


async def _generate_guarded_art(
    llm: LLMClient,
    prompt: str,
    *,
    role: str,
    aspect_ratio: str,
    label: str,
    size: tuple[int, int],
    finalize: Callable[[Image.Image], Image.Image],
    fallback: Callable[[], Image.Image],
    rejected_dir: Path | None = None,
    rejected_name: str | None = None,
) -> GeneratedImage:
    """Generate one final asset, retrying once when the decision model objects."""
    style_prompt = with_image_style_suffix(prompt)
    findings: tuple[ArtifactFinding, ...] = ()
    rejections: list[str] = []
    verdict = None

    for attempt in range(1, MAX_IMAGE_ATTEMPTS + 1):
        attempt_prompt = style_prompt if attempt == 1 else _retry_prompt(style_prompt, findings)
        try:
            payload = await llm.generate_image(
                role=role,
                prompt=attempt_prompt,
                aspect_ratio=aspect_ratio,
            )
            image = finalize(decode_image_bytes(payload))
            verdict = await check_image_artifacts(
                llm,
                image,
                role=f"{role}_artifact_check",
            )
        except LLMAuthenticationError:
            raise
        except Exception as exc:
            return _fallback_result(
                exc,
                factory=fallback,
                label=label,
                size=size,
            )

        if verdict.clean:
            return GeneratedImage(image=image, status=ASSET_STATUS_READY, error=None)

        _save_rejected_attempt(
            rejected_dir,
            name=rejected_name or role,
            role=role,
            attempt=attempt,
            prompt=attempt_prompt,
            image=image,
            verdict=verdict,
        )

        if verdict.error:
            return _fallback_result(
                ImageGenerationError(f"{label} artifact check failed: {verdict.error}"),
                factory=fallback,
                label=label,
                size=size,
            )

        findings = verdict.findings
        rejections.append(f"attempt {attempt}: {verdict.summary()}")
        logger.warning(
            "%s generation attempt %s/%s rejected by the %s artifact check: %s",
            label,
            attempt,
            MAX_IMAGE_ATTEMPTS,
            verdict.model,
            verdict.summary(),
        )

    assert verdict is not None
    return _fallback_result(
        ImageGenerationError(
            f"{label} artwork failed the {verdict.model} artifact check after "
            f"{MAX_IMAGE_ATTEMPTS} attempts: {'; '.join(rejections)}"
        ),
        factory=fallback,
        label=label,
        size=size,
    )


async def generate_summary_cover(
    llm: LLMClient,
    prompt: str,
    *,
    rejected_dir: Path | None = None,
    rejected_name: str | None = None,
) -> GeneratedImage:
    """Generate and normalize the Summary cover art, or its brand fallback."""
    return await _generate_guarded_art(
        llm,
        with_cover_satire_suffix(prompt),
        role=SUMMARY_COVER_ROLE,
        aspect_ratio=SUMMARY_ASPECT_RATIO,
        label="Summary cover",
        size=SUMMARY_IMAGE_SIZE,
        finalize=lambda image: normalize_image(image, SUMMARY_IMAGE_SIZE),
        fallback=summary_fallback_art,
        rejected_dir=rejected_dir,
        rejected_name=rejected_name,
    )


def _normalized_topic_art(image: Image.Image) -> Image.Image:
    return normalize_image(image, TOPIC_IMAGE_SIZE)


async def generate_topic_cover(
    llm: LLMClient,
    prompt: str,
    *,
    rejected_dir: Path | None = None,
    rejected_name: str | None = None,
) -> GeneratedImage:
    """Generate and normalize the 1080x1350 topic cover art or its fallback."""
    return await _generate_guarded_art(
        llm,
        with_cover_satire_suffix(prompt),
        role=TOPIC_COVER_ROLE,
        aspect_ratio=TOPIC_ASPECT_RATIO,
        label="Topic cover",
        size=TOPIC_IMAGE_SIZE,
        finalize=_normalized_topic_art,
        fallback=topic_cover_fallback_art,
        rejected_dir=rejected_dir,
        rejected_name=rejected_name,
    )


async def generate_topic_pair_art(
    llm: LLMClient,
    prompt: str,
    *,
    rejected_dir: Path | None = None,
    rejected_name: str | None = None,
) -> GeneratedImage:
    """Generate one 4:5 artwork and center-crop it to a 720x1350 pair."""
    return await _generate_guarded_art(
        llm,
        prompt,
        role=TOPIC_PAIR_ROLE,
        aspect_ratio=TOPIC_ASPECT_RATIO,
        label="Topic pair artwork",
        size=TOPIC_PAIR_SIZE,
        finalize=lambda image: _normalized_topic_art(image).crop(TOPIC_PAIR_CROP),
        fallback=topic_pair_fallback_art,
        rejected_dir=rejected_dir,
        rejected_name=rejected_name,
    )


async def generate_topic_single_art(
    llm: LLMClient,
    prompt: str,
    *,
    rejected_dir: Path | None = None,
    rejected_name: str | None = None,
) -> GeneratedImage:
    """Generate one 4:5 artwork and center-crop it to a 360x1350 strip."""
    return await _generate_guarded_art(
        llm,
        prompt,
        role=TOPIC_SINGLE_ROLE,
        aspect_ratio=TOPIC_ASPECT_RATIO,
        label="Topic single artwork",
        size=TOPIC_SINGLE_SIZE,
        finalize=lambda image: _normalized_topic_art(image).crop(TOPIC_SINGLE_CROP),
        fallback=topic_single_fallback_art,
        rejected_dir=rejected_dir,
        rejected_name=rejected_name,
    )


__all__ = [
    "ARTIFACT_RETRY_SUFFIX",
    "ASSET_STATUS_FALLBACK",
    "ASSET_STATUS_READY",
    "COVER_SATIRE_SUFFIX",
    "GeneratedImage",
    "IMAGE_STYLE_SUFFIX",
    "ImageGenerationError",
    "MAX_IMAGE_ATTEMPTS",
    "SUMMARY_ASPECT_RATIO",
    "SUMMARY_COVER_ROLE",
    "SUMMARY_IMAGE_SIZE",
    "TOPIC_ASPECT_RATIO",
    "TOPIC_COVER_ROLE",
    "TOPIC_IMAGE_SIZE",
    "TOPIC_PAIR_CROP",
    "TOPIC_PAIR_ROLE",
    "TOPIC_PAIR_SIZE",
    "TOPIC_SINGLE_CROP",
    "TOPIC_SINGLE_ROLE",
    "TOPIC_SINGLE_SIZE",
    "decode_image_bytes",
    "generate_summary_cover",
    "generate_topic_cover",
    "generate_topic_pair_art",
    "generate_topic_single_art",
    "normalize_image",
    "summary_fallback_art",
    "topic_cover_fallback_art",
    "topic_pair_fallback_art",
    "topic_single_fallback_art",
    "with_artifact_retry_suffix",
    "with_cover_satire_suffix",
    "with_image_style_suffix",
]
