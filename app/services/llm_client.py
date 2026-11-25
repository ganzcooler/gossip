"""Stateless LLM port used by the post pipeline and OpenRouter adapter.

Every call carries only the current role input. There is deliberately no
message history, session, or conversation argument on the interface. The
adapter wraps the synchronous :mod:`app.services.openrouter_client` with
``asyncio.to_thread`` and turns transport/schema failures into a small, fixed
retry budget while stopping immediately on authentication or account errors.
"""

import asyncio
import json
import logging
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ValidationError

from app.core import config
from app.services import openrouter_client
from app.services.decision_models import (
    DecisionResponse,
    DecisionState,
    ImagePart,
    NoulQuestion,
)
from app.services.openrouter_client import OpenRouterError

logger = logging.getLogger(__name__)

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_RETRY_DELAY_SECONDS = 0.5

_ACCOUNT_ERROR_KEYWORDS = (
    "credit",
    "permission",
    "unauthorized",
    "payment",
    "billing",
    "quota",
)


class LLMError(Exception):
    """Base class for failures at the LLM port boundary."""


class LLMTransportError(LLMError):
    """The provider could not be reached or returned a transport failure."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class LLMSchemaError(LLMError):
    """The provider response was not JSON or did not match the schema."""


class LLMAuthenticationError(LLMError):
    """Authentication or account failure that must not be retried."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@runtime_checkable
class LLMClient(Protocol):
    """Injectable port for stateless text and image generation."""

    async def generate_json(
        self, *, role: str, prompt: str, schema: type[BaseModel]
    ) -> BaseModel:
        """Generate one JSON object and validate it against ``schema``."""

    async def generate_image(
        self, *, role: str, prompt: str, aspect_ratio: str
    ) -> bytes:
        """Generate one image for ``prompt`` at ``aspect_ratio``."""

    async def decide(
        self,
        *,
        role: str,
        state: DecisionState,
        questions: dict[str, NoulQuestion],
    ) -> DecisionResponse:
        """Answer typed ``noul`` questions about ``state``."""


def _is_account_error(error: OpenRouterError) -> bool:
    if error.status_code in {401, 402, 403}:
        return True
    message = str(error).casefold()
    return any(keyword in message for keyword in _ACCOUNT_ERROR_KEYWORDS)


class OpenRouterLLMClient:
    """``LLMClient`` adapter around the synchronous OpenRouter transport."""

    def __init__(
        self,
        *,
        text_model: str | None = None,
        image_model: str | None = None,
        decision_model: str | None = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        retry_delay: float = DEFAULT_RETRY_DELAY_SECONDS,
    ):
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self._text_model = text_model
        self._image_model = image_model
        self._decision_model = decision_model
        self._max_attempts = max_attempts
        self._retry_delay = retry_delay

    @property
    def text_model(self) -> str:
        return self._text_model or config.OPENROUTER_TEXT_MODEL

    @property
    def image_model(self) -> str:
        return self._image_model or config.OPENROUTER_IMAGE_MODEL

    @property
    def decision_model(self) -> str:
        return self._decision_model or config.OPENROUTER_DECISION_MODEL

    async def _wait_before_retry(self) -> None:
        if self._retry_delay > 0:
            await asyncio.sleep(self._retry_delay)

    def _classify_transport_error(self, error: OpenRouterError) -> LLMError:
        if _is_account_error(error):
            return LLMAuthenticationError(str(error), status_code=error.status_code)
        return LLMTransportError(str(error), status_code=error.status_code)

    async def generate_json(
        self, *, role: str, prompt: str, schema: type[BaseModel]
    ) -> BaseModel:
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": schema.__name__,
                "strict": True,
                "schema": schema.model_json_schema(),
            },
        }
        last_error: LLMError | None = None

        for attempt in range(1, self._max_attempts + 1):
            try:
                content = await asyncio.to_thread(
                    openrouter_client.chat_completion,
                    model=self.text_model,
                    prompt=prompt,
                    response_format=response_format,
                    extra_body={
                        "reasoning": {"effort": config.OPENROUTER_REASONING_EFFORT}
                    },
                )
            except OpenRouterError as exc:
                error = self._classify_transport_error(exc)
                if isinstance(error, LLMAuthenticationError):
                    raise error from exc
                last_error = error
            else:
                try:
                    payload = json.loads(content)
                except (json.JSONDecodeError, TypeError) as exc:
                    last_error = LLMSchemaError(
                        f"LLM returned invalid JSON for {schema.__name__}: {exc}"
                    )
                else:
                    try:
                        return schema.model_validate(payload)
                    except ValidationError as exc:
                        last_error = LLMSchemaError(
                            f"LLM schema validation failed for {schema.__name__}: {exc}"
                        )

            if attempt < self._max_attempts:
                logger.warning(
                    "LLM %s call attempt %s/%s failed: %s",
                    role,
                    attempt,
                    self._max_attempts,
                    last_error,
                )
                await self._wait_before_retry()

        assert last_error is not None
        raise last_error

    async def generate_image(
        self, *, role: str, prompt: str, aspect_ratio: str
    ) -> bytes:
        last_error: LLMError | None = None

        for attempt in range(1, self._max_attempts + 1):
            try:
                return await asyncio.to_thread(
                    openrouter_client.generate_image,
                    model=self.image_model,
                    prompt=prompt,
                    aspect_ratio=aspect_ratio,
                )
            except OpenRouterError as exc:
                error = self._classify_transport_error(exc)
                if isinstance(error, LLMAuthenticationError):
                    raise error from exc
                last_error = error

            if attempt < self._max_attempts:
                logger.warning(
                    "LLM %s image attempt %s/%s failed: %s",
                    role,
                    attempt,
                    self._max_attempts,
                    last_error,
                )
                await self._wait_before_retry()

        assert last_error is not None
        raise last_error

    @staticmethod
    def _decision_state_payload(state: DecisionState) -> str | list[object]:
        if isinstance(state, str):
            return state
        return [
            part.model_dump(mode="json", exclude_none=True) if isinstance(part, ImagePart) else part
            for part in state
        ]

    async def decide(
        self,
        *,
        role: str,
        state: DecisionState,
        questions: dict[str, NoulQuestion],
    ) -> DecisionResponse:
        state_payload = self._decision_state_payload(state)
        questions_payload = {
            key: question.model_dump(mode="json", exclude_none=True)
            for key, question in questions.items()
        }
        last_error: LLMError | None = None

        for attempt in range(1, self._max_attempts + 1):
            try:
                payload = await asyncio.to_thread(
                    openrouter_client.submit_decisions,
                    model=self.decision_model,
                    state=state_payload,
                    questions=questions_payload,
                )
            except OpenRouterError as exc:
                error = self._classify_transport_error(exc)
                if isinstance(error, LLMAuthenticationError):
                    raise error from exc
                last_error = error
            else:
                try:
                    return DecisionResponse.model_validate(payload)
                except ValidationError as exc:
                    last_error = LLMSchemaError(f"LLM decision schema validation failed: {exc}")

            if attempt < self._max_attempts:
                logger.warning(
                    "LLM %s decision attempt %s/%s failed: %s",
                    role,
                    attempt,
                    self._max_attempts,
                    last_error,
                )
                await self._wait_before_retry()

        assert last_error is not None
        raise last_error
