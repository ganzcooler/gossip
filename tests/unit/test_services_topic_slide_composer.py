"""Behaviour tests for deterministic topic slide composition."""

import re

import pytest

from app.core.post_models import TopicDraft
from app.services.slide_composer import (
    TOPIC_BODY_BOTTOM,
    TOPIC_BODY_LINE_HEIGHT,
    TOPIC_CONTINUATION_TOP,
    TOPIC_H2_BODY_GAP,
    TOPIC_H2_TOP,
    TOPIC_TEXT_WIDTH,
    TopicCompositionError,
    compose_topic_slides,
    derive_chapter_short,
    derive_topic_kicker,
    render_topic_markdown,
)
from app.services.text_layout import inter_font, normalize_whitespace, wrap_text

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


_SENTENCE_SEED = (
    "Der Rat hat den Haushalt einstimmig beschlossen und die Mittel "
    "für alle Ortsteile freigegeben"
)


def _sentence(length: int) -> str:
    """Build one sentence of roughly ``length`` characters without a period."""
    text = ""
    while len(text) < length:
        text = f"{text} {_SENTENCE_SEED}".strip()
    if len(text) > length:
        text = text[:length].rsplit(" ", 1)[0]
    return text.rstrip(" ,;") + "."


def _sentences(count: int, total_length: int = 500) -> str:
    """Build exactly ``count`` sentences of roughly equal length."""
    per_sentence = total_length // count
    return " ".join(_sentence(per_sentence) for _ in range(count))


def _sentence_units(text: str) -> list[str]:
    return [
        unit
        for unit in re.split(r"(?<=[.!?…])\s+", text.strip())
        if unit
    ]


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


def _section_slides(composition, section_index):
    return [
        slide
        for slide in _content_slides(composition)
        if slide.section_index == section_index
    ]


def _rendered_heading_capacity(slide) -> float:
    body_top = TOPIC_H2_TOP + slide.heading_zone + TOPIC_H2_BODY_GAP
    return TOPIC_BODY_BOTTOM - body_top


def _rendered_body_height(slide) -> float:
    return len(slide.body_lines) * slide.body_size * TOPIC_BODY_LINE_HEIGHT


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


def test_paragraph_that_fits_a_full_page_moves_whole_to_the_next_slide():
    intro = _paragraph(
        "Der Rat hat den Haushalt einstimmig beschlossen.", 80
    )
    full_page_paragraph = _paragraph(
        "Der Rat hat den Haushalt einstimmig beschlossen und die Mittel "
        "für alle Ortsteile freigegeben.",
        420,
    )
    draft = _draft(
        sections=[
            {
                "h2": H2_ONE,
                "paragraphs": [intro, full_page_paragraph],
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
        ]
    )

    composition = compose_topic_slides(draft)

    assert 4 <= len(_content_slides(composition)) <= 7
    section = _section_slides(composition, 0)
    assert len(section) == 2
    heading, continuation = section
    assert heading.slide_type == "heading"
    assert normalize_whitespace(heading.body) == normalize_whitespace(intro)
    assert continuation.slide_type == "continuation"
    assert normalize_whitespace(continuation.body) == normalize_whitespace(
        full_page_paragraph
    )
    assert len(heading.body_paragraphs) == 1
    assert len(continuation.body_paragraphs) == 1
    continuation_capacity = TOPIC_BODY_BOTTOM - TOPIC_CONTINUATION_TOP
    assert _rendered_body_height(continuation) <= continuation_capacity + 1e-9
    assert (
        _rendered_body_height(continuation)
        > _rendered_heading_capacity(heading) + 1e-9
    )


def test_first_paragraph_is_measured_against_the_heading_capacity():
    first_body = _paragraph(
        "Der Rat hat den Haushalt einstimmig beschlossen und die Mittel "
        "für alle Ortsteile freigegeben.",
        340,
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
                        720,
                    )
                ],
            },
        ]
    )

    composition = compose_topic_slides(draft)

    assert composition.body_size == 42
    section = _section_slides(composition, 0)
    assert len(section) == 2
    heading, continuation = section
    assert heading.slide_type == "heading"
    assert heading.body
    assert continuation.body
    assert _rendered_body_height(heading) <= (
        _rendered_heading_capacity(heading) + 1e-9
    )
    assert normalize_whitespace(first_body).startswith(
        normalize_whitespace(heading.body) + " "
    )
    assert normalize_whitespace(heading.body) != normalize_whitespace(
        first_body
    )
    assert normalize_whitespace(
        heading.body + " " + continuation.body
    ) == normalize_whitespace(first_body)
    assert len(heading.body_paragraphs) == 1
    assert len(continuation.body_paragraphs) == 1
    assert "\n\n" not in heading.body
    assert "\n\n" not in continuation.body


