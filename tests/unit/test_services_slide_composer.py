"""Behaviour tests for deterministic Summary slide composition."""

import re

import pytest

from app.core.post_models import SummaryDraft
from app.services.slide_composer import (
    SUMMARY_BODY_SIZES,
    SummaryCompositionError,
    compose_summary_slides,
    render_summary_markdown,
)
from app.services.text_layout import normalize_whitespace

WIDE_BODY = ("WWWWWWW " * 39 + "WWWWWWW").strip()


def _point(index: int, *, heading: str | None = None, body: str | None = None):
    default_body = (f"Thema {index}: " + "Der Rat hat dazu beraten. " * 10)[:120]
    return {
        "kicker": f"Thema{index}",
        "heading": heading or f"Der Rat entscheidet über Thema {index}",
        "body": body or default_body.ljust(120, "x"),
    }


def _draft(*, points=None, cover_title="Was der Rat in Rosdorf entschieden hat"):
    return SummaryDraft(
        cover_title=cover_title,
        points=points or [_point(1), _point(2)],
    )


def test_composer_builds_cover_and_cards_with_deterministic_fields():
    draft = _draft()

    composition = compose_summary_slides(draft)

    assert len(composition.slides) == 3
    cover, first, second = composition.slides

    assert cover.slide_index == 1
    assert cover.slide_type == "cover"
    assert cover.label == "SITZUNG KOMPAKT"
    assert cover.headline == draft.cover_title
    assert cover.body is None
    assert cover.pair_index is None

    assert first.slide_index == 2
    assert first.slide_type == "heading"
    assert first.label == draft.points[0].kicker
    assert first.headline == draft.points[0].heading
    assert first.body == draft.points[0].body
    assert first.pair_index is None
    assert second.slide_index == 3
    assert second.label == draft.points[1].kicker

    assert composition.body_size in SUMMARY_BODY_SIZES
    assert composition.cover_title_size in (76, 72, 68, 64)
    assert composition.slide_plan["family"] == "summary"
    assert composition.slide_plan["body_size"] == composition.body_size
    assert len(composition.slide_plan["cards"]) == 2


def test_card_numbering_and_page_labels_are_one_based_with_cover():
    composition = compose_summary_slides(_draft())

    cards = composition.slide_plan["cards"]

    assert cards[0]["card_number"] == 1
    assert cards[0]["page_label"] == "02 / 03"
    assert cards[1]["card_number"] == 2
    assert cards[1]["page_label"] == "03 / 03"
    assert composition.slides[1].card_number == 1
    assert composition.slides[2].page_label == "03 / 03"


def test_overlong_point_splits_onto_two_consecutive_cards_without_rewriting():
    point = _point(
        1,
        heading=(
            "Der Rat hat den Haushalt für die Ortsteile im kommenden Jahr "
            "mit mehreren Änderungen beschlossen"
        ),
        body=WIDE_BODY,
    )
    draft = _draft(points=[point, _point(2)])

    composition = compose_summary_slides(draft)

    cards = [slide for slide in composition.slides if slide.slide_type == "heading"]
    assert len(cards) == 3
    split_cards = cards[:2]
    assert composition.body_size == 42
    assert split_cards[0].label == split_cards[1].label == point["kicker"]
    assert split_cards[0].headline == split_cards[1].headline == point["heading"]
    assert split_cards[0].card_number == 1
    assert split_cards[1].card_number == 2
    assert split_cards[0].slide_index == 2
    assert split_cards[1].slide_index == 3
    assert split_cards[0].page_label == "02 / 04"
    assert split_cards[1].page_label == "03 / 04"

    rebuilt = " ".join(card.body for card in split_cards)
    assert rebuilt == normalize_whitespace(point["body"])
    assert split_cards[0].part_index == 0
    assert split_cards[1].part_index == 1


def test_five_points_with_one_split_fit_exactly_six_cards():
    points = [
        _point(1, body=WIDE_BODY),
        _point(2),
        _point(3),
        _point(4),
        _point(5),
    ]

    composition = compose_summary_slides(_draft(points=points))

    cards = [slide for slide in composition.slides if slide.slide_type == "heading"]
    assert len(cards) == 6
    assert composition.body_size in SUMMARY_BODY_SIZES
    assert [card.card_number for card in cards] == [1, 2, 3, 4, 5, 6]
    assert len([card for card in cards if card.point_index == 0]) == 2
    assert len(composition.slides) == 7


def test_more_than_six_cards_is_a_render_content_error():
    points = [
        _point(
            1,
            heading="Der Rat hat über das Thema und den Haushalt beraten",
            body=WIDE_BODY,
        ),
        *[_point(index) for index in range(2, 7)],
    ]

    with pytest.raises(SummaryCompositionError, match="six|6"):
        compose_summary_slides(_draft(points=points))


def test_unfittable_heading_raises_instead_of_truncating():
    draft = _draft(
        points=[
            _point(
                1,
                heading=(
                    "Donaudampfschifffahrtsgesellschaft "
                    "Donaudampfschifffahrtsgesellschaft "
                    "Donaudampfschifffahrtsgesellschaft "
                    "Donaudampfschifffahrtsgesellschaft "
                    "Donaudampfschifffahrtsgesellschaft"
                ),
            ),
            _point(2),
        ]
    )

    with pytest.raises(SummaryCompositionError):
        compose_summary_slides(draft)


def test_heading_and_cover_text_are_never_changed():
    draft = _draft(cover_title="Was der Rat in Rosdorf wirklich entschieden hat")

    composition = compose_summary_slides(draft)

    assert composition.slides[0].headline == draft.cover_title
    assert " ".join(
        composition.slide_plan["cover"]["title_lines"]
    ) == normalize_whitespace(draft.cover_title)
    for slide, point in zip(composition.slides[1:], draft.points):
        assert slide.headline == point.heading
        assert " ".join(slide.heading_lines) == normalize_whitespace(point.heading)


def test_alt_texts_are_deterministic_and_derived_from_the_composed_slides():
    draft = _draft()

    first = compose_summary_slides(draft)
    second = compose_summary_slides(draft)

    assert first.alt_texts == second.alt_texts
    assert len(first.alt_texts) == len(first.slides)
    assert draft.cover_title in first.alt_texts[0]
    assert draft.points[0].heading in first.alt_texts[1]
    assert [slide.alt_text for slide in first.slides] == list(first.alt_texts)


def test_markdown_contains_the_exact_draft_text():
    draft = _draft()

    markdown = render_summary_markdown(draft)

    assert markdown.startswith(f"# {draft.cover_title}")
    for point in draft.points:
        assert point.heading in markdown
        assert point.body in markdown
    assert re.search(r"^## ", markdown, re.MULTILINE)


def test_composition_is_deterministic():
    draft = _draft(points=[_point(1, body=WIDE_BODY), _point(2), _point(3)])

    first = compose_summary_slides(draft)
    second = compose_summary_slides(draft)

    assert first.slide_plan == second.slide_plan
    assert [slide.body for slide in first.slides] == [
        slide.body for slide in second.slides
    ]
    assert first.body_size == second.body_size
