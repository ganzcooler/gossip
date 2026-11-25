"""Behaviour tests for the decision-model artifact gate."""

import base64
import io

import pytest
from PIL import Image

from app.core import config
from app.services.decision_models import ImagePart
from app.services.image_artifact_check import (
    ARTIFACT_DEFECT_QUESTIONS,
    DECISION_MAX_IMAGE_SIDE,
    check_image_artifacts,
    verifier_image,
)
from app.services.llm_client import (
    LLMAuthenticationError,
    LLMTransportError,
)
from tests.support.fake_llm import FakeLLMClient


def _decision_image(call) -> Image.Image:
    assert isinstance(call.state, list)
    part = call.state[1]
    assert isinstance(part, ImagePart)
    prefix = "data:image/png;base64,"
    assert part.image_url.url.startswith(prefix)
    payload = base64.b64decode(part.image_url.url[len(prefix) :])
    with Image.open(io.BytesIO(payload)) as image:
        return image.convert("RGB")


def test_question_set_covers_every_planned_defect_class():
    assert list(ARTIFACT_DEFECT_QUESTIONS) == [
        "border_or_frame",
        "blank_band_or_strip",
        "flat_blank_block",
        "multi_panel_or_seam",
        "unintended_text_or_watermark",
        "generation_glitch",
    ]
    for question in ARTIFACT_DEFECT_QUESTIONS.values():
        assert question.type == "noul"
        assert question.criteria is not None
        assert question.criteria.true
        assert question.criteria.false


def test_verifier_image_downscales_only_oversized_assets():
    oversized = Image.new("RGB", (1080, 1920))
    fitting = Image.new("RGB", (1080, 1350))

    assert verifier_image(oversized).size == (882, DECISION_MAX_IMAGE_SIDE)
    assert verifier_image(fitting).size == (1080, 1350)


async def test_summary_cover_is_downscaled_before_the_decision_call():
    fake = FakeLLMClient(decision_responses={"image_artifact_check": [{}]})

    await check_image_artifacts(fake, Image.new("RGB", (1080, 1920)))

    assert _decision_image(fake.decision_calls[0]).size == (
        882,
        DECISION_MAX_IMAGE_SIDE,
    )


async def test_clean_verdict_requires_every_probability_below_the_threshold():
    fake = FakeLLMClient(
        decision_responses={
            "image_artifact_check": [{"border_or_frame": 0.1, "generation_glitch": 0.5}]
        }
    )

    verdict = await check_image_artifacts(fake, Image.new("RGB", (720, 1350)))

    assert verdict.clean is True
    assert verdict.findings == ()
    assert verdict.error is None
    assert verdict.model == config.OPENROUTER_DECISION_MODEL
    assert len(fake.decision_calls) == 1
    assert fake.decision_calls[0].questions == ARTIFACT_DEFECT_QUESTIONS
    assert _decision_image(fake.decision_calls[0]).size == (720, 1350)


async def test_any_probability_above_the_threshold_is_reported():
    fake = FakeLLMClient(
        decision_responses={
            "image_artifact_check": [{"border_or_frame": 0.9, "generation_glitch": 0.7}]
        }
    )

    verdict = await check_image_artifacts(fake, Image.new("RGB", (360, 1350)))

    assert verdict.clean is False
    assert verdict.error is None
    assert [(finding.question, finding.probability) for finding in verdict.findings] == [
        ("border_or_frame", 0.9),
        ("generation_glitch", 0.7),
    ]
    assert "border_or_frame=90%" in verdict.summary()
    assert "generation_glitch=70%" in verdict.summary()


async def test_thresholds_are_calibrated_per_question():
    fake = FakeLLMClient(
        decision_responses={
            "image_artifact_check": [
                {"border_or_frame": 0.4},
                {"border_or_frame": 0.6},
                {"generation_glitch": 0.5},
                {"generation_glitch": 0.7},
                {"unintended_text_or_watermark": 0.3},
                {"unintended_text_or_watermark": 0.5},
            ]
        }
    )
    image = Image.new("RGB", (540, 960))

    border_clean = await check_image_artifacts(fake, image)
    border_defect = await check_image_artifacts(fake, image)
    glitch_clean = await check_image_artifacts(fake, image)
    glitch_defect = await check_image_artifacts(fake, image)
    text_clean = await check_image_artifacts(fake, image)
    text_defect = await check_image_artifacts(fake, image)

    assert border_clean.clean is True
    assert border_defect.findings[0].question == "border_or_frame"
    assert glitch_clean.clean is True
    assert glitch_defect.findings[0].question == "generation_glitch"
    assert text_clean.clean is True
    assert text_defect.findings[0].question == "unintended_text_or_watermark"


async def test_thresholds_are_read_from_config_per_call(monkeypatch):
    monkeypatch.setitem(
        config.IMAGE_ARTIFACT_THRESHOLDS, "border_or_frame", 0.8
    )
    fake = FakeLLMClient(
        decision_responses={
            "image_artifact_check": [
                {"border_or_frame": 0.7},
                {"border_or_frame": 0.9},
            ]
        }
    )

    first = await check_image_artifacts(fake, Image.new("RGB", (540, 960)))
    second = await check_image_artifacts(fake, Image.new("RGB", (540, 960)))

    assert first.clean is True
    assert second.clean is False
    assert second.findings[0].question == "border_or_frame"


async def test_refusal_is_not_treated_as_clean():
    fake = FakeLLMClient(
        decision_responses={
            "image_artifact_check": [{"answers": {"border_or_frame": {"type": "refusal"}}}]
        }
    )

    verdict = await check_image_artifacts(fake, Image.new("RGB", (540, 960)))

    assert verdict.clean is False
    assert verdict.error is not None
    assert "border_or_frame: refusal" in verdict.error


async def test_missing_answer_is_not_treated_as_clean():
    fake = FakeLLMClient(
        decision_responses={
            "image_artifact_check": [
                {"answers": {"border_or_frame": {"type": "noul", "noul": 0.0}}}
            ]
        }
    )

    verdict = await check_image_artifacts(fake, Image.new("RGB", (540, 960)))

    assert verdict.clean is False
    assert verdict.error is not None
    assert "blank_band_or_strip: no answer" in verdict.error


async def test_transport_failure_becomes_a_fail_closed_verdict():
    fake = FakeLLMClient(
        decision_responses={"image_artifact_check": [LLMTransportError("decisions down")]}
    )

    verdict = await check_image_artifacts(fake, Image.new("RGB", (540, 960)))

    assert verdict.clean is False
    assert verdict.error == "decisions down"


async def test_authentication_failure_propagates_to_the_pipeline():
    fake = FakeLLMClient(
        decision_responses={
            "image_artifact_check": [LLMAuthenticationError("Insufficient credits")]
        }
    )

    with pytest.raises(LLMAuthenticationError, match="Insufficient credits"):
        await check_image_artifacts(fake, Image.new("RGB", (540, 960)))
