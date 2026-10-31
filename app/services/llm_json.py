"""Small helpers for single-purpose OpenRouter calls.

Every call is a fresh context: one prompt, one JSON schema, no conversation
history. The helpers own retries, auth-error detection, and JSON parsing so the
prompt services stay focused on their domain task.
"""

import logging
import re
import time
from typing import Type, TypeVar

from pydantic import BaseModel

from app.core import config
from app.services import openrouter_client
from app.services.errors import (
    AuthenticationError,
    PostGenerationError,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def is_auth_error(exception: Exception) -> bool:
    """Return True for errors that cannot be fixed by retrying."""
    status = getattr(exception, "status_code", None)
    if status is None:
        status = getattr(exception, "status", None)
    if status is None:
        status = getattr(exception, "code", None)

    if status in (401, 402, 403):
        return True

    error_str = str(exception).lower()
    fatal_keywords = [
        "unauthorized",
        "forbidden",
        "api key",
        "authentication",
        "permission denied",
        "payment required",
        "insufficient credit",
        "credits depleted",
    ]
    return any(keyword in error_str for keyword in fatal_keywords)


def strip_code_fences(text: str) -> str:
    """Remove optional Markdown fences around a JSON response."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _reasoning_config(effort: str | None) -> dict:
    if effort is None:
        return {"enabled": False}
    return {"effort": effort}


def call_json(
    *,
    prompt: str,
    model: Type[T],
    call_label: str | None = None,
    max_tokens: int = 8192,
    temperature: float | None = None,
    reasoning_effort: str | None = "medium",
    max_retries: int = 3,
    timeout: float = 180.0,
) -> T:
    """Run one prompt and validate the response against a Pydantic model."""
    label = call_label or model.__name__
    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": model.__name__.lower(),
            "strict": True,
            "schema": model.model_json_schema(),
        },
    }

    last_error: Exception | None = None
    for attempt in range(max_retries):
        started = time.monotonic()
        try:
            logger.info(
                "LLM call %s start model=%s reasoning=%s max_tokens=%s attempt=%s/%s",
                label,
                config.OPENROUTER_TEXT_MODEL,
                reasoning_effort or "off",
                max_tokens,
                attempt + 1,
                max_retries,
            )
            raw = openrouter_client.chat_completion(
                model=config.OPENROUTER_TEXT_MODEL,
                prompt=prompt,
                temperature=temperature,
                response_format=response_format,
                max_tokens=max_tokens,
                timeout=timeout,
                extra_body={
                    "reasoning": _reasoning_config(reasoning_effort)
                },
            )

            if not raw:
                logger.warning(
                    "LLM call %s returned an empty response on attempt %s/%s",
                    label,
                    attempt + 1,
                    max_retries,
                )
                if attempt < max_retries - 1:
                    time.sleep(config.API_CALL_DELAY_SECONDS)
                continue

            parsed = model.model_validate_json(strip_code_fences(raw))
            logger.info(
                "LLM call %s ok in %.2fs chars=%s",
                label,
                time.monotonic() - started,
                len(raw),
            )
            return parsed

        except Exception as exc:
            logger.error(
                "LLM call %s failed on attempt %s/%s after %.2fs: %s",
                label,
                attempt + 1,
                max_retries,
                time.monotonic() - started,
                exc,
                exc_info=True,
            )
            if is_auth_error(exc):
                raise AuthenticationError(f"Authentication failed: {exc}") from exc
            last_error = exc

        if attempt < max_retries - 1:
            time.sleep(config.API_CALL_DELAY_SECONDS)

    raise PostGenerationError(
        f"{model.__name__} generation failed after {max_retries} attempts: {last_error}"
    )


def call_text(
    *,
    prompt: str,
    call_label: str | None = None,
    max_tokens: int = 2048,
    temperature: float | None = None,
    reasoning_effort: str | None = "medium",
    max_retries: int = 3,
    timeout: float = 180.0,
) -> str:
    """Run one prompt and return plain text, with retries and auth handling."""
    label = call_label or "text"
    last_error: Exception | None = None
    for attempt in range(max_retries):
        started = time.monotonic()
        try:
            logger.info(
                "LLM call %s start model=%s reasoning=%s max_tokens=%s attempt=%s/%s",
                label,
                config.OPENROUTER_TEXT_MODEL,
                reasoning_effort or "off",
                max_tokens,
                attempt + 1,
                max_retries,
            )
            raw = openrouter_client.chat_completion(
                model=config.OPENROUTER_TEXT_MODEL,
                prompt=prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                extra_body={
                    "reasoning": _reasoning_config(reasoning_effort)
                },
            )
            if raw:
                logger.info(
                    "LLM call %s ok in %.2fs chars=%s",
                    label,
                    time.monotonic() - started,
                    len(raw),
                )
                return raw.strip()
            logger.warning(
                "LLM call %s returned an empty response on attempt %s/%s",
                label,
                attempt + 1,
                max_retries,
            )
        except Exception as exc:
            logger.error(
                "LLM call %s failed on attempt %s/%s after %.2fs: %s",
                label,
                attempt + 1,
                max_retries,
                time.monotonic() - started,
                exc,
                exc_info=True,
            )
            if is_auth_error(exc):
                raise AuthenticationError(f"Authentication failed: {exc}") from exc
            last_error = exc

        if attempt < max_retries - 1:
            time.sleep(config.API_CALL_DELAY_SECONDS)

    raise PostGenerationError(
        f"Text generation failed after {max_retries} attempts: {last_error}"
    )
