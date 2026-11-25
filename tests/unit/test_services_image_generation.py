"""Behaviour tests for deterministic Summary cover image generation."""

import io

import pytest
from PIL import Image, ImageDraw

from app.services.image_generation import (
    ARTIFACT_RETRY_SUFFIX,
    IMAGE_STYLE_SUFFIX,
    MAX_IMAGE_ATTEMPTS,
    SUMMARY_ASPECT_RATIO,
    SUMMARY_IMAGE_SIZE,
    TOPIC_ASPECT_RATIO,
    TOPIC_IMAGE_SIZE,
    TOPIC_PAIR_SIZE,
    TOPIC_SINGLE_SIZE,
    ImageGenerationError,
    decode_image_bytes,
    detect_image_artifact,
    generate_summary_cover,
    generate_topic_cover,
    generate_topic_pair_art,
    generate_topic_single_art,
    normalize_image,
    summary_fallback_art,
    topic_cover_fallback_art,
    topic_pair_fallback_art,
    topic_single_fallback_art,
    with_artifact_retry_suffix,
    with_image_style_suffix,
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
    assert fake.image_calls[0].prompt == (
        f"A wide calm civic scene\n\n{IMAGE_STYLE_SUFFIX}"
    )


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


def test_image_style_suffix_forbids_illustration_and_frames():
    assert IMAGE_STYLE_SUFFIX.startswith("Photorealistic editorial")
    for required in (
        "natural light",
        "real materials",
        "illustration",
        "cartoon",
        "drawing",
        "watercolour",
        "3D render",
        "frame",
        "border",
        "passepartout",
        "polaroid",
        "picture-in-picture",
        "collage",
        "split screen",
        "vignette",
    ):
        assert required in IMAGE_STYLE_SUFFIX


def test_image_style_suffix_is_deterministic_and_idempotent():
    base = "A wide calm civic scene"

    once = with_image_style_suffix(base)
    twice = with_image_style_suffix(once)

    assert once == f"{base}\n\n{IMAGE_STYLE_SUFFIX}"
    assert twice == once


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


def test_fallbacks_use_the_shared_render_common_palette():
    from app.services.render_common import (
        BRAND_ORANGE,
        BRAND_ORANGE_DEEP,
        SURFACE_BASE,
        SURFACE_SUNKEN,
    )

    summary = summary_fallback_art()
    topic = topic_cover_fallback_art()

    assert summary.getpixel((0, 0)) == SURFACE_SUNKEN
    assert summary.getpixel((900, 100)) == (21, 90, 133)
    assert topic.getpixel((0, 0)) == SURFACE_BASE
    assert topic.getpixel((900, 100)) == BRAND_ORANGE_DEEP
    assert topic.getpixel((715, 500)) == BRAND_ORANGE


def _striped_png_bytes(size=(1080, 1350)) -> bytes:
    image = Image.new("RGB", size, (40, 60, 80))
    image.paste((200, 100, 50), (180, 0, 900, 1350))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _topic_png_bytes(size=(720, 900), color=(90, 140, 170)) -> bytes:
    image = Image.new("RGB", size, color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


async def test_topic_cover_requests_4_5_and_normalizes_to_1080x1350():
    fake = FakeLLMClient(
        image_responses={"topic_cover": [_topic_png_bytes()]}
    )

    result = await generate_topic_cover(fake, "A wide calm civic scene")

    assert result.status == "ready"
    assert result.error is None
    assert result.image.size == TOPIC_IMAGE_SIZE == (1080, 1350)
    assert result.image.mode == "RGB"
    assert result.image.getpixel((540, 675)) == (90, 140, 170)
    assert len(fake.image_calls) == 1
    assert fake.image_calls[0].role == "topic_cover"
    assert fake.image_calls[0].aspect_ratio == TOPIC_ASPECT_RATIO == "4:5"
    assert fake.image_calls[0].prompt == (
        f"A wide calm civic scene\n\n{IMAGE_STYLE_SUFFIX}"
    )


async def test_topic_pair_art_center_crops_the_normalized_image_to_720x1350():
    fake = FakeLLMClient(
        image_responses={"topic_pair_art": [_striped_png_bytes()]}
    )

    result = await generate_topic_pair_art(fake, "Pair prompt")

    assert result.status == "ready"
    assert result.image.size == TOPIC_PAIR_SIZE == (720, 1350)
    assert result.image.getpixel((0, 675)) == (200, 100, 50)
    assert result.image.getpixel((719, 675)) == (200, 100, 50)
    assert fake.image_calls[0].role == "topic_pair_art"
    assert fake.image_calls[0].aspect_ratio == "4:5"
    assert fake.image_calls[0].prompt == f"Pair prompt\n\n{IMAGE_STYLE_SUFFIX}"


async def test_topic_single_art_center_crops_to_a_standalone_360x1350_strip():
    fake = FakeLLMClient(
        image_responses={"topic_single_art": [_striped_png_bytes()]}
    )

    result = await generate_topic_single_art(fake, "Single prompt")

    assert result.status == "ready"
    assert result.image.size == TOPIC_SINGLE_SIZE == (360, 1350)
    assert result.image.getpixel((0, 675)) == (200, 100, 50)
    assert fake.image_calls[0].role == "topic_single_art"
    assert fake.image_calls[0].aspect_ratio == "4:5"
    assert fake.image_calls[0].prompt == f"Single prompt\n\n{IMAGE_STYLE_SUFFIX}"


async def test_topic_image_failures_produce_orange_family_fallbacks():
    fake = FakeLLMClient(
        image_responses={
            "topic_cover": [LLMTransportError("cover unavailable")],
            "topic_pair_art": [LLMTransportError("pair unavailable")],
            "topic_single_art": [b"not an image"],
        }
    )

    cover = await generate_topic_cover(fake, "Cover")
    pair = await generate_topic_pair_art(fake, "Pair")
    single = await generate_topic_single_art(fake, "Single")

    assert cover.status == pair.status == single.status == "fallback"
    assert "cover unavailable" in cover.error
    assert "pair unavailable" in pair.error
    assert single.error
    assert cover.image.size == TOPIC_IMAGE_SIZE
    assert pair.image.size == TOPIC_PAIR_SIZE
    assert single.image.size == TOPIC_SINGLE_SIZE
    assert cover.image.getpixel((100, 100)) == (30, 30, 33)
    assert cover.image.getpixel((900, 100)) == (201, 62, 24)
    assert cover.image.getpixel((715, 500)) == (233, 79, 35)
    assert pair.image.getpixel((300, 600)) == (201, 62, 24)
    assert pair.image.getpixel((359, 100)) == (233, 79, 35)
    assert single.image.getpixel((100, 600)) == (201, 62, 24)
    assert single.image.tobytes() == topic_single_fallback_art().tobytes()


async def test_topic_authentication_errors_propagate_without_fallback():
    fake = FakeLLMClient(
        image_responses={
            "topic_cover": [LLMAuthenticationError("Insufficient credits")]
        }
    )

    with pytest.raises(LLMAuthenticationError, match="Insufficient credits"):
        await generate_topic_cover(fake, "Prompt")


def test_topic_fallbacks_are_deterministic_and_match_the_design():
    assert topic_cover_fallback_art().tobytes() == topic_cover_fallback_art().tobytes()
    assert topic_pair_fallback_art().tobytes() == topic_pair_fallback_art().tobytes()
    assert topic_single_fallback_art().size == TOPIC_SINGLE_SIZE
    assert topic_pair_fallback_art().crop((180, 0, 540, 1350)).tobytes() == (
        topic_single_fallback_art().tobytes()
    )


def _clean_scene(size=(720, 1350)) -> Image.Image:
    width, height = size
    image = Image.new("RGB", size, (82, 111, 132))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, height // 4), fill=(105, 136, 158))
    draw.rectangle((0, height // 4, width, height // 2), fill=(67, 94, 74))
    draw.rectangle((0, height // 2, width, 3 * height // 4), fill=(52, 71, 86))
    draw.rectangle((0, 3 * height // 4, width, height), fill=(38, 50, 60))
    draw.ellipse(
        (width // 5, height // 3, width // 2, height * 2 // 3),
        fill=(178, 132, 83),
    )
    return image


def _artifact_art(
    kind: str, *, size=(540, 960), color=(90, 140, 170)
) -> Image.Image:
    width, height = size
    image = Image.new("RGB", size, color)
    draw = ImageDraw.Draw(image)
    white = (255, 255, 255)
    if kind == "border":
        draw.rectangle((0, 0, width - 1, height - 1), outline=white, width=3)
    elif kind == "top_band":
        draw.rectangle((0, 0, width, 50), fill=white)
    elif kind == "bottom_band":
        draw.rectangle((0, height - 50, width, height), fill=white)
    elif kind == "block":
        draw.rectangle(
            (width // 5, height // 3, width * 4 // 5, height // 3 + 260),
            fill=white,
        )
    elif kind == "vertical_seam":
        draw.rectangle((width // 2 - 2, 0, width // 2 + 2, height), fill=white)
    elif kind == "horizontal_seam":
        draw.rectangle((0, height // 2 - 2, width, height // 2 + 2), fill=white)
    else:  # pragma: no cover - test helper guard
        raise AssertionError(f"unknown artifact kind: {kind}")
    return image


def _artifact_png_bytes(kind: str, **kwargs) -> bytes:
    buffer = io.BytesIO()
    _artifact_art(kind, **kwargs).save(buffer, format="PNG")
    return buffer.getvalue()


def _seam_png_bytes(size=(1080, 1350), x=540) -> bytes:
    image = Image.new("RGB", size, (60, 100, 140))
    ImageDraw.Draw(image).rectangle(
        (x - 2, 0, x + 2, size[1]), fill=(255, 255, 255)
    )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_artifact_detector_accepts_clean_photo_like_artwork():
    assert detect_image_artifact(_clean_scene()) is None


def test_artifact_detector_accepts_the_brand_fallbacks():
    for image in (
        summary_fallback_art(),
        topic_cover_fallback_art(),
        topic_pair_fallback_art(),
        topic_single_fallback_art(),
    ):
        assert detect_image_artifact(image) is None


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("border", "border/frame"),
        ("top_band", "edge band at the top"),
        ("bottom_band", "edge band at the bottom"),
        ("block", "large flat near-white region"),
        ("vertical_seam", "vertical seam"),
        ("horizontal_seam", "horizontal seam"),
    ],
)
def test_artifact_detector_rejects_near_white_artifacts(kind, expected):
    artifact = detect_image_artifact(_artifact_art(kind))

    assert artifact is not None
    assert expected in artifact


def test_artifact_retry_suffix_is_deterministic_and_idempotent():
    once = with_artifact_retry_suffix("Prompt")
    twice = with_artifact_retry_suffix(once)

    assert once == f"Prompt\n\n{ARTIFACT_RETRY_SUFFIX}"
    assert twice == once
    for required in ("Full-bleed", "edge to edge", "no white border", "split-screen"):
        assert required in ARTIFACT_RETRY_SUFFIX


async def test_first_artifact_retries_once_with_the_full_bleed_suffix():
    fake = FakeLLMClient(
        image_responses={
            "summary_cover": [_artifact_png_bytes("border"), _png_bytes()]
        }
    )

    result = await generate_summary_cover(fake, "A wide calm civic scene")

    assert result.status == "ready"
    assert result.error is None
    assert result.image.getpixel((540, 960)) == (90, 140, 170)
    assert len(fake.image_calls) == MAX_IMAGE_ATTEMPTS == 2
    assert fake.image_calls[0].prompt == (
        f"A wide calm civic scene\n\n{IMAGE_STYLE_SUFFIX}"
    )
    assert fake.image_calls[1].prompt == (
        f"A wide calm civic scene\n\n{IMAGE_STYLE_SUFFIX}"
        f"\n\n{ARTIFACT_RETRY_SUFFIX}"
    )
    assert fake.image_calls[0].role == fake.image_calls[1].role == "summary_cover"
    assert (
        fake.image_calls[0].aspect_ratio
        == fake.image_calls[1].aspect_ratio
        == "9:16"
    )


async def test_persistent_artifact_falls_back_with_an_explanatory_error():
    fake = FakeLLMClient(
        image_responses={
            "topic_cover": [
                _artifact_png_bytes("block"),
                _artifact_png_bytes("vertical_seam"),
            ]
        }
    )

    result = await generate_topic_cover(fake, "Prompt")

    assert result.status == "fallback"
    assert "near-white" in result.error
    assert "artifact" in result.error.lower()
    assert len(fake.image_calls) == MAX_IMAGE_ATTEMPTS
    assert result.image.tobytes() == topic_cover_fallback_art().tobytes()


async def test_authentication_error_on_the_artifact_retry_propagates():
    fake = FakeLLMClient(
        image_responses={
            "summary_cover": [
                _artifact_png_bytes("border"),
                LLMAuthenticationError("Insufficient credits"),
            ]
        }
    )

    with pytest.raises(LLMAuthenticationError, match="Insufficient credits"):
        await generate_summary_cover(fake, "Prompt")

    assert len(fake.image_calls) == MAX_IMAGE_ATTEMPTS


async def test_topic_pair_detects_an_artifact_inside_the_cropped_pair():
    fake = FakeLLMClient(
        image_responses={
            "topic_pair_art": [
                _seam_png_bytes(),
                _topic_png_bytes(size=(720, 900)),
            ]
        }
    )

    result = await generate_topic_pair_art(fake, "Pair prompt")

    assert result.status == "ready"
    assert result.image.size == TOPIC_PAIR_SIZE
    assert result.image.getpixel((360, 675)) == (90, 140, 170)
    assert len(fake.image_calls) == MAX_IMAGE_ATTEMPTS
    assert fake.image_calls[1].prompt == (
        f"Pair prompt\n\n{IMAGE_STYLE_SUFFIX}\n\n{ARTIFACT_RETRY_SUFFIX}"
    )


async def test_topic_single_detects_an_artifact_inside_its_crop():
    fake = FakeLLMClient(
        image_responses={
            "topic_single_art": [
                _seam_png_bytes(),
                _topic_png_bytes(size=(720, 900)),
            ]
        }
    )

    result = await generate_topic_single_art(fake, "Single prompt")

    assert result.status == "ready"
    assert result.image.size == TOPIC_SINGLE_SIZE
    assert result.image.getpixel((180, 675)) == (90, 140, 170)
    assert len(fake.image_calls) == MAX_IMAGE_ATTEMPTS
    assert fake.image_calls[1].prompt == (
        f"Single prompt\n\n{IMAGE_STYLE_SUFFIX}\n\n{ARTIFACT_RETRY_SUFFIX}"
    )


async def test_topic_single_ignores_an_artifact_outside_its_crop():
    fake = FakeLLMClient(
        image_responses={"topic_single_art": [_seam_png_bytes(x=100)]}
    )

    result = await generate_topic_single_art(fake, "Single prompt")

    assert result.status == "ready"
    assert result.image.size == TOPIC_SINGLE_SIZE
    assert len(fake.image_calls) == 1
    assert fake.image_calls[0].prompt == f"Single prompt\n\n{IMAGE_STYLE_SUFFIX}"
