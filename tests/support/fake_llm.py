"""Reusable test seam for the injected LLM port.

Tickets 03–09 script responses per role and inspect the recorded calls to
assert input isolation and error handling. Decision calls default to a clean
verdict so visual-pipeline tests only script the defect answers they need.
"""

from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.services.decision_models import (
    ChoiceAnswer,
    ChoiceQuestion,
    DecisionQuestion,
    DecisionResponse,
    DecisionState,
    NoulAnswer,
)


@dataclass(frozen=True)
class LLMCall:
    """One recorded call at the LLM port."""

    role: str
    prompt: str
    schema: type[BaseModel] | None = None
    aspect_ratio: str | None = None
    state: DecisionState | None = None
    questions: dict[str, DecisionQuestion] | None = None


class FakeLLMClient:
    """Deterministic ``LLMClient`` with scripted success/error responses."""

    def __init__(
        self,
        *,
        json_responses: Mapping[str, Iterable[object]] | None = None,
        image_responses: Mapping[str, Iterable[object]] | None = None,
        decision_responses: Mapping[str, Iterable[object]] | None = None,
    ):
        self._json_responses: dict[str, deque[object]] = defaultdict(deque)
        self._image_responses: dict[str, deque[object]] = defaultdict(deque)
        self._decision_responses: dict[str, deque[object]] = defaultdict(deque)
        self.calls: list[LLMCall] = []

        for role, responses in (json_responses or {}).items():
            self.script_json(role, *responses)
        for role, responses in (image_responses or {}).items():
            self.script_image(role, *responses)
        for role, responses in (decision_responses or {}).items():
            self.script_decision(role, *responses)

    def script_json(self, role: str, *responses: object) -> None:
        self._json_responses[role].extend(responses)

    def script_image(self, role: str, *responses: object) -> None:
        self._image_responses[role].extend(responses)

    def script_decision(self, role: str, *responses: object) -> None:
        self._decision_responses[role].extend(responses)

    @property
    def json_calls(self) -> list[LLMCall]:
        return [call for call in self.calls if call.schema is not None]

    @property
    def image_calls(self) -> list[LLMCall]:
        return [call for call in self.calls if call.aspect_ratio is not None]

    @property
    def decision_calls(self) -> list[LLMCall]:
        return [call for call in self.calls if call.questions is not None]

    def calls_for(self, role: str) -> list[LLMCall]:
        return [call for call in self.calls if call.role == role]

    async def generate_json(self, *, role: str, prompt: str, schema: type[BaseModel]) -> BaseModel:
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

    async def generate_image(self, *, role: str, prompt: str, aspect_ratio: str) -> bytes:
        self.calls.append(LLMCall(role=role, prompt=prompt, aspect_ratio=aspect_ratio))
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

    async def decide(
        self,
        *,
        role: str,
        state: DecisionState,
        questions: dict[str, DecisionQuestion],
    ) -> DecisionResponse:
        prompt = state if isinstance(state, str) else ""
        if isinstance(state, list) and state:
            prompt = state[0] if isinstance(state[0], str) else ""
        self.calls.append(
            LLMCall(
                role=role,
                prompt=prompt if isinstance(prompt, str) else "",
                state=state,
                questions=questions,
            )
        )
        responses = self._decision_responses[role]
        if not responses:
            return self._clean_response(questions)

        response = responses.popleft()
        if isinstance(response, Exception):
            raise response
        if isinstance(response, DecisionResponse):
            return response
        if isinstance(response, Mapping):
            if all(isinstance(value, (int, float)) for value in response.values()):
                return self._probability_response(questions, response)
            return DecisionResponse.model_validate(response)
        raise AssertionError(
            f"Decision response for role {role!r} must be a mapping, "
            f"DecisionResponse or Exception, got {response!r}"
        )

    @staticmethod
    def _clean_response(
        questions: dict[str, DecisionQuestion],
    ) -> DecisionResponse:
        return FakeLLMClient._probability_response(questions, {})

    @staticmethod
    def _probability_response(
        questions: dict[str, DecisionQuestion],
        probabilities: Mapping[str, Any],
    ) -> DecisionResponse:
        answers: dict[str, NoulAnswer | ChoiceAnswer] = {}
        for key, question in questions.items():
            if isinstance(question, ChoiceQuestion):
                options = list(question.criteria)
                selected = (
                    options[0] if options else ""
                )
                option_probabilities = {
                    option: (
                        float(probabilities.get(option, 0.0))
                        if not probabilities
                        or set(probabilities).issubset(set(options))
                        else 0.0
                    )
                    for option in options
                }
                if not probabilities and selected:
                    option_probabilities[selected] = 1.0
                answers[key] = ChoiceAnswer(
                    type="choice",
                    choice=selected,
                    confidence=option_probabilities.get(selected),
                    probabilities=option_probabilities,
                )
            else:
                answers[key] = NoulAnswer(
                    type="noul",
                    noul=float(probabilities.get(key, 0.0)),
                )
        return DecisionResponse(answers=answers)
