"""Deterministic image generation for the post renderers.

The injected LLM port returns raw image bytes. This module decodes them,
normalizes the result with a deterministic center fit, and substitutes the
family-pure brand fallback when the provider or the payload fails. An
authentication/account failure is never swallowed: it stops the job.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Callable
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageOps

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
        raise ImageGenerationError(
            f"Could not build the {label} brand fallback: {exc}"
        ) from exc
    if image.size != size:
        raise ImageGenerationError(
            f"{label} brand fallback has size {image.size}, expected {size}"
        )
    message = str(error) or error.__class__.__name__
    logger.warning("%s generation failed; using brand fallback: %s", label, message)
    return GeneratedImage(image=image, status=ASSET_STATUS_FALLBACK, error=message)


def _summary_fallback_result(error: Exception | str) -> GeneratedImage:
    return _fallback_result(
        error,
        factory=summary_fallback_art,
        label="Summary cover",
        size=SUMMARY_IMAGE_SIZE,
    )


async def generate_summary_cover(llm: LLMClient, prompt: str) -> GeneratedImage:
    """Generate and normalize the Summary cover art, or its brand fallback."""
    try:
        payload = await llm.generate_image(
            role=SUMMARY_COVER_ROLE,
            prompt=prompt,
            aspect_ratio=SUMMARY_ASPECT_RATIO,
        )
        image = normalize_image(decode_image_bytes(payload), SUMMARY_IMAGE_SIZE)
    except LLMAuthenticationError:
        raise
    except Exception as exc:
        return _summary_fallback_result(exc)
    return GeneratedImage(image=image, status=ASSET_STATUS_READY, error=None)


def _normalized_topic_art(payload: bytes) -> Image.Image:
    return normalize_image(decode_image_bytes(payload), TOPIC_IMAGE_SIZE)


async def generate_topic_cover(llm: LLMClient, prompt: str) -> GeneratedImage:
    """Generate and normalize the 1080x1350 topic cover art or its fallback."""
    try:
        payload = await llm.generate_image(
            role=TOPIC_COVER_ROLE,
            prompt=prompt,
            aspect_ratio=TOPIC_ASPECT_RATIO,
        )
        image = _normalized_topic_art(payload)
    except LLMAuthenticationError:
        raise
    except Exception as exc:
        return _fallback_result(
            exc,
            factory=topic_cover_fallback_art,
            label="Topic cover",
            size=TOPIC_IMAGE_SIZE,
        )
    return GeneratedImage(image=image, status=ASSET_STATUS_READY, error=None)


async def generate_topic_pair_art(llm: LLMClient, prompt: str) -> GeneratedImage:
    """Generate one 4:5 artwork and center-crop it to a 720x1350 pair."""
    try:
        payload = await llm.generate_image(
            role=TOPIC_PAIR_ROLE,
            prompt=prompt,
            aspect_ratio=TOPIC_ASPECT_RATIO,
        )
        image = _normalized_topic_art(payload).crop(TOPIC_PAIR_CROP)
    except LLMAuthenticationError:
        raise
    except Exception as exc:
        return _fallback_result(
            exc,
            factory=topic_pair_fallback_art,
            label="Topic pair artwork",
            size=TOPIC_PAIR_SIZE,
        )
    return GeneratedImage(image=image, status=ASSET_STATUS_READY, error=None)


async def generate_topic_single_art(llm: LLMClient, prompt: str) -> GeneratedImage:
    """Generate one 4:5 artwork and center-crop it to a 360x1350 strip."""
    try:
        payload = await llm.generate_image(
            role=TOPIC_SINGLE_ROLE,
            prompt=prompt,
            aspect_ratio=TOPIC_ASPECT_RATIO,
        )
        image = _normalized_topic_art(payload).crop(TOPIC_SINGLE_CROP)
    except LLMAuthenticationError:
        raise
    except Exception as exc:
        return _fallback_result(
            exc,
            factory=topic_single_fallback_art,
            label="Topic single artwork",
            size=TOPIC_SINGLE_SIZE,
        )
    return GeneratedImage(image=image, status=ASSET_STATUS_READY, error=None)


__all__ = [
    "ASSET_STATUS_FALLBACK",
    "ASSET_STATUS_READY",
    "GeneratedImage",
    "ImageGenerationError",
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
]
