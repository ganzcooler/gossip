"""Behaviour tests for Jev-assisted and deterministic topic kickers."""

import pytest

from app.core.post_models import TopicDraft
from app.services.decision_models import ChoiceAnswer, DecisionResponse
from app.services.llm_client import LLMError
from app.services.slide_composer import compose_topic_slides
from app.services.topic_kicker_writer import (
    TOPIC_KICKER_ROLE,
    apply_topic_kickers,
    choose_topic_kicker,
    kicker_choice_candidates,
    kicker_word_candidates,
    resolve_topic_kickers,
)
from app.services.topic_kickers import (
    DEFAULT_TOPIC_KICKER,
    derive_topic_kicker,
    fit_topic_kicker,
    format_follow_counter,
    kicker_candidates,
    kicker_char_budget,
    kicker_fits,
    shorten_topic_kicker,
)
from tests.support.fake_llm import FakeLLMClient


def _paragraph(seed: str, length: int) -> str:
    text = ""
    while len(text) < length:
        text = f"{text} {seed}".strip()
    if len(text) > length:
        text = text[:length].rsplit(" ", 1)[0]
    return text.rstrip(" ,;") + "."


def _draft(*, first_h2: str = "Der Rat hat den Haushalt beschlossen") -> TopicDraft:
    return TopicDraft(
        title="Was der Rat zum Haushalt in Rosdorf entschieden hat",
        sections=[
            {
                "h2": first_h2,
                "paragraphs": [
                    _paragraph(
                        "Der Rat hat den Haushalt einstimmig beschlossen und "
                        "die Mittel für alle Ortsteile freigegeben.",
                        700,
                    )
                ],
            },
            {
                "h2": "Der Radweg wird im Sommer gebaut",
                "paragraphs": [
                    _paragraph(
                        "Der Radweg an der Hauptstraße wird im Sommer gebaut "
                        "und verbindet die Ortsteile besser.",
                        700,
                    )
                ],
            },
        ],
    )


def _section_slides(composition, section_index: int):
    return [
        slide
        for slide in composition.slides[1:]
        if slide.section_index == section_index
    ]


def _counters(composition, section_index: int) -> tuple[str, ...]:
    content_total = len(composition.slides) - 1
    return tuple(
        format_follow_counter(int(slide.content_position), content_total)
        for slide in _section_slides(composition, section_index)
    )


def _choice(
    *,
    selected: str,
    probabilities: dict[str, float] | None = None,
) -> DecisionResponse:
    return DecisionResponse(
        answers={
            "kicker": ChoiceAnswer(
                type="choice",
                choice=selected,
                probabilities=probabilities,
            )
        }
    )


def test_shorten_topic_kicker_strips_common_compound_heads():
    assert shorten_topic_kicker("DRINGLICHKEITSLISTE") == "DRINGLICHKEIT"
    assert shorten_topic_kicker("HAUSHALTSPLAN") == "HAUSHALT"
    assert shorten_topic_kicker("VERWALTUNGSAUSSCHUSS") == "VERWALTUNG"
    assert shorten_topic_kicker("RADWEG") is None


def test_kicker_candidates_are_progressive_and_never_repeat():
    candidates = kicker_candidates("Dringlichkeitsliste bis September")

    assert candidates == ("DRINGLICHKEITSLISTE", "DRINGLICHKEIT")
    assert len(set(candidates)) == len(candidates)


def test_kicker_word_candidates_strip_punctuation_and_deduplicate():
    assert kicker_word_candidates(
        "Der Rat hat den Haushalt, den Haushalt beschlossen."
    ) == ("Der", "Rat", "hat", "den", "Haushalt", "beschlossen")


def test_kicker_choice_candidates_add_shortened_compounds():
    assert kicker_choice_candidates(
        "Dringlichkeitsliste bis September"
    ) == (
        "Dringlichkeitsliste",
        "bis",
        "September",
        "DRINGLICHKEIT",
    )


