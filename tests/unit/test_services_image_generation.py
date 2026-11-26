"""Behaviour tests for decision-checked Summary and topic image generation."""

import base64
import io
import json

import pytest
from PIL import Image, ImageDraw

from app.services.decision_models import ImagePart
from app.services.image_generation import (
    ARTIFACT_RETRY_SUFFIX,
    COVER_SATIRE_SUFFIX,
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
    LLMSchemaError,
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


def _decision_image(call) -> Image.Image:
    assert isinstance(call.state, list)
    part = call.state[1]
    assert isinstance(part, ImagePart)
    prefix = "data:image/png;base64,"
    assert part.image_url.url.startswith(prefix)
    payload = base64.b64decode(part.image_url.url[len(prefix) :])
    with Image.open(io.BytesIO(payload)) as image:
        return image.convert("RGB")


async def test_summary_cover_requests_9_16_and_normalizes_to_1080x1920():
    fake = FakeLLMClient(image_responses={"summary_cover": [_png_bytes(size=(400, 800))]})

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
        f"A wide calm civic scene\n\n{COVER_SATIRE_SUFFIX}\n\n{IMAGE_STYLE_SUFFIX}"
    )
    assert len(fake.decision_calls) == 1
    assert fake.decision_calls[0].role == "summary_cover_artifact_check"
    assert _decision_image(fake.decision_calls[0]).size == (882, 1568)


async def test_token_transport_failure_produces_the_blue_brand_fallback():
    fake = FakeLLMClient(
        image_responses={"summary_cover": [LLMTransportError("image endpoint unavailable")]}
    )

    result = await generate_summary_cover(fake, "Prompt")

    assert result.status == "fallback"
    assert "image endpoint unavailable" in result.error
    assert result.image.size == SUMMARY_IMAGE_SIZE
    assert result.image.mode == "RGB"
    for position, expected in _fallback_colors().items():
        assert result.image.getpixel(position) == expected
    assert fake.decision_calls == []


async def test_undecodable_image_bytes_produce_the_fallback_instead_of_an_empty_cover():
    fake = FakeLLMClient(image_responses={"summary_cover": [b"not an image"]})

    result = await generate_summary_cover(fake, "Prompt")

    assert result.status == "fallback"
    assert result.error
    assert result.image.getpixel((900, 100)) == (21, 90, 133)
    assert fake.decision_calls == []


async def test_authentication_errors_propagate_immediately_without_fallback():
    fake = FakeLLMClient(
        image_responses={"summary_cover": [LLMAuthenticationError("Insufficient credits")]}
    )

    with pytest.raises(LLMAuthenticationError, match="Insufficient credits"):
        await generate_summary_cover(fake, "Prompt")


