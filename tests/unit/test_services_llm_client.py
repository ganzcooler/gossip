"""Tests for the injectable OpenRouter LLM port."""

import inspect
import logging
from unittest.mock import patch

import pytest
from pydantic import BaseModel, ConfigDict

from app.core import config
from app.services import llm_client as llm_client_module
from app.services.decision_models import ImagePart, ImageURL, NoulQuestion
from app.services.llm_client import (
    LLMAuthenticationError,
    LLMClient,
    LLMSchemaError,
    LLMTransportError,
    OpenRouterLLMClient,
)
from app.services.openrouter_client import OpenRouterError


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str


@pytest.fixture
def transport():
    with patch.object(llm_client_module, "openrouter_client") as client:
        yield client


def _client(**kwargs):
    return OpenRouterLLMClient(retry_delay=0, **kwargs)


async def test_generate_json_requests_strict_schema_and_sends_only_the_prompt(transport):
    transport.chat_completion.return_value = '{"message": "ok"}'

    result = await _client().generate_json(
        role="planner", prompt="full protocol text", schema=Payload
    )

    assert result == Payload(message="ok")
    transport.chat_completion.assert_called_once()
    kwargs = transport.chat_completion.call_args.kwargs
    assert kwargs["model"] == config.OPENROUTER_TEXT_MODEL
    assert kwargs["prompt"] == "full protocol text"
    assert kwargs["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "Payload",
            "strict": True,
            "schema": Payload.model_json_schema(),
        },
    }
    assert kwargs["extra_body"] == {
        "reasoning": {"effort": config.OPENROUTER_REASONING_EFFORT}
    }
    assert set(kwargs) == {"model", "prompt", "response_format", "extra_body"}


def test_llm_client_interface_has_no_history_parameters():
    json_parameters = set(inspect.signature(LLMClient.generate_json).parameters)
    image_parameters = set(inspect.signature(LLMClient.generate_image).parameters)
    decision_parameters = set(inspect.signature(LLMClient.decide).parameters)

    assert json_parameters == {"self", "role", "prompt", "schema"}
    assert image_parameters == {"self", "role", "prompt", "aspect_ratio"}
    assert decision_parameters == {"self", "role", "state", "questions"}


async def test_invalid_json_is_retried_three_times(transport):
    transport.chat_completion.side_effect = ["not json", "still not json", "nope"]

    with pytest.raises(LLMSchemaError, match="invalid JSON"):
        await _client().generate_json(role="planner", prompt="prompt", schema=Payload)

    assert transport.chat_completion.call_count == 3


async def test_schema_validation_is_retried_then_succeeds(transport):
    transport.chat_completion.side_effect = [
        '{"message": "ok", "extra": true}',
        '{"message": "ok"}',
    ]

    result = await _client().generate_json(
        role="planner", prompt="prompt", schema=Payload
    )

    assert result == Payload(message="ok")
    assert transport.chat_completion.call_count == 2


async def test_schema_validation_failure_stops_after_three_attempts(transport):
    transport.chat_completion.return_value = '{"unexpected": true}'

    with pytest.raises(LLMSchemaError, match="schema"):
        await _client().generate_json(role="planner", prompt="prompt", schema=Payload)

    assert transport.chat_completion.call_count == 3


async def test_transport_errors_are_retried_then_raised(transport):
    transport.chat_completion.side_effect = OpenRouterError("connection reset")

    with pytest.raises(LLMTransportError, match="connection reset"):
        await _client().generate_json(role="planner", prompt="prompt", schema=Payload)

    assert transport.chat_completion.call_count == 3


async def test_transport_error_recovers_within_retry_budget(transport):
    transport.chat_completion.side_effect = [
        OpenRouterError("temporary"),
        '{"message": "ok"}',
    ]

    result = await _client().generate_json(
        role="planner", prompt="prompt", schema=Payload
    )

    assert result == Payload(message="ok")
    assert transport.chat_completion.call_count == 2


@pytest.mark.parametrize("status_code", [401, 402, 403])
async def test_auth_status_codes_fail_immediately(transport, status_code):
    transport.chat_completion.side_effect = OpenRouterError(
        "account problem", status_code=status_code
    )

    with pytest.raises(LLMAuthenticationError):
        await _client().generate_json(role="planner", prompt="prompt", schema=Payload)

    assert transport.chat_completion.call_count == 1


@pytest.mark.parametrize(
    "message",
    [
        "Insufficient credits",
        "Permission denied",
        "Payment required",
        "Billing quota exceeded",
    ],
)
async def test_credit_or_permission_keywords_fail_immediately(transport, message):
    transport.chat_completion.side_effect = OpenRouterError(message)

    with pytest.raises(LLMAuthenticationError, match=message):
        await _client().generate_json(role="planner", prompt="prompt", schema=Payload)

    assert transport.chat_completion.call_count == 1


async def test_generate_image_passes_aspect_ratio_and_returns_bytes(transport):
    transport.generate_image.return_value = b"image-bytes"

    result = await _client().generate_image(
        role="summary_cover", prompt="abstract blue artwork", aspect_ratio="9:16"
    )

    assert result == b"image-bytes"
    transport.generate_image.assert_called_once_with(
        model=config.OPENROUTER_IMAGE_MODEL,
        prompt="abstract blue artwork",
        aspect_ratio="9:16",
    )


async def test_generate_image_retries_transport_errors(transport):
    transport.generate_image.side_effect = [
        OpenRouterError("temporary"),
        b"image-bytes",
    ]

    result = await _client().generate_image(
        role="cover", prompt="prompt", aspect_ratio="4:5"
    )

    assert result == b"image-bytes"
    assert transport.generate_image.call_count == 2


