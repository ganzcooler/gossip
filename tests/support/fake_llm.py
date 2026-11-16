"""Reusable test seam for the injected LLM port.

Tickets 03–09 script responses per role and inspect the recorded calls to
assert input isolation and error handling.
"""

from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from pydantic import BaseModel


@dataclass(frozen=True)
class LLMCall:
    """One recorded call at the LLM port."""

    role: str
    prompt: str
    schema: type[BaseModel] | None = None
    aspect_ratio: str | None = None


class FakeLLMClient:
    """Deterministic ``LLMClient`` with scripted success/error responses."""

    def __init__(
        self,
        *,
        json_responses: Mapping[str, Iterable[object]] | None = None,
        image_responses: Mapping[str, Iterable[object]] | None = None,
    ):
        self._json_responses: dict[str, deque[object]] = defaultdict(deque)
        self._image_responses: dict[str, deque[object]] = defaultdict(deque)
        self.calls: list[LLMCall] = []

        for role, responses in (json_responses or {}).items():
            self.script_json(role, *responses)
        for role, responses in (image_responses or {}).items():
            self.script_image(role, *responses)

    def script_json(self, role: str, *responses: object) -> None:
        self._json_responses[role].extend(responses)

    def script_image(self, role: str, *responses: object) -> None:
        self._image_responses[role].extend(responses)

    @property
    def json_calls(self) -> list[LLMCall]:
        return [call for call in self.calls if call.schema is not None]

    @property
    def image_calls(self) -> list[LLMCall]:
        return [call for call in self.calls if call.aspect_ratio is not None]

    def calls_for(self, role: str) -> list[LLMCall]:
        return [call for call in self.calls if call.role == role]

    async def generate_json(
        self, *, role: str, prompt: str, schema: type[BaseModel]
    ) -> BaseModel:
        self.calls.append(LLMCall(role=role, prompt=prompt, schema=schema))
        responses = self._json_responses[role]
        if not responses:
            raise AssertionError(f"No scripted JSON response for role {role!r}")

        response = responses.popleft()
        if isinstance(response, Exception):
            raise response
        if isinstance(response, schema):
            return response
        if isinstance(response, BaseModel):
            return schema.model_validate(response.model_dump())
        return schema.model_validate(response)

    async def generate_image(
        self, *, role: str, prompt: str, aspect_ratio: str
    ) -> bytes:
        self.calls.append(
            LLMCall(role=role, prompt=prompt, aspect_ratio=aspect_ratio)
        )
        responses = self._image_responses[role]
        if not responses:
            raise AssertionError(f"No scripted image response for role {role!r}")

        response = responses.popleft()
        if isinstance(response, Exception):
            raise response
        if not isinstance(response, bytes):
            raise AssertionError(
                f"Image response for role {role!r} must be bytes, got {response!r}"
            )
        return response