def test_kicker_fit_uses_the_combined_counter_width_at_body_size_plus_two():
    counter = format_follow_counter(4, 4)
    assert counter == "04/04"
    assert derive_topic_kicker("Dringlichkeitsliste bis September") == (
        "DRINGLICHKEITSLISTE"
    )
    assert not kicker_fits(
        "DRINGLICHKEITSLISTE", body_size=42, counters=[counter]
    )
    assert fit_topic_kicker(
        "Dringlichkeitsliste bis September",
        body_size=42,
        counters=[counter],
    ) == "DRINGLICHKEIT"
    assert kicker_char_budget(body_size=42, counters=[counter]) >= 12


def test_composer_shortens_a_compound_kicker_when_the_full_word_overflows():
    draft = _draft(first_h2="Dringlichkeitsliste bis September")
    composition = compose_topic_slides(draft)

    assert composition.body_size == 42
    assert {slide.kicker for slide in _section_slides(composition, 0)} == {
        "DRINGLICHKEIT"
    }
    assert {
        entry["kicker"]
        for entry in composition.slide_plan["slides"]
        if entry["section_index"] == 0
    } == {"DRINGLICHKEIT"}


def test_composer_accepts_explicit_section_kickers():
    draft = _draft()
    composition = compose_topic_slides(draft, kickers={0: "HAUSHALT"})

    assert {slide.kicker for slide in _section_slides(composition, 0)} == {
        "HAUSHALT"
    }
    assert {slide.kicker for slide in _section_slides(composition, 1)} == {
        "RADWEG"
    }


@pytest.mark.asyncio
async def test_resolver_sends_the_complete_h2_to_jev_and_takes_the_top_choice():
    draft = _draft(first_h2="Der Rat hat den Haushalt beschlossen")
    composition = compose_topic_slides(draft)
    fake = FakeLLMClient(
        decision_responses={
            TOPIC_KICKER_ROLE: [
                _choice(
                    selected="Haushalt",
                    probabilities={
                        "Haushalt": 0.9,
                        "Rat": 0.2,
                        "beschlossen": 0.1,
                    },
                ),
                _choice(selected="Radweg", probabilities={"Radweg": 0.9}),
            ]
        }
    )

    resolved = await resolve_topic_kickers(draft, composition, fake)

    assert {slide.kicker for slide in _section_slides(resolved, 0)} == {
        "HAUSHALT"
    }
    assert {slide.kicker for slide in _section_slides(resolved, 1)} == {
        "RADWEG"
    }
    call = fake.calls_for(TOPIC_KICKER_ROLE)[0]
    assert call.state == "Der Rat hat den Haushalt beschlossen"
    question = call.questions["kicker"]
    assert set(question.criteria) == {
        "Der",
        "Rat",
        "hat",
        "den",
        "Haushalt",
        "beschlossen",
    }
    assert "German noun" in question.instructions


@pytest.mark.asyncio
async def test_resolver_offers_shortened_compounds_to_jev():
    h2 = "Dringlichkeitsliste bis September"
    draft = _draft(first_h2=h2)
    composition = compose_topic_slides(draft)
    fake = FakeLLMClient(
        decision_responses={
            TOPIC_KICKER_ROLE: [
                _choice(
                    selected="Dringlichkeitsliste",
                    probabilities={
                        "Dringlichkeitsliste": 0.9,
                        "September": 0.8,
                        "bis": 0.1,
                    },
                ),
                _choice(selected="Radweg", probabilities={"Radweg": 0.9}),
            ]
        }
    )

    await resolve_topic_kickers(draft, composition, fake)

    question = fake.calls_for(TOPIC_KICKER_ROLE)[0].questions["kicker"]
    assert "DRINGLICHKEIT" in question.criteria
    assert question.criteria["DRINGLICHKEIT"] == "Candidate label: DRINGLICHKEIT"


