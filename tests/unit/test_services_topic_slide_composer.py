"""Behaviour tests for deterministic topic slide composition."""

import re

import pytest

from app.core.post_models import TopicDraft
from app.services.slide_composer import (
    TopicCompositionError,
    compose_topic_slides,
    derive_chapter_short,
    derive_topic_kicker,
    render_topic_markdown,
)
from app.services.text_layout import normalize_whitespace

TITLE = "Was der Rat in Rosdorf entschieden hat"
H2_ONE = "Der Rat hat den Haushalt beschlossen"
H2_TWO = "Der Radweg wird im Sommer gebaut"


def _paragraph(seed: str, length: int) -> str:
    """Build a natural paragraph of roughly ``length`` characters."""
    text = ""
    while len(text) < length:
        text = f"{text} {seed}".strip()
    if len(text) > length:
        text = text[:length].rsplit(" ", 1)[0]
    return text.rstrip(" ,;") + "."


def _draft(
    *,
    sections: list[dict] | None = None,
    title: str = TITLE,
) -> TopicDraft:
    return TopicDraft(
        title=title,
        sections=sections
        or [
            {
                "h2": H2_ONE,
                "paragraphs": [
                    _paragraph(
                        "Der Rat hat den Haushalt einstimmig beschlossen und "
                        "die Mittel für alle Ortsteile freigegeben.",
                        720,
                    )
                ],
            },
            {
                "h2": H2_TWO,
                "paragraphs": [
                    _paragraph(
                        "Der Radweg an der Hauptstraße wird im Sommer gebaut "
                        "und verbindet die Ortsteile besser.",
                        720,
                    )
                ],
            },
        ],
    )


def _content_slides(composition):
    return [
        slide for slide in composition.slides if slide.slide_type != "cover"
    ]


def test_cover_and_every_h2_start_a_new_slide():
    draft = _draft()

    composition = compose_topic_slides(draft)

    cover = composition.slides[0]
    assert cover.slide_index == 1
    assert cover.slide_type == "cover"
    assert cover.label == "THEMA IM FOKUS"
    assert cover.headline == draft.title
    assert cover.body is None
    assert cover.pair_index is None
    assert draft.title in cover.alt_text

    content = _content_slides(composition)
    assert 4 <= len(content) <= 7
    assert [slide.slide_index for slide in composition.slides] == list(
        range(1, len(composition.slides) + 1)
    )

    heading_slides = [
        slide for slide in content if slide.slide_type == "heading"
    ]
    assert [slide.headline for slide in heading_slides] == [
        section.h2 for section in draft.sections
    ]
    for heading in heading_slides:
        assert heading.label == derive_topic_kicker(heading.headline)
        assert heading.label == heading.label.upper()
        assert " " not in heading.label

    first_section_slides = [
        slide for slide in content if slide.section_index == 0
    ]
    second_section_slides = [
        slide for slide in content if slide.section_index == 1
    ]
    assert first_section_slides[0].slide_type == "heading"
    assert second_section_slides[0].slide_type == "heading"
    assert first_section_slides[-1].slide_index < second_section_slides[0].slide_index


def test_overlong_section_continues_with_chapter_short_and_same_pair_index():
    first_body = _paragraph(
        "Der Rat hat den Haushalt einstimmig beschlossen und die Mittel "
        "für alle Ortsteile freigegeben.",
        1800,
    )
    draft = _draft(
        sections=[
            {"h2": H2_ONE, "paragraphs": [first_body]},
            {
                "h2": H2_TWO,
                "paragraphs": [
                    _paragraph(
                        "Der Radweg an der Hauptstraße wird im Sommer gebaut "
                        "und verbindet die Ortsteile besser.",
                        300,
                    )
                ],
            },
        ]
    )

    composition = compose_topic_slides(draft)

    content = _content_slides(composition)
    continuations = [
        slide for slide in content if slide.slide_type == "continuation"
    ]
    assert continuations
    for slide in continuations:
        assert slide.headline is None
        assert slide.label == derive_chapter_short(H2_ONE)
        assert len(slide.label) <= 28
        assert "…" not in slide.body

    first_section = [slide for slide in content if slide.section_index == 0]
    assert first_section[0].slide_type == "heading"
    assert all(slide.slide_type == "continuation" for slide in first_section[1:])
    for position, slide in enumerate(first_section, start=1):
        assert slide.pair_index == (position + 1) // 2


