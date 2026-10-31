"""Small OpenRouter client used for text and image generation.

The application talks to OpenRouter's OpenAI-compatible chat endpoint for text
and to the dedicated Image API for generated images. Keeping both calls in one
module makes the service layer easy to test and avoids leaking HTTP details into
the article/image generators.
"""

import base64
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.core import config

logger = logging.getLogger(__name__)


@dataclass
class ChatCompletionResult:
    """Text response plus provider usage and cost metadata."""

    content: str
    usage: dict[str, Any]


@dataclass
class ImageGenerationResult:
    """Image bytes plus provider usage and cost metadata."""

    image_bytes: bytes
    usage: dict[str, Any]


class OpenRouterError(Exception):
    """Raised when an OpenRouter request fails."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _headers() -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {config.load_openrouter_api_key()}",
        "Content-Type": "application/json",
    }
    if config.OPENROUTER_SITE_URL:
        headers["HTTP-Referer"] = config.OPENROUTER_SITE_URL
    if config.OPENROUTER_APP_NAME:
        headers["X-OpenRouter-Title"] = config.OPENROUTER_APP_NAME
    return headers


def _error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text or f"HTTP {response.status_code}"

    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error)
    if isinstance(error, str):
        return error
    if isinstance(payload, dict):
        return str(payload.get("message") or payload)
    return response.text or f"HTTP {response.status_code}"


def _post(path: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    url = f"{config.OPENROUTER_BASE_URL.rstrip('/')}{path}"
    try:
        response = httpx.post(url, headers=_headers(), json=payload, timeout=timeout)
    except httpx.HTTPError as exc:
        raise OpenRouterError(f"OpenRouter request failed: {exc}") from exc

    if response.status_code >= 400:
        raise OpenRouterError(
            f"OpenRouter HTTP {response.status_code}: {_error_message(response)}",
            status_code=response.status_code,
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise OpenRouterError("OpenRouter returned invalid JSON") from exc

    if not isinstance(payload, dict):
        raise OpenRouterError(f"Unexpected OpenRouter response: {payload!r}")
    return payload


def chat_completion(
    *,
    model: str,
    prompt: str,
    temperature: float | None = None,
    response_format: dict[str, Any] | None = None,
    max_tokens: int | None = None,
    extra_body: dict[str, Any] | None = None,
    timeout: float = 120.0,
) -> str:
    """Run a single-prompt chat completion and return the text response."""
    return chat_completion_result(
        model=model,
        prompt=prompt,
        temperature=temperature,
        response_format=response_format,
        max_tokens=max_tokens,
        extra_body=extra_body,
        timeout=timeout,
    ).content


def chat_completion_result(
    *,
    model: str,
    prompt: str,
    temperature: float | None = None,
    response_format: dict[str, Any] | None = None,
    max_tokens: int | None = None,
    extra_body: dict[str, Any] | None = None,
    timeout: float = 120.0,
) -> ChatCompletionResult:
    """Run a single-prompt chat completion with usage/cost metadata."""
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "usage": {"include": True},
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if response_format is not None:
        payload["response_format"] = response_format
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if extra_body:
        payload.update(extra_body)

    data = _post("/chat/completions", payload, timeout)
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise OpenRouterError(f"Unexpected OpenRouter chat response: {data!r}") from exc

    if isinstance(content, list):
        content = "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    if content is None:
        content = ""
    usage = data.get("usage")
    return ChatCompletionResult(
        content=str(content).strip(),
        usage=usage if isinstance(usage, dict) else {},
    )


def generate_image(
    *,
    model: str,
    prompt: str,
    aspect_ratio: str = "9:16",
    timeout: float = 300.0,
) -> bytes:
    """Generate one image and return the decoded image bytes."""
    return generate_image_result(
        model=model,
        prompt=prompt,
        aspect_ratio=aspect_ratio,
        timeout=timeout,
    ).image_bytes


def generate_image_result(
    *,
    model: str,
    prompt: str,
    aspect_ratio: str = "9:16",
    timeout: float = 300.0,
) -> ImageGenerationResult:
    """Generate one image with usage/cost metadata."""
    payload = {
        "model": model,
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "n": 1,
    }
    data = _post("/images", payload, timeout)

    try:
        image = data["data"][0]
        encoded = image["b64_json"]
    except (KeyError, IndexError, TypeError) as exc:
        raise OpenRouterError(f"Unexpected OpenRouter image response: {data!r}") from exc

    try:
        image_bytes = base64.b64decode(encoded, validate=True)
    except (TypeError, ValueError) as exc:
        raise OpenRouterError("OpenRouter returned invalid base64 image data") from exc

    usage = data.get("usage")
    return ImageGenerationResult(
        image_bytes=image_bytes,
        usage=usage if isinstance(usage, dict) else {},
    )