@pytest.mark.asyncio
async def test_resolver_reuses_stored_kickers_without_calling_jev():
    draft = _draft()
    composition = compose_topic_slides(draft)
    first = FakeLLMClient(
        decision_responses={
            TOPIC_KICKER_ROLE: [
                _choice(selected="Haushalt", probabilities={"Haushalt": 0.9}),
                _choice(selected="Radweg", probabilities={"Radweg": 0.9}),
            ]
        }
    )
    resolved = await resolve_topic_kickers(draft, composition, first)
    assert resolved.slide_plan["kickers_resolved"] is True

    second = FakeLLMClient()
    reused = await resolve_topic_kickers(draft, resolved, second)

    assert second.calls_for(TOPIC_KICKER_ROLE) == []
    assert {slide.kicker for slide in _section_slides(reused, 0)} == {
        "HAUSHALT"
    }
    assert {slide.kicker for slide in _section_slides(reused, 1)} == {
        "RADWEG"
    }


@pytest.mark.asyncio
async def test_resolver_re_resolves_a_legacy_stored_kicker():
    draft = _draft()
    composition = compose_topic_slides(draft)
    first = FakeLLMClient(
        decision_responses={
            TOPIC_KICKER_ROLE: [
                _choice(selected="Haushalt", probabilities={"Haushalt": 0.9}),
                _choice(selected="Radweg", probabilities={"Radweg": 0.9}),
            ]
        }
    )
    resolved = await resolve_topic_kickers(draft, composition, first)
    legacy = apply_topic_kickers(resolved, {0: "THEMA"})
    fake = FakeLLMClient(
        decision_responses={
            TOPIC_KICKER_ROLE: [
                _choice(selected="Haushalt", probabilities={"Haushalt": 0.9})
            ]
        }
    )

    renewed = await resolve_topic_kickers(draft, legacy, fake)

    assert len(fake.calls_for(TOPIC_KICKER_ROLE)) == 1
    assert {slide.kicker for slide in _section_slides(renewed, 0)} == {
        "HAUSHALT"
    }
    assert {slide.kicker for slide in _section_slides(renewed, 1)} == {
        "RADWEG"
    }


@pytest.mark.asyncio
async def test_resolver_re_resolves_a_stored_kicker_that_no_longer_fits():
    draft = _draft()
    composition = compose_topic_slides(draft)
    first = FakeLLMClient(
        decision_responses={
            TOPIC_KICKER_ROLE: [
                _choice(selected="Haushalt", probabilities={"Haushalt": 0.9}),
                _choice(selected="Radweg", probabilities={"Radweg": 0.9}),
            ]
        }
    )
    resolved = await resolve_topic_kickers(draft, composition, first)
    too_wide = apply_topic_kickers(
        resolved, {0: "VERWALTUNGSAUSSCHUSS"}
    )
    fake = FakeLLMClient(
        decision_responses={
            TOPIC_KICKER_ROLE: [
                _choice(selected="Haushalt", probabilities={"Haushalt": 0.9})
            ]
        }
    )

    renewed = await resolve_topic_kickers(draft, too_wide, fake)

    assert len(fake.calls_for(TOPIC_KICKER_ROLE)) == 1
    assert {slide.kicker for slide in _section_slides(renewed, 0)} == {
        "HAUSHALT"
    }
    assert {slide.kicker for slide in _section_slides(renewed, 1)} == {
        "RADWEG"
    }


@pytest.mark.asyncio
async def test_resolver_skips_a_too_wide_top_choice_and_takes_the_next():
    h2 = "Dringlichkeitsliste bis September"
    draft = _draft(first_h2=h2)
    composition = compose_topic_slides(draft)
    body_size = composition.body_size
    counters = _counters(composition, 0)
    assert not kicker_fits(
        "DRINGLICHKEITSLISTE",
        body_size=body_size,
        counters=counters,
    )
    fake = FakeLLMClient(
        decision_responses={
            TOPIC_KICKER_ROLE: [
                _choice(
                    selected="Dringlichkeitsliste",
                    probabilities={
                        "Dringlichkeitsliste": 0.9,
                        "September": 0.8,
                        "bis": 0.1,
                    },
                ),
                _choice(selected="Radweg", probabilities={"Radweg": 0.9}),
            ]
        }
    )

    resolved = await resolve_topic_kickers(draft, composition, fake)

    assert {slide.kicker for slide in _section_slides(resolved, 0)} == {
        "SEPTEMBER"
    }