@pytest.mark.parametrize("sentence_count", [3, 4, 5])
def test_overlong_paragraph_splits_at_sentences_with_substantial_continuation(
    sentence_count,
):
    paragraph = _sentences(sentence_count)
    draft = _draft(
        sections=[
            {"h2": H2_ONE, "paragraphs": [paragraph]},
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
        ]
    )

    composition = compose_topic_slides(draft)

    assert composition.body_size == 42
    section = _section_slides(composition, 0)
    assert len(section) == 2
    heading, continuation = section
    assert heading.slide_type == "heading"
    assert continuation.slide_type == "continuation"
    assert heading.body.rstrip().endswith((".", "!", "?", "…"))
    assert len(_sentence_units(continuation.body)) >= 2
    assert len(continuation.body_lines) >= 2

    full_lines = len(
        wrap_text(
            paragraph,
            inter_font(composition.body_size, weight=400),
            TOPIC_TEXT_WIDTH,
            allow_char_split=False,
        )
    )
    full_height = full_lines * composition.body_size * TOPIC_BODY_LINE_HEIGHT
    assert _rendered_body_height(continuation) >= 0.25 * full_height - 1e-9
    assert normalize_whitespace(
        heading.body + " " + continuation.body
    ) == normalize_whitespace(paragraph)
    assert len(heading.body_paragraphs) == 1
    assert len(continuation.body_paragraphs) == 1
    assert "\n\n" not in heading.body
    assert "\n\n" not in continuation.body


def test_three_sentence_paragraph_keeps_two_sentences_on_the_continuation():
    sentences = [_sentence(112), _sentence(66), _sentence(239)]
    paragraph = " ".join(sentences)
    draft = _draft(
        sections=[
            {"h2": H2_ONE, "paragraphs": [paragraph]},
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
        ]
    )

    composition = compose_topic_slides(draft)

    assert composition.body_size == 42
    section = _section_slides(composition, 0)
    assert len(section) == 2
    heading, continuation = section
    # The short middle sentence makes the penultimate sentence boundary look
    # near the middle; it is still not allowed because the continuation would
    # contain only the final sentence.
    assert len(_sentence_units(continuation.body)) >= 2
    assert normalize_whitespace(
        heading.body + " " + continuation.body
    ) == normalize_whitespace(paragraph)


def test_single_sentence_paragraph_uses_a_balanced_word_fallback():
    paragraph = _sentence(500)
    draft = _draft(
        sections=[
            {"h2": H2_ONE, "paragraphs": [paragraph]},
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
        ]
    )

    composition = compose_topic_slides(draft)

    assert composition.body_size == 42
    section = _section_slides(composition, 0)
    assert len(section) == 2
    heading, continuation = section
    assert not heading.body.rstrip().endswith((".", "!", "?", "…"))
    assert len(continuation.body_lines) >= 2
    assert abs(len(heading.body_lines) - len(continuation.body_lines)) <= 1
    assert normalize_whitespace(
        heading.body + " " + continuation.body
    ) == normalize_whitespace(paragraph)
    assert len(heading.body_paragraphs) == 1
    assert len(continuation.body_paragraphs) == 1


def test_common_abbreviations_are_not_treated_as_sentence_ends():
    sentences = [
        "Der Rat hat z. B. die Mittel für alle Ortsteile freigegeben und "
        "die Verwaltung informiert die Anwohner über den Beschluss.",
        "Die Gemeinde baut d. h. den Radweg an der Hauptstraße und die "
        "Anwohner werden u. a. vorher über die Arbeiten informiert.",
        "Die Kosten teilen sich usw. zwischen Land und Gemeinde und die "
        "Arbeiten beginnen ca. im Sommer nach der Ausschreibung.",
        "Das ist Nr. 42 und Dr. Meyer prüft St. Marien und die Zahlen im "
        "Frühjahr gemeinsam mit der Verwaltung.",
    ]
    paragraph = " ".join(sentences)
    draft = _draft(
        sections=[
            {"h2": H2_ONE, "paragraphs": [paragraph]},
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
        ]
    )

    composition = compose_topic_slides(draft)

    assert composition.body_size == 42
    section = _section_slides(composition, 0)
    assert len(section) == 2
    heading, continuation = section
    assert normalize_whitespace(heading.body) == " ".join(sentences[:2])
    assert normalize_whitespace(continuation.body) == " ".join(sentences[2:])
    assert normalize_whitespace(
        heading.body + " " + continuation.body
    ) == normalize_whitespace(paragraph)


def test_body_size_choice_keeps_whole_paragraph_packing_within_four_to_seven():
    sections = [
        {
            "h2": f"Der Rat entscheidet über Thema Nummer {index}",
            "paragraphs": [
                _paragraph(
                    "Der Rat hat zu diesem Thema ausführlich beraten und "
                    "eine Entscheidung getroffen.",
                    330,
                )
            ],
        }
        for index in range(1, 7)
    ]
    draft = _draft(title="T" * 20, sections=sections)

    composition = compose_topic_slides(draft)

    content = _content_slides(composition)
    assert composition.body_size == 39
    assert 4 <= len(content) <= 7
    assert {slide.body_size for slide in content} == {composition.body_size}


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

    for section_index, section in enumerate(draft.sections):
        rebuilt_section = normalize_whitespace(
            " ".join(
                slide.body for slide in _section_slides(composition, section_index)
            )
        )
        assert rebuilt_section == normalize_whitespace(" ".join(section.paragraphs))

    for slide in _content_slides(composition):
        flattened = tuple(
            line for block in slide.body_paragraphs for line in block
        )
        assert flattened == slide.body_lines
        assert slide.body == "\n\n".join(
            " ".join(block) for block in slide.body_paragraphs
        )

    plan_entries = composition.slide_plan["slides"]
    assert [entry["body"] for entry in plan_entries] == [
        slide.body for slide in _content_slides(composition)
    ]
    assert [entry["body_lines"] for entry in plan_entries] == [
        list(slide.body_lines) for slide in _content_slides(composition)
    ]
    assert [entry["body_paragraphs"] for entry in plan_entries] == [
        [list(block) for block in slide.body_paragraphs]
        for slide in _content_slides(composition)
    ]


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