async def test_generate_image_auth_error_fails_immediately(transport):
    transport.generate_image.side_effect = OpenRouterError(
        "Insufficient credits", status_code=402
    )

    with pytest.raises(LLMAuthenticationError):
        await _client().generate_image(
            role="cover", prompt="prompt", aspect_ratio="4:5"
        )

    assert transport.generate_image.call_count == 1


async def test_generate_image_transport_errors_stop_after_three_attempts(transport):
    transport.generate_image.side_effect = OpenRouterError("connection reset")

    with pytest.raises(LLMTransportError):
        await _client().generate_image(
            role="cover", prompt="prompt", aspect_ratio="4:5"
        )

    assert transport.generate_image.call_count == 3


QUESTION = NoulQuestion(instructions="Is there an unintended border?")
IMAGE_STATE = [
    "Inspect this image",
    ImagePart(image_url=ImageURL(url="data:image/png;base64,AAAA")),
]


async def test_decide_serializes_typed_questions_and_validates_the_response(
    transport,
):
    transport.submit_decisions.return_value = {
        "model": "typesafe/jev-1.14",
        "answers": {
            "border_or_frame": {"type": "noul", "noul": 0.25}
        },
    }

    result = await _client(decision_model="custom/decision-model").decide(
        role="artifact_check",
        state=IMAGE_STATE,
        questions={"border_or_frame": QUESTION},
    )

    assert result.answers["border_or_frame"].noul == 0.25
    transport.submit_decisions.assert_called_once_with(
        model="custom/decision-model",
        state=[
            "Inspect this image",
            {
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64,AAAA"},
            },
        ],
        questions={
            "border_or_frame": {
                "type": "noul",
                "instructions": "Is there an unintended border?",
            }
        },
    )


async def test_decide_logs_every_result_at_info(transport, caplog):
    transport.submit_decisions.return_value = {
        "model": "typesafe/jev-1.14",
        "answers": {"border_or_frame": {"type": "noul", "noul": 0.25}},
    }

    with caplog.at_level(logging.INFO, logger=llm_client_module.__name__):
        await _client().decide(
            role="artifact_check",
            state="state",
            questions={"border_or_frame": QUESTION},
        )

    results = [
        record.getMessage()
        for record in caplog.records
        if "Jev decision result" in record.getMessage()
    ]
    assert len(results) == 1
    assert "role=artifact_check" in results[0]
    assert "model=typesafe/jev-1.14" in results[0]
    assert '"noul": 0.25' in results[0]


async def test_decide_logs_an_invalid_result_before_retrying(transport, caplog):
    transport.submit_decisions.side_effect = [
        {"answers": {"border_or_frame": {"type": "noul", "noul": 2.0}}},
        {"answers": {"border_or_frame": {"type": "noul", "noul": 0.1}}},
    ]

    with caplog.at_level(logging.INFO, logger=llm_client_module.__name__):
        await _client().decide(
            role="artifact_check",
            state="state",
            questions={"border_or_frame": QUESTION},
        )

    results = [
        record.getMessage()
        for record in caplog.records
        if "Jev decision result" in record.getMessage()
    ]
    assert len(results) == 2
    assert '"noul": 2.0' in results[0]
    assert '"noul": 0.1' in results[1]


async def test_decide_uses_the_configured_model_by_default(transport):
    transport.submit_decisions.return_value = {
        "answers": {"border_or_frame": {"type": "noul", "noul": 0.0}}
    }

    await _client().decide(
        role="artifact_check",
        state="state",
        questions={"border_or_frame": QUESTION},
    )

    kwargs = transport.submit_decisions.call_args.kwargs
    assert kwargs["model"] == config.OPENROUTER_DECISION_MODEL


async def test_decide_retries_schema_failures_then_succeeds(transport):
    transport.submit_decisions.side_effect = [
        {"answers": {"border_or_frame": {"type": "noul", "noul": 2.0}}},
        {"answers": {"border_or_frame": {"type": "noul", "noul": 0.1}}},
    ]

    result = await _client().decide(
        role="artifact_check",
        state="state",
        questions={"border_or_frame": QUESTION},
    )

    assert result.answers["border_or_frame"].noul == 0.1
    assert transport.submit_decisions.call_count == 2


async def test_decide_retries_transport_errors_then_succeeds(transport):
    transport.submit_decisions.side_effect = [
        OpenRouterError("temporary"),
        {"answers": {"border_or_frame": {"type": "noul", "noul": 0.1}}},
    ]

    result = await _client().decide(
        role="artifact_check",
        state="state",
        questions={"border_or_frame": QUESTION},
    )

    assert result.answers["border_or_frame"].noul == 0.1
    assert transport.submit_decisions.call_count == 2


async def test_decide_schema_errors_stop_after_three_attempts(transport):
    transport.submit_decisions.return_value = {"answers": {"border_or_frame": {}}}

    with pytest.raises(LLMSchemaError, match="decision schema"):
        await _client().decide(
            role="artifact_check",
            state="state",
            questions={"border_or_frame": QUESTION},
        )

    assert transport.submit_decisions.call_count == 3


async def test_decide_auth_error_fails_immediately(transport):
    transport.submit_decisions.side_effect = OpenRouterError(
        "Insufficient credits", status_code=402
    )

    with pytest.raises(LLMAuthenticationError):
        await _client().decide(
            role="artifact_check",
            state="state",
            questions={"border_or_frame": QUESTION},
        )

    assert transport.submit_decisions.call_count == 1
