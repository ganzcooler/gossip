"""Behaviour tests for deterministic and LLM-assisted topic kickers."""

import pytest

from app.core.post_models import TopicDraft, TopicKicker
from app.services.slide_composer import compose_topic_slides
from app.services.topic_kicker_writer import (
    TOPIC_KICKER_ROLE,
    apply_topic_kickers,
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


def test_shorten_topic_kicker_strips_common_compound_heads():
    assert shorten_topic_kicker("DRINGLICHKEITSLISTE") == "DRINGLICHKEIT"
    assert shorten_topic_kicker("HAUSHALTSPLAN") == "HAUSHALT"
    assert shorten_topic_kicker("VERWALTUNGSAUSSCHUSS") == "VERWALTUNG"
    assert shorten_topic_kicker("RADWEG") is None


def test_kicker_candidates_are_progressive_and_never_repeat():
    candidates = kicker_candidates("Dringlichkeitsliste bis September")

    assert candidates == ("DRINGLICHKEITSLISTE", "DRINGLICHKEIT")
    assert len(set(candidates)) == len(candidates)


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
async def test_resolver_uses_the_kicker_writer_when_no_deterministic_word_fits():
    draft = _draft(first_h2="Donaudampfschifffahrt")
    composition = compose_topic_slides(draft)
    assert {slide.kicker for slide in _section_slides(composition, 0)} == {
        "DONAUDAMPFSCHIFFFAHRT"
    }

    fake = FakeLLMClient(
        json_responses={
            TOPIC_KICKER_ROLE: [
                TopicKicker(kicker="SCHIFFFAHRT"),
            ]
        }
    )

    resolved = await resolve_topic_kickers(draft, composition, fake)

    assert {slide.kicker for slide in _section_slides(resolved, 0)} == {
        "SCHIFFFAHRT"
    }
    assert {
        entry["kicker"]
        for entry in resolved.slide_plan["slides"]
        if entry["section_index"] == 0
    } == {"SCHIFFFAHRT"}
    assert len(fake.calls_for(TOPIC_KICKER_ROLE)) == 1
    prompt = fake.calls_for(TOPIC_KICKER_ROLE)[0].prompt
    assert "Donaudampfschifffahrt" in prompt
    assert "Höchstens" in prompt


@pytest.mark.asyncio
async def test_resolver_retries_a_too_wide_llm_word_with_a_smaller_budget():
    draft = _draft(first_h2="Donaudampfschifffahrt")
    composition = compose_topic_slides(draft)
    fake = FakeLLMClient(
        json_responses={
            TOPIC_KICKER_ROLE: [
                TopicKicker(kicker="WWWWWWWWWWWWWWWW"),
                TopicKicker(kicker="SCHIFFFAHRT"),
            ]
        }
    )

    resolved = await resolve_topic_kickers(draft, composition, fake)

    assert {slide.kicker for slide in _section_slides(resolved, 0)} == {
        "SCHIFFFAHRT"
    }
    calls = fake.calls_for(TOPIC_KICKER_ROLE)
    assert len(calls) == 2
    assert "zu breit" in calls[1].prompt


@pytest.mark.asyncio
async def test_resolver_uses_a_neutral_last_resort_without_thema():
    draft = _draft(first_h2="Donaudampfschifffahrt")
    composition = compose_topic_slides(draft)
    fake = FakeLLMClient(
        json_responses={
            TOPIC_KICKER_ROLE: [
                TopicKicker(kicker="WWWWWWWWWWWWWWWW"),
                TopicKicker(kicker="WWWWWWWWWWWWWW"),
            ]
        }
    )

    resolved = await resolve_topic_kickers(draft, composition, fake)

    assert {slide.kicker for slide in _section_slides(resolved, 0)} == {
        DEFAULT_TOPIC_KICKER
    }
    assert all(
        slide.kicker != "THEMA"
        for slide in resolved.slides
        if slide.slide_type != "cover"
    )


@pytest.mark.asyncio
async def test_resolver_replaces_a_legacy_thema_kicker_without_an_llm_call():
    draft = _draft()
    composition = compose_topic_slides(draft)
    legacy = apply_topic_kickers(
        composition,
        {0: "THEMA", 1: "THEMA"},
    )
    fake = FakeLLMClient()

    resolved = await resolve_topic_kickers(draft, legacy, fake)

    assert {slide.kicker for slide in _section_slides(resolved, 0)} == {
        "RAT"
    }
    assert {slide.kicker for slide in _section_slides(resolved, 1)} == {
        "RADWEG"
    }
    assert not fake.calls_for(TOPIC_KICKER_ROLE)
