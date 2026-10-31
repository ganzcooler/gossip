"""Tests for semantic slide planning, validation, and deterministic fallback."""

import pytest

from app.core.post_models import (
    ArticleDraft,
    ArticleSection,
    CoverPlan,
    SlideContent,
    SummarySlidePlan,
    TopicSlidePair,
    TopicSlidePlan,
)
from app.services.errors import SlidePlanError
from app.services.slide_planner import (
    _condense_text,
    _label_from_heading,
    fallback_summary_slides,
    fallback_topic_slides,
    validate_summary_plan,
    validate_topic_plan,
)


def _article(section_count: int = 5) -> ArticleDraft:
    sections = [
        ArticleSection(
            heading=f"Abschnitt {index}",
            paragraphs=[
                f"Der Rat hat im Abschnitt {index} eine Entscheidung getroffen. "
                "Die Verwaltung soll die nächsten Schritte prüfen."
            ],
        )
        for index in range(1, section_count + 1)
    ]
    return ArticleDraft(
        title="Haushalt, Windpark und Radwege: Das war die Sitzung",
        kicker="SITZUNG KOMPAKT",
        lead="Der Rat hat mehrere wichtige Entscheidungen getroffen.",
        sections=sections,
        key_takeaways=["Haushalt beschlossen", "Windpark vertagt"],
    )


def _summary_plan(slide_count: int) -> SummarySlidePlan:
    return SummarySlidePlan(
        cover=CoverPlan(
            kicker="SITZUNG KOMPAKT",
            headline="Das war die Sitzung",
            image_brief="A calm town hall at dusk",
        ),
        slides=[
            SlideContent(label="HAUSHALT", headline="Beschluss", body="Kurzer Text.")
            for _ in range(slide_count)
        ],
    )


def _topic_plan(pair_count: int) -> TopicSlidePlan:
    return TopicSlidePlan(
        cover=CoverPlan(
            kicker="THEMA IM FOKUS",
            headline="Windpark: Warum die Entscheidung vertagt wurde",
            image_brief="A calm landscape with a wind turbine",
        ),
        pairs=[
            TopicSlidePair(
                slides=[
                    SlideContent(label="BESCHLUSS", headline="Vertagt", body="Kurzer Text."),
                    SlideContent(label="AUSBLICK", headline="Wie es weitergeht", body="Kurzer Text."),
                ],
                artwork_brief="One calm landscape, no text",
            )
            for _ in range(pair_count)
        ],
    )


def test_validate_summary_plan_accepts_three_to_eight_slides():
    validate_summary_plan(_summary_plan(3))
    validate_summary_plan(_summary_plan(8))


def test_validate_summary_plan_rejects_too_few_slides():
    with pytest.raises(SlidePlanError):
        validate_summary_plan(_summary_plan(2))


def test_validate_summary_plan_rejects_too_many_slides():
    with pytest.raises(SlidePlanError):
        validate_summary_plan(_summary_plan(9))


def test_validate_topic_plan_accepts_one_to_four_pairs():
    validate_topic_plan(_topic_plan(1))
    validate_topic_plan(_topic_plan(4))


def test_validate_topic_plan_rejects_too_many_pairs():
    with pytest.raises(SlidePlanError):
        validate_topic_plan(_topic_plan(5))


def test_fallback_summary_slides_produces_valid_plan():
    plan = fallback_summary_slides(_article(section_count=6))

    validate_summary_plan(plan)
    assert plan.cover.kicker == "SITZUNG KOMPAKT"
    assert 3 <= len(plan.slides) <= 8
    assert all(len(slide.body) <= 220 for slide in plan.slides)


def test_fallback_topic_slides_produces_even_pairs():
    plan = fallback_topic_slides(_article(section_count=5))

    validate_topic_plan(plan)
    assert plan.cover.kicker == "THEMA IM FOKUS"
    assert 1 <= len(plan.pairs) <= 4
    assert all(len(pair.slides) == 2 for pair in plan.pairs)
    assert all(len(slide.body) <= 220 for pair in plan.pairs for slide in pair.slides)
    assert all(pair.artwork_brief for pair in plan.pairs)


def test_label_from_heading_maps_intro_words():
    assert _label_from_heading("Was der Ortsrat beschlossen hat") == "BESCHLUSS"
    assert _label_from_heading("Das steckt hinter dem Gesamtprojekt") == "HINTERGRUND"
    assert _label_from_heading("Optik, Größe und Kosten als Streitpunkte") == "KOSTEN"


def test_condense_text_keeps_date_and_full_sentence():
    text = (
        "In der Sitzung am 24. September 2026 hat der Ortsrat eine Entscheidung "
        "getroffen. Ein weiterer Satz."
    )

    result = _condense_text([text], 120)

    assert "24." in result
    assert "September" in result
    assert result != "In der Sitzung am 24."