@pytest.mark.asyncio
async def test_resolver_falls_back_to_the_deterministic_chain_when_jev_fails():
    h2 = "Dringlichkeitsliste bis September"
    draft = _draft(first_h2=h2)
    composition = compose_topic_slides(draft)
    fake = FakeLLMClient(
        decision_responses={
            TOPIC_KICKER_ROLE: [LLMError("decisions unavailable")]
        }
    )

    resolved = await resolve_topic_kickers(draft, composition, fake)

    assert {slide.kicker for slide in _section_slides(resolved, 0)} == {
        "DRINGLICHKEIT"
    }


@pytest.mark.asyncio
async def test_resolver_shortens_a_single_compound_heading_without_jev():
    h2 = "Dringlichkeitslisten"
    draft = _draft(first_h2=h2)
    composition = compose_topic_slides(draft)
    fake = FakeLLMClient()

    resolved = await resolve_topic_kickers(draft, composition, fake)

    assert {slide.kicker for slide in _section_slides(resolved, 0)} == {
        "DRINGLICHKEIT"
    }
    assert all(
        call.state != h2 for call in fake.calls_for(TOPIC_KICKER_ROLE)
    )


@pytest.mark.asyncio
async def test_resolver_falls_back_to_content_words_when_the_chain_does_not_fit():
    h2 = "Grundstücksverkehr September"
    draft = _draft(first_h2=h2)
    composition = compose_topic_slides(draft)
    fake = FakeLLMClient(
        decision_responses={
            TOPIC_KICKER_ROLE: [LLMError("decisions unavailable")]
        }
    )

    resolved = await resolve_topic_kickers(draft, composition, fake)

    assert {slide.kicker for slide in _section_slides(resolved, 0)} == {
        "SEPTEMBER"
    }


@pytest.mark.asyncio
async def test_resolver_uses_aktuell_when_no_heading_word_fits():
    h2 = "Personalentscheidung"
    draft = _draft(first_h2=h2)
    composition = compose_topic_slides(draft)

    candidate = await choose_topic_kicker(
        h2,
        body_size=composition.body_size,
        max_chars=6,
        counters=_counters(composition, 0),
        llm=FakeLLMClient(),
    )
    assert candidate is None

    resolved = await resolve_topic_kickers(
        draft, composition, FakeLLMClient()
    )

    assert {slide.kicker for slide in _section_slides(resolved, 0)} == {
        DEFAULT_TOPIC_KICKER
    }
    assert all(
        slide.kicker != "THEMA"
        for slide in resolved.slides
        if slide.slide_type != "cover"
    )


@pytest.mark.asyncio
async def test_resolver_replaces_a_legacy_thema_kicker():
    draft = _draft()
    composition = compose_topic_slides(draft)
    legacy = apply_topic_kickers(composition, {0: "THEMA", 1: "THEMA"})
    fake = FakeLLMClient(
        decision_responses={
            TOPIC_KICKER_ROLE: [
                _choice(selected="Haushalt", probabilities={"Haushalt": 0.9}),
                _choice(selected="Radweg", probabilities={"Radweg": 0.9}),
            ]
        }
    )

    resolved = await resolve_topic_kickers(draft, legacy, fake)

    assert {slide.kicker for slide in _section_slides(resolved, 0)} == {
        "HAUSHALT"
    }
    assert {slide.kicker for slide in _section_slides(resolved, 1)} == {
        "RADWEG"
    }
    assert len(fake.calls_for(TOPIC_KICKER_ROLE)) == 2


@pytest.mark.asyncio
async def test_resolver_updates_the_slide_plan_with_the_resolved_kickers():
    draft = _draft()
    composition = compose_topic_slides(draft)
    fake = FakeLLMClient(
        decision_responses={
            TOPIC_KICKER_ROLE: [
                _choice(selected="Haushalt", probabilities={"Haushalt": 0.9}),
                _choice(selected="Radweg", probabilities={"Radweg": 0.9}),
            ]
        }
    )

    resolved = await resolve_topic_kickers(draft, composition, fake)

    plan_kickers = {
        entry["section_index"]: entry["kicker"]
        for entry in resolved.slide_plan["slides"]
    }
    assert plan_kickers == {0: "HAUSHALT", 1: "RADWEG"}
