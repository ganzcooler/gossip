"""Deterministic image generation for the post renderers.

The injected LLM port returns raw image bytes. This module decodes them,
normalizes the result with a deterministic center fit, and substitutes the
family-pure brand fallback when the provider or the payload fails. Generated
artwork is also checked for near-white generation artifacts (borders, flat
blocks, edge bands and split-screen seams) before it is accepted. An
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

IMAGE_STYLE_SUFFIX = (
    "Photorealistic editorial reportage photography with natural light, real "
    "materials and a believable scene. No illustration, cartoon, comic, drawing, "
    "watercolour or 3D render. No frame, border, passepartout, polaroid edge, "
    "picture-in-picture, collage, split screen or vignette."
)

ARTIFACT_RETRY_SUFFIX = (
    "Full-bleed single photograph that fills the entire frame edge to edge, "
    "with real scene detail all the way into every corner. Absolutely no white "
    "border, frame, blank band, white block, split-screen seam or empty margin."
)
MAX_IMAGE_ATTEMPTS = 2

# Near-white artifact detection. The thresholds are deliberately conservative:
# normal flat-colour or photographic artwork stays clean, while the flat white
# bands, blocks, frames and split-screen seams seen from the provider do not.
ARTIFACT_NEAR_WHITE_LUMINANCE = 240
ARTIFACT_BORDER_WIDTHS = (2, 3, 4)
ARTIFACT_BORDER_MIN_WHITE_RATIO = 0.90
ARTIFACT_BLOCK_SIZE = 45
ARTIFACT_BLOCK_MIN_WHITE = 250
ARTIFACT_FLAT_LUMINANCE_RANGE = 12
ARTIFACT_MIN_FLAT_AREA_RATIO = 0.04
ARTIFACT_EDGE_BAND_RATIO = 0.03
ARTIFACT_EDGE_BAND_MIN_WHITE = 242
ARTIFACT_EDGE_BAND_MIN_MEAN = 245
ARTIFACT_SEAM_MAX_WIDTH = 12
ARTIFACT_SEAM_MIN_WHITE = 230
ARTIFACT_SEAM_MIN_MEAN = 220
ARTIFACT_SEAM_CONTEXT = 4
ARTIFACT_SEAM_MIN_CONTRAST = 50
ARTIFACT_SEAM_MAX_CONTEXT_MEAN = 210

_NEAR_WHITE_LUT = [0] * ARTIFACT_NEAR_WHITE_LUMINANCE + [255] * (
    256 - ARTIFACT_NEAR_WHITE_LUMINANCE
)


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


def with_artifact_retry_suffix(prompt: str) -> str:
    """Append the full-bleed/no-artifact retry suffix exactly once."""
    prompt = prompt.strip()
    if prompt.endswith(ARTIFACT_RETRY_SUFFIX):
        return prompt
    return f"{prompt}\n\n{ARTIFACT_RETRY_SUFFIX}"


def _near_white_mask(gray: Image.Image) -> Image.Image:
    return gray.point(_NEAR_WHITE_LUT)


def _border_artifact(mask: Image.Image) -> str | None:
    """Reject a mostly near-white ring around the outer image edge."""
    width, height = mask.size
    for ring in ARTIFACT_BORDER_WIDTHS:
        if width <= 2 * ring or height <= 2 * ring:
            continue
        strips = (
            mask.crop((0, 0, width, ring)),
            mask.crop((0, height - ring, width, height)),
            mask.crop((0, ring, ring, height - ring)),
            mask.crop((width - ring, ring, width, height - ring)),
        )
        white = sum(strip.histogram()[255] for strip in strips)
        total = sum(strip.width * strip.height for strip in strips)
        if total and white / total >= ARTIFACT_BORDER_MIN_WHITE_RATIO:
            return f"near-white border/frame {ring}px wide around the outer edge"
    return None


def _edge_band_artifact(
    white: list[int], mean: list[int], length: int, edge: str
) -> str | None:
    """Reject a contiguous flat near-white band at one image edge."""
    minimum = max(6, int(length * ARTIFACT_EDGE_BAND_RATIO))
    indices = range(length) if edge in {"top", "left"} else range(length - 1, -1, -1)
    run = 0
    for index in indices:
        if (
            white[index] >= ARTIFACT_EDGE_BAND_MIN_WHITE
            and mean[index] >= ARTIFACT_EDGE_BAND_MIN_MEAN
        ):
            run += 1
            if run >= minimum:
                return f"near-white edge band at the {edge}"
        else:
            break
    return None


def _flat_area_artifact(mask: Image.Image, gray: Image.Image) -> str | None:
    """Reject a substantial area of flat near-white blocks."""
    width, height = mask.size
    block = ARTIFACT_BLOCK_SIZE
    grid_width = (width + block - 1) // block
    grid_height = (height + block - 1) // block
    sampled = mask.resize((grid_width, grid_height), Image.Resampling.BOX)
    flat_pixels = 0

    for grid_y in range(grid_height):
        y0 = grid_y * block
        y1 = min(height, y0 + block)
        for grid_x in range(grid_width):
            if sampled.getpixel((grid_x, grid_y)) < ARTIFACT_BLOCK_MIN_WHITE:
                continue
            x0 = grid_x * block
            x1 = min(width, x0 + block)
            low, high = gray.crop((x0, y0, x1, y1)).getextrema()
            if high - low <= ARTIFACT_FLAT_LUMINANCE_RANGE:
                flat_pixels += (x1 - x0) * (y1 - y0)

    ratio = flat_pixels / (width * height)
    if ratio >= ARTIFACT_MIN_FLAT_AREA_RATIO:
        return f"large flat near-white region ({ratio:.0%} of the image)"
    return None


def _context_mean(
    profile: list[int], start: int, step: int, length: int
) -> float | None:
    values = []
    index = start
    for _ in range(ARTIFACT_SEAM_CONTEXT):
        if 0 <= index < length:
            values.append(profile[index])
        index += step
    return sum(values) / len(values) if values else None


def _profile_seam(
    white: list[int], mean: list[int], length: int
) -> tuple[int, int] | None:
    """Find a narrow near-white seam over a low-contrast neighbourhood."""
    index = 0
    while index < length:
        if (
            white[index] < ARTIFACT_SEAM_MIN_WHITE
            or mean[index] < ARTIFACT_SEAM_MIN_MEAN
        ):
            index += 1
            continue

        start = index
        while index < length and (
            white[index] >= ARTIFACT_SEAM_MIN_WHITE
            and mean[index] >= ARTIFACT_SEAM_MIN_MEAN
        ):
            index += 1
        width = index - start

        if width > ARTIFACT_SEAM_MAX_WIDTH or start == 0 or index >= length:
            continue

        left = _context_mean(mean, start - 2, -1, length)
        right = _context_mean(mean, index + 1, 1, length)
        if left is None or right is None:
            continue
        seam_mean = min(mean[start:index])
        if (
            left <= ARTIFACT_SEAM_MAX_CONTEXT_MEAN
            and right <= ARTIFACT_SEAM_MAX_CONTEXT_MEAN
            and seam_mean - left >= ARTIFACT_SEAM_MIN_CONTRAST
            and seam_mean - right >= ARTIFACT_SEAM_MIN_CONTRAST
        ):
            return start, width
    return None


def detect_image_artifact(image: Image.Image) -> str | None:
    """Return a description of a near-white generation artifact, if any.

    The check runs on the exact final asset: the normalized Summary cover, the
    normalized topic cover, or the cropped pair/single strip. Only near-white,
    low-variance structures are rejected; ordinary flat-colour artwork passes.
    """
    rgb = image.convert("RGB")
    gray = rgb.convert("L")
    mask = _near_white_mask(gray)
    width, height = rgb.size

    border = _border_artifact(mask)
    if border is not None:
        return border

    column_white = list(
        mask.resize((width, 1), Image.Resampling.BOX).get_flattened_data()
    )
    column_mean = list(
        gray.resize((width, 1), Image.Resampling.BOX).get_flattened_data()
    )
    row_white = list(
        mask.resize((1, height), Image.Resampling.BOX).get_flattened_data()
    )
    row_mean = list(
        gray.resize((1, height), Image.Resampling.BOX).get_flattened_data()
    )

    for edge, white, mean, length in (
        ("top", row_white, row_mean, height),
        ("bottom", row_white, row_mean, height),
        ("left", column_white, column_mean, width),
        ("right", column_white, column_mean, width),
    ):
        band = _edge_band_artifact(white, mean, length, edge)
        if band is not None:
            return band

    flat = _flat_area_artifact(mask, gray)
    if flat is not None:
        return flat

    vertical = _profile_seam(column_white, column_mean, width)
    if vertical is not None:
        start, seam_width = vertical
        return f"near-white vertical seam at x={start} ({seam_width}px wide)"

    horizontal = _profile_seam(row_white, row_mean, height)
    if horizontal is not None:
        start, seam_width = horizontal
        return f"near-white horizontal seam at y={start} ({seam_width}px wide)"

    return None


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
) -> GeneratedImage:
    """Generate one final asset, retrying once when artifacts are detected."""
    style_prompt = with_image_style_suffix(prompt)
    artifact: str | None = None

    for attempt in range(1, MAX_IMAGE_ATTEMPTS + 1):
        attempt_prompt = (
            style_prompt
            if attempt == 1
            else with_artifact_retry_suffix(style_prompt)
        )
        try:
            payload = await llm.generate_image(
                role=role,
                prompt=attempt_prompt,
                aspect_ratio=aspect_ratio,
            )
            image = finalize(decode_image_bytes(payload))
        except LLMAuthenticationError:
            raise
        except Exception as exc:
            return _fallback_result(
                exc,
                factory=fallback,
                label=label,
                size=size,
            )

        artifact = detect_image_artifact(image)
        if artifact is None:
            return GeneratedImage(
                image=image, status=ASSET_STATUS_READY, error=None
            )
        logger.warning(
            "%s generation attempt %s/%s rejected: %s",
            label,
            attempt,
            MAX_IMAGE_ATTEMPTS,
            artifact,
        )

    return _fallback_result(
        ImageGenerationError(
            f"{label} artwork still contained a near-white artifact after "
            f"{MAX_IMAGE_ATTEMPTS} attempts: {artifact}"
        ),
        factory=fallback,
        label=label,
        size=size,
    )


async def generate_summary_cover(llm: LLMClient, prompt: str) -> GeneratedImage:
    """Generate and normalize the Summary cover art, or its brand fallback."""
    return await _generate_guarded_art(
        llm,
        prompt,
        role=SUMMARY_COVER_ROLE,
        aspect_ratio=SUMMARY_ASPECT_RATIO,
        label="Summary cover",
        size=SUMMARY_IMAGE_SIZE,
        finalize=lambda image: normalize_image(image, SUMMARY_IMAGE_SIZE),
        fallback=summary_fallback_art,
    )


def _normalized_topic_art(image: Image.Image) -> Image.Image:
    return normalize_image(image, TOPIC_IMAGE_SIZE)


async def generate_topic_cover(llm: LLMClient, prompt: str) -> GeneratedImage:
    """Generate and normalize the 1080x1350 topic cover art or its fallback."""
    return await _generate_guarded_art(
        llm,
        prompt,
        role=TOPIC_COVER_ROLE,
        aspect_ratio=TOPIC_ASPECT_RATIO,
        label="Topic cover",
        size=TOPIC_IMAGE_SIZE,
        finalize=_normalized_topic_art,
        fallback=topic_cover_fallback_art,
    )


async def generate_topic_pair_art(llm: LLMClient, prompt: str) -> GeneratedImage:
    """Generate one 4:5 artwork and center-crop it to a 720x1350 pair."""
    return await _generate_guarded_art(
        llm,
        prompt,
        role=TOPIC_PAIR_ROLE,
        aspect_ratio=TOPIC_ASPECT_RATIO,
        label="Topic pair artwork",
        size=TOPIC_PAIR_SIZE,
        finalize=lambda image: _normalized_topic_art(image).crop(
            TOPIC_PAIR_CROP
        ),
        fallback=topic_pair_fallback_art,
    )


async def generate_topic_single_art(llm: LLMClient, prompt: str) -> GeneratedImage:
    """Generate one 4:5 artwork and center-crop it to a 360x1350 strip."""
    return await _generate_guarded_art(
        llm,
        prompt,
        role=TOPIC_SINGLE_ROLE,
        aspect_ratio=TOPIC_ASPECT_RATIO,
        label="Topic single artwork",
        size=TOPIC_SINGLE_SIZE,
        finalize=lambda image: _normalized_topic_art(image).crop(
            TOPIC_SINGLE_CROP
        ),
        fallback=topic_single_fallback_art,
    )


__all__ = [
    "ARTIFACT_RETRY_SUFFIX",
    "ASSET_STATUS_FALLBACK",
    "ASSET_STATUS_READY",
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
    "detect_image_artifact",
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
    "with_image_style_suffix",
]