def test_all_content_slides_share_one_body_size_between_four_and_seven_slides():
    composition = compose_topic_slides(_draft())

    content = _content_slides(composition)
    assert composition.body_size in (42, 39, 36)
    assert 4 <= len(content) <= 7
    assert {slide.body_size for slide in content} == {composition.body_size}


def test_text_reconstruction_is_exact_and_never_reworded_or_truncated():
    first_body = _paragraph(
        "Der Rat hat den Haushalt einstimmig beschlossen und die Mittel "
        "für alle Ortsteile freigegeben.",
        2100,
    )
    second_body = _paragraph(
        "Der Radweg an der Hauptstraße wird im Sommer gebaut und verbindet "
        "die Ortsteile besser.",
        500,
    )
    draft = _draft(
        sections=[
            {"h2": H2_ONE, "paragraphs": [first_body]},
            {"h2": H2_TWO, "paragraphs": [second_body]},
        ]
    )

    composition = compose_topic_slides(draft)

    expected = normalize_whitespace(first_body + " " + second_body)
    rebuilt = normalize_whitespace(
        " ".join(
            slide.body
            for slide in composition.slides
            if slide.slide_type != "cover"
        )
    )
    assert rebuilt == expected
    assert all("Fortsetzung" not in (slide.body or "") for slide in composition.slides)


def test_paragraph_gaps_only_appear_between_complete_paragraphs_on_a_slide():
    draft = _draft(
        sections=[
            {
                "h2": H2_ONE,
                "paragraphs": [
                    _paragraph("Erster Absatz über den Haushalt.", 280),
                    _paragraph("Zweiter Absatz über den Haushalt.", 280),
                ],
            },
            {"h2": H2_TWO, "paragraphs": [_paragraph("Der Radweg kommt.", 600)]},
        ]
    )

    composition = compose_topic_slides(draft)

    for slide in composition.slides:
        if not slide.body:
            continue
        assert not slide.body.startswith("\n")
        assert not slide.body.endswith("\n")
        assert "\n\n\n" not in slide.body


def test_pair_index_follows_the_content_position_and_rounds_up():
    composition = compose_topic_slides(_draft())

    content = _content_slides(composition)
    assert [slide.content_position for slide in content] == list(
        range(1, len(content) + 1)
    )
    assert [slide.pair_index for slide in content] == [
        (position + 1) // 2 for position in range(1, len(content) + 1)
    ]


def test_kicker_and_chapter_short_derivation_is_deterministic():
    assert derive_topic_kicker("Der Rat hat den Haushalt beschlossen") == "RAT"
    assert derive_topic_kicker("Die Gemeinde baut den Radweg") == "GEMEINDE"
    assert derive_topic_kicker("Der die das und was auch") == "THEMA"

    chapter = derive_chapter_short("Der Rat hat den Haushalt beschlossen")
    assert chapter == "Der Rat hat den Haushalt"
    assert len(chapter) <= 28
    assert "…" not in chapter
    assert derive_chapter_short("Donaudampfschifffahrtsgesellschaft") == "THEMA"


def test_alt_texts_are_deterministic_and_match_the_slides():
    draft = _draft()

    first = compose_topic_slides(draft)
    second = compose_topic_slides(draft)

    assert first.alt_texts == second.alt_texts
    assert len(first.alt_texts) == len(first.slides)
    assert [slide.alt_text for slide in first.slides] == list(first.alt_texts)
    assert first.alt_texts[0].startswith("Titelbild des Themenbeitrags:")
    assert first.slides[0].headline in first.alt_texts[0]
    for slide in first.slides[1:]:
        if slide.slide_type == "heading":
            assert slide.headline in slide.alt_text
        else:
            assert slide.label in slide.alt_text