def test_image_style_suffix_forbids_illustration_and_frames():
    assert IMAGE_STYLE_SUFFIX.startswith("Photorealistic editorial")
    for required in (
        "natural light",
        "real materials",
        "Continuous scene detail",
        "empty margins",
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
        "diptych",
        "triptych",
        "multi-panel",
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


def test_cover_satire_suffix_is_idempotent_and_stays_before_the_style_suffix():
    from app.services.image_generation import with_cover_satire_suffix

    once = with_cover_satire_suffix("A wide calm civic scene")
    twice = with_cover_satire_suffix(once)
    styled = with_image_style_suffix(once)
    styled_twice = with_cover_satire_suffix(styled)

    assert once == f"A wide calm civic scene\n\n{COVER_SATIRE_SUFFIX}"
    assert twice == once
    assert styled == (
        f"A wide calm civic scene\n\n{COVER_SATIRE_SUFFIX}\n\n{IMAGE_STYLE_SUFFIX}"
    )
    assert styled_twice == styled


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


def _seam_png_bytes(size=(1080, 1350), x=540) -> bytes:
    image = Image.new("RGB", size, (60, 100, 140))
    ImageDraw.Draw(image).rectangle((x - 2, 0, x + 2, size[1]), fill=(255, 255, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


async def test_topic_cover_requests_4_5_and_normalizes_to_1080x1350():
    fake = FakeLLMClient(image_responses={"topic_cover": [_topic_png_bytes()]})

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
        f"A wide calm civic scene\n\n{COVER_SATIRE_SUFFIX}\n\n{IMAGE_STYLE_SUFFIX}"
    )


async def test_topic_pair_art_center_crops_the_normalized_image_to_720x1350():
    fake = FakeLLMClient(image_responses={"topic_pair_art": [_striped_png_bytes()]})

    result = await generate_topic_pair_art(fake, "Pair prompt")

    assert result.status == "ready"
    assert result.image.size == TOPIC_PAIR_SIZE == (720, 1350)
    assert result.image.getpixel((0, 675)) == (200, 100, 50)
    assert result.image.getpixel((719, 675)) == (200, 100, 50)
    assert fake.image_calls[0].role == "topic_pair_art"
    assert fake.image_calls[0].aspect_ratio == "4:5"
    assert fake.image_calls[0].prompt == f"Pair prompt\n\n{IMAGE_STYLE_SUFFIX}"
    assert _decision_image(fake.decision_calls[0]).size == TOPIC_PAIR_SIZE


async def test_topic_single_art_center_crops_to_a_standalone_360x1350_strip():
    fake = FakeLLMClient(image_responses={"topic_single_art": [_striped_png_bytes()]})

    result = await generate_topic_single_art(fake, "Single prompt")

    assert result.status == "ready"
    assert result.image.size == TOPIC_SINGLE_SIZE
    assert result.image.getpixel((0, 675)) == (200, 100, 50)
    assert fake.image_calls[0].role == "topic_single_art"
    assert fake.image_calls[0].aspect_ratio == "4:5"
    assert fake.image_calls[0].prompt == f"Single prompt\n\n{IMAGE_STYLE_SUFFIX}"
    assert _decision_image(fake.decision_calls[0]).size == TOPIC_SINGLE_SIZE


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
        image_responses={"topic_cover": [LLMAuthenticationError("Insufficient credits")]}
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


def test_artifact_retry_suffix_is_deterministic_and_idempotent():
    once = with_artifact_retry_suffix("Prompt")
    twice = with_artifact_retry_suffix(once)

    assert once == f"Prompt\n\n{ARTIFACT_RETRY_SUFFIX}"
    assert twice == once
    for required in (
        "full-bleed",
        "edge to edge",
        "no white border",
        "diptych",
        "triptych",
        "multi-panel",
        "split-screen",
    ):
        assert required in ARTIFACT_RETRY_SUFFIX


async def test_first_artifact_retries_once_with_the_full_bleed_suffix():
    fake = FakeLLMClient(
        image_responses={"summary_cover": [_png_bytes(), _png_bytes()]},
        decision_responses={
            "summary_cover_artifact_check": [
                {"border_or_blank_area": 0.9},
                {},
            ]
        },
    )

    result = await generate_summary_cover(fake, "A wide calm civic scene")

    assert result.status == "ready"
    assert result.error is None
    assert result.image.getpixel((540, 960)) == (90, 140, 170)
    assert len(fake.image_calls) == MAX_IMAGE_ATTEMPTS == 2
    assert fake.image_calls[0].prompt == (
        f"A wide calm civic scene\n\n{COVER_SATIRE_SUFFIX}\n\n{IMAGE_STYLE_SUFFIX}"
    )
    assert fake.image_calls[1].prompt.startswith(
        f"A wide calm civic scene\n\n{COVER_SATIRE_SUFFIX}\n\n"
        f"{IMAGE_STYLE_SUFFIX}\n\n{ARTIFACT_RETRY_SUFFIX}"
    )
    assert "border_or_blank_area" in fake.image_calls[1].prompt
    assert fake.image_calls[0].role == fake.image_calls[1].role == "summary_cover"
    assert fake.image_calls[0].aspect_ratio == fake.image_calls[1].aspect_ratio == "9:16"
    assert len(fake.decision_calls) == 2


async def test_persistent_artifact_falls_back_with_an_explanatory_error():
    fake = FakeLLMClient(
        image_responses={"topic_cover": [_topic_png_bytes(), _topic_png_bytes()]},
        decision_responses={
            "topic_cover_artifact_check": [
                {"border_or_blank_area": 0.9},
                {"panel_or_seam": 0.8},
            ]
        },
    )

    result = await generate_topic_cover(fake, "Prompt")

    assert result.status == "fallback"
    assert "artifact check" in result.error
    assert "border_or_blank_area" in result.error
    assert "panel_or_seam" in result.error
    assert "typesafe/jev-1.14" in result.error
    assert len(fake.image_calls) == MAX_IMAGE_ATTEMPTS
    assert len(fake.decision_calls) == MAX_IMAGE_ATTEMPTS
    assert result.image.tobytes() == topic_cover_fallback_art().tobytes()


async def test_rejected_attempts_are_persisted_with_prompt_and_verdict(tmp_path):
    fake = FakeLLMClient(
        image_responses={"topic_cover": [_topic_png_bytes(), _topic_png_bytes()]},
        decision_responses={
            "topic_cover_artifact_check": [
                {"border_or_blank_area": 0.9},
                {"minor": 0.9},
            ]
        },
    )

    result = await generate_topic_cover(
        fake,
        "Prompt",
        rejected_dir=tmp_path,
        rejected_name="cover",
    )

    assert result.status == "fallback"
    first = tmp_path / "cover-attempt-1-rejected.png"
    second = tmp_path / "cover-attempt-2-rejected.png"
    assert first.is_file()
    assert second.is_file()
    with Image.open(first) as image:
        assert image.size == TOPIC_IMAGE_SIZE
    first_meta = json.loads(
        (tmp_path / "cover-attempt-1-rejected.json").read_text(encoding="utf-8")
    )
    assert first_meta["role"] == "topic_cover"
    assert first_meta["attempt"] == 1
    assert first_meta["prompt"].startswith("Prompt\n\n")
    assert first_meta["findings"][0]["question"] == "border_or_blank_area"
    assert first_meta["findings"][0]["probability"] == 0.9
    assert first_meta["thresholds"]["minor"] == 0.5
    second_meta = json.loads(
        (tmp_path / "cover-attempt-2-rejected.json").read_text(encoding="utf-8")
    )
    assert second_meta["findings"][0]["question"] == "minor"


async def test_accepted_attempt_writes_no_rejected_files(tmp_path):
    fake = FakeLLMClient(
        image_responses={"summary_cover": [_png_bytes()]},
    )

    result = await generate_summary_cover(
        fake,
        "Prompt",
        rejected_dir=tmp_path,
        rejected_name="cover",
    )

    assert result.status == "ready"
    assert list(tmp_path.iterdir()) == []


async def test_verifier_failure_is_persisted_as_a_diagnostic(tmp_path):
    fake = FakeLLMClient(
        image_responses={"summary_cover": [_png_bytes()]},
        decision_responses={
            "summary_cover_artifact_check": [
                LLMSchemaError("artifact verdict was not JSON")
            ]
        },
    )

    result = await generate_summary_cover(
        fake,
        "Prompt",
        rejected_dir=tmp_path,
        rejected_name="cover",
    )

    assert result.status == "fallback"
    assert (tmp_path / "cover-attempt-1-verifier-error.png").is_file()
    metadata = json.loads(
        (tmp_path / "cover-attempt-1-verifier-error.json").read_text(
            encoding="utf-8"
        )
    )
    assert "artifact verdict was not JSON" in metadata["error"]


async def test_verifier_failure_falls_back_without_a_second_image_call():
    fake = FakeLLMClient(
        image_responses={"summary_cover": [_png_bytes()]},
        decision_responses={
            "summary_cover_artifact_check": [
                LLMSchemaError("artifact verdict was not JSON"),
            ]
        },
    )

    result = await generate_summary_cover(fake, "Prompt")

    assert result.status == "fallback"
    assert "artifact check failed" in result.error
    assert "artifact verdict was not JSON" in result.error
    assert len(fake.image_calls) == 1
    assert len(fake.decision_calls) == 1
    assert result.image.tobytes() == summary_fallback_art().tobytes()


async def test_authentication_error_on_the_artifact_check_propagates():
    fake = FakeLLMClient(
        image_responses={"summary_cover": [_png_bytes(), _png_bytes()]},
        decision_responses={
            "summary_cover_artifact_check": [
                {"border_or_blank_area": 0.9},
                LLMAuthenticationError("Insufficient credits"),
            ]
        },
    )

    with pytest.raises(LLMAuthenticationError, match="Insufficient credits"):
        await generate_summary_cover(fake, "Prompt")

    assert len(fake.image_calls) == MAX_IMAGE_ATTEMPTS
    assert len(fake.decision_calls) == MAX_IMAGE_ATTEMPTS


async def test_topic_pair_check_uses_the_cropped_pair_asset():
    fake = FakeLLMClient(image_responses={"topic_pair_art": [_seam_png_bytes()]})

    result = await generate_topic_pair_art(fake, "Pair prompt")

    assert result.status == "ready"
    decision_image = _decision_image(fake.decision_calls[0])
    assert decision_image.size == TOPIC_PAIR_SIZE
    assert decision_image.getpixel((0, 675)) == (60, 100, 140)
    assert decision_image.getpixel((360, 675)) == (255, 255, 255)
    assert len(fake.image_calls) == 1


async def test_topic_single_check_uses_the_cropped_strip_asset():
    fake = FakeLLMClient(image_responses={"topic_single_art": [_seam_png_bytes(x=100)]})

    result = await generate_topic_single_art(fake, "Single prompt")

    assert result.status == "ready"
    decision_image = _decision_image(fake.decision_calls[0])
    assert decision_image.size == TOPIC_SINGLE_SIZE
    assert decision_image.getpixel((0, 675)) == (60, 100, 140)
    assert decision_image.getpixel((359, 675)) == (60, 100, 140)
    assert len(fake.image_calls) == 1
    assert fake.image_calls[0].prompt == f"Single prompt\n\n{IMAGE_STYLE_SUFFIX}"
