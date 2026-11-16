"""Behaviour tests for deterministic Summary cover image generation."""

import io

import pytest
from PIL import Image

from app.services.image_generation import (
    SUMMARY_ASPECT_RATIO,
    SUMMARY_IMAGE_SIZE,
    ImageGenerationError,
    decode_image_bytes,
    generate_summary_cover,
    normalize_image,
    summary_fallback_art,
)
from app.services.llm_client import (
    LLMAuthenticationError,
    LLMTransportError,
)
from tests.support.fake_llm import FakeLLMClient


def _png_bytes(size=(540, 960), color=(90, 140, 170)) -> bytes:
    image = Image.new("RGB", size, color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _fallback_colors() -> dict[tuple[int, int], tuple[int, int, int]]:
    return {
        (100, 100): (23, 23, 26),
        (900, 100): (21, 90, 133),
        (715, 500): (30, 123, 181),
        (100, 1455): (30, 123, 181),
        (100, 1800): (21, 90, 133),
    }


async def test_summary_cover_requests_9_16_and_normalizes_to_1080x1920():
    fake = FakeLLMClient(
        image_responses={"summary_cover": [_png_bytes(size=(400, 800))]}
    )

    result = await generate_summary_cover(fake, "A wide calm civic scene")

    assert result.status == "ready"
    assert result.error is None
    assert result.image.size == SUMMARY_IMAGE_SIZE
    assert result.image.mode == "RGB"
    assert result.image.getpixel((540, 960)) == (90, 140, 170)
    assert len(fake.image_calls) == 1
    assert fake.image_calls[0].role == "summary_cover"
    assert fake.image_calls[0].aspect_ratio == SUMMARY_ASPECT_RATIO == "9:16"
    assert fake.image_calls[0].prompt == "A wide calm civic scene"


async def test_token_transport_failure_produces_the_blue_brand_fallback():
    fake = FakeLLMClient(
        image_responses={
            "summary_cover": [LLMTransportError("image endpoint unavailable")]
        }
    )

    result = await generate_summary_cover(fake, "Prompt")

    assert result.status == "fallback"
    assert "image endpoint unavailable" in result.error
    assert result.image.size == SUMMARY_IMAGE_SIZE
    assert result.image.mode == "RGB"
    for position, expected in _fallback_colors().items():
        assert result.image.getpixel(position) == expected


async def test_undecodable_image_bytes_produce_the_fallback_instead_of_an_empty_cover():
    fake = FakeLLMClient(image_responses={"summary_cover": [b"not an image"]})

    result = await generate_summary_cover(fake, "Prompt")

    assert result.status == "fallback"
    assert result.error
    assert result.image.getpixel((900, 100)) == (21, 90, 133)


async def test_authentication_errors_propagate_immediately_without_fallback():
    fake = FakeLLMClient(
        image_responses={
            "summary_cover": [LLMAuthenticationError("Insufficient credits")]
        }
    )

    with pytest.raises(LLMAuthenticationError, match="Insufficient credits"):
        await generate_summary_cover(fake, "Prompt")


def test_normalize_image_uses_a_deterministic_center_fit():
    source = Image.new("RGB", (100, 400), (10, 20, 30))
    source.paste((200, 100, 50), (0, 100, 100, 300))

    normalized = normalize_image(source, SUMMARY_IMAGE_SIZE)

    assert normalized.size == SUMMARY_IMAGE_SIZE
    assert normalized.getpixel((540, 960)) == (200, 100, 50)


def test_decode_image_bytes_rejects_invalid_payloads():
    with pytest.raises(ImageGenerationError):
        decode_image_bytes(b"not an image")


def test_summary_fallback_can_be_built_twice_without_side_effects():
    first = summary_fallback_art()
    second = summary_fallback_art()

    assert first.size == second.size == SUMMARY_IMAGE_SIZE
    assert first.tobytes() == second.tobytes()
