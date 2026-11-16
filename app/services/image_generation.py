"""Deterministic image generation for the post renderers.

The injected LLM port returns raw image bytes. This module decodes them,
normalizes the result with a deterministic center fit, and substitutes the
family-pure brand fallback when the provider or the payload fails. An
authentication/account failure is never swallowed: it stops the job.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageOps

from app.services.llm_client import LLMAuthenticationError, LLMClient

logger = logging.getLogger(__name__)

SUMMARY_COVER_ROLE = "summary_cover"
SUMMARY_ASPECT_RATIO = "9:16"
SUMMARY_IMAGE_SIZE = (1080, 1920)

ASSET_STATUS_READY = "ready"
ASSET_STATUS_FALLBACK = "fallback"

SURFACE_BASE = (23, 23, 26)
BRAND_BLUE = (30, 123, 181)
BRAND_BLUE_DEEP = (21, 90, 133)


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
    image = Image.new("RGB", SUMMARY_IMAGE_SIZE, SURFACE_BASE)
    draw = ImageDraw.Draw(image)
    draw.rectangle((720, 0, 1079, 1919), fill=BRAND_BLUE_DEEP)
    draw.rectangle((710, 0, 719, 1919), fill=BRAND_BLUE)
    draw.rectangle((0, 1450, 709, 1459), fill=BRAND_BLUE)
    draw.rectangle((0, 1680, 239, 1919), fill=BRAND_BLUE_DEEP)
    return image


def _fallback_result(error: Exception | str) -> GeneratedImage:
    try:
        image = summary_fallback_art()
    except Exception as exc:  # pragma: no cover - Pillow drawing is deterministic
        raise ImageGenerationError(
            f"Could not build the Summary brand fallback: {exc}"
        ) from exc
    message = str(error) or error.__class__.__name__
    logger.warning("Summary cover generation failed; using brand fallback: %s", message)
    return GeneratedImage(image=image, status=ASSET_STATUS_FALLBACK, error=message)


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
        return _fallback_result(exc)
    return GeneratedImage(image=image, status=ASSET_STATUS_READY, error=None)


__all__ = [
    "ASSET_STATUS_FALLBACK",
    "ASSET_STATUS_READY",
    "GeneratedImage",
    "ImageGenerationError",
    "SUMMARY_ASPECT_RATIO",
    "SUMMARY_COVER_ROLE",
    "SUMMARY_IMAGE_SIZE",
    "decode_image_bytes",
    "generate_summary_cover",
    "normalize_image",
    "summary_fallback_art",
]