def test_markdown_contains_the_exact_article_text():
    draft = _draft(
        sections=[
            {
                "h2": H2_ONE,
                "paragraphs": ["Der Haushalt ist beschlossen."],
            },
            {
                "h2": H2_TWO,
                "paragraphs": ["Der Radweg kommt im Sommer."],
            },
        ]
    )

    markdown = render_topic_markdown(draft)

    assert markdown.startswith(f"# {draft.title}")
    for section in draft.sections:
        assert f"## {section.h2}" in markdown
        for paragraph in section.paragraphs:
            assert paragraph in markdown
    assert re.search(r"^## ", markdown, re.MULTILINE)


def test_body_size_falls_back_when_a_word_is_too_wide_at_the_larger_size():
    long_word = "A" * 22
    draft = _draft(
        sections=[
            {
                "h2": H2_ONE,
                "paragraphs": [
                    _paragraph(
                        f"Der Rat hat den Haushalt beschlossen. {long_word} "
                        "ist im Beschluss genannt.",
                        600,
                    )
                ],
            },
            {
                "h2": H2_TWO,
                "paragraphs": [
                    _paragraph(
                        "Der Radweg an der Hauptstraße wird im Sommer gebaut "
                        "und verbindet die Ortsteile besser.",
                        600,
                    )
                ],
            },
        ]
    )

    composition = compose_topic_slides(draft)

    assert composition.body_size == 39
    assert 4 <= len(_content_slides(composition)) <= 7
    assert any(long_word in (slide.body or "") for slide in composition.slides)


def test_composition_rejects_fewer_than_four_content_slides():
    draft = _draft(
        sections=[
            {"h2": H2_ONE, "paragraphs": ["Der Haushalt ist beschlossen."]},
            {"h2": H2_TWO, "paragraphs": ["Der Radweg kommt im Sommer."]},
        ]
    )

    with pytest.raises(TopicCompositionError, match="4"):
        compose_topic_slides(draft)


def test_composition_rejects_more_than_seven_content_slides():
    sections = [
        {
            "h2": f"Der Rat entscheidet über Thema Nummer {index}",
            "paragraphs": [
                _paragraph(
                    "Der Rat hat zu diesem Thema ausführlich beraten und "
                    "eine Entscheidung getroffen.",
                    460,
                )
            ],
        }
        for index in range(1, 7)
    ]
    draft = _draft(title="T" * 20, sections=sections)

    with pytest.raises(TopicCompositionError, match="7|Content-Slides"):
        compose_topic_slides(draft)


def test_slide_plan_describes_the_deterministic_composition():
    draft = _draft()

    composition = compose_topic_slides(draft)
    plan = composition.slide_plan

    assert plan["family"] == "topic"
    assert plan["body_size"] == composition.body_size
    assert plan["content_slides"] == len(_content_slides(composition))
    assert plan["total_slides"] == len(composition.slides)
    assert plan["cover"]["label"] == "THEMA IM FOKUS"
    assert " ".join(plan["cover"]["title_lines"]) == normalize_whitespace(
        draft.title
    )
    assert len(plan["slides"]) == len(_content_slides(composition))
    assert plan["slides"][0]["slide_type"] == "heading"
    assert plan["slides"][0]["headline"] == H2_ONE
    assert plan["slides"][0]["pair_index"] == 1


def test_composition_is_deterministic():
    draft = _draft()

    first = compose_topic_slides(draft)
    second = compose_topic_slides(draft)

    assert first.slide_plan == second.slide_plan
    assert [slide.body for slide in first.slides] == [
        slide.body for slide in second.slides
    ]
    assert first.markdown == second.markdown
