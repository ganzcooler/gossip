"""Behaviour tests for the shared Pillow text-layout primitives."""

import pytest

from app.services.text_layout import (
    TextOverflowError,
    fit_lines,
    inter_font,
    missing_glyphs,
    normalize_whitespace,
    oswald_font,
    reconstruct_lines,
    split_text_balanced,
    split_text_to_fit,
    wrap_text,
)

GERMAN_GLYPHS = "ÄÖÜäöüßẞ§€–—„“”‘’"
DISPLAY_SIZES = (21, 22, 24, 36, 39, 40, 42, 64, 68, 72, 76, 96, 118)


@pytest.mark.parametrize("size", DISPLAY_SIZES)
def test_oswald_and_inter_contain_every_german_glyph_at_display_sizes(size):
    oswald = oswald_font(size, weight=700)
    inter = inter_font(size, weight=400)

    assert missing_glyphs(oswald, GERMAN_GLYPHS) == []
    assert missing_glyphs(inter, GERMAN_GLYPHS) == []


def test_inter_variable_font_applies_both_optical_size_and_weight_axes():
    light = inter_font(42, weight=400)
    heavy = inter_font(42, weight=700)

    assert heavy.getlength("Haushalt") > light.getlength("Haushalt")
    assert heavy.getlength("Haushalt") != inter_font(42, weight=400).getlength("Haushalt")


def test_wrap_text_uses_real_metrics_and_reconstructs_the_input():
    font = inter_font(42, weight=400)
    text = normalize_whitespace(
        "Der Rat beschließt den Haushalt einstimmig und die Verwaltung "
        "zahlt die Mittel im Frühjahr aus."
    )

    lines = wrap_text(text, font, max_width=400)

    assert len(lines) > 1
    assert all(font.getlength(line.text) <= 400 for line in lines)
    assert reconstruct_lines(lines) == text


def test_wrap_text_never_splits_a_heading_word_without_permission():
    font = oswald_font(76, weight=700)
    long_word = "Donaudampfschifffahrtsgesellschaft"

    with pytest.raises(TextOverflowError):
        wrap_text(long_word, font, max_width=120)


def test_wrap_text_can_split_an_overlong_body_word_as_a_last_resort():
    font = inter_font(36, weight=400)
    long_word = "Donaudampfschifffahrtsgesellschaft"

    lines = wrap_text(long_word, font, max_width=120, allow_char_split=True)

    assert len(lines) > 1
    assert reconstruct_lines(lines) == long_word
    assert all(font.getlength(line.text) <= 120 for line in lines)


def test_fit_lines_returns_the_largest_size_that_respects_lines_and_height():
    text = "Was der Rat in Rosdorf entschieden hat"

    fit = fit_lines(
        text,
        family="oswald",
        sizes=(76, 72, 68, 64),
        width=950,
        max_lines=3,
        line_height=1.04,
        weight=700,
        max_height=400,
    )

    assert fit is not None
    assert fit.size in (76, 72, 68, 64)
    assert 1 <= len(fit.lines) <= 3
    assert fit.height <= 400
    assert reconstruct_lines(fit.lines) == text


def test_fit_lines_rejects_an_overlong_word_instead_of_splitting_it():
    fit = fit_lines(
        "Donaudampfschifffahrtsgesellschaft",
        family="oswald",
        sizes=(76, 72),
        width=200,
        max_lines=2,
        line_height=1.0,
        weight=700,
    )

    assert fit is None


def test_fit_lines_rejects_a_too_short_last_line():
    # "ab" is narrower than the 4 visible-character minimum; no size fits
    # because the first word consumes nearly the whole line.
    fit = fit_lines(
        "Haushalt ab",
        family="oswald",
        sizes=(76,),
        width=330,
        max_lines=1,
        line_height=1.0,
        weight=700,
    )

    assert fit is None


def test_split_text_to_fit_prefers_sentence_boundaries_and_reconstructs_exactly():
    font = inter_font(36, weight=400)
    text = normalize_whitespace(
        "Der Rat beschließt den Haushalt einstimmig. "
        "Die Verwaltung zahlt die Mittel im Frühjahr aus. "
        "Der Radweg an der Hauptstraße wird im Sommer gebaut. "
        "Die Anwohner werden vorher informiert. "
        "Die Kosten teilen sich Land und Gemeinde."
    )
    width = 600
    line_height = 36 * 1.4

    parts = split_text_to_fit(
        text,
        font,
        width=width,
        max_heights=(220, 220),
        line_height=line_height,
        allow_char_split=False,
    )

    assert parts is not None
    assert len(parts) == 2
    assert " ".join(parts) == text
    assert parts[0].endswith(".")


def test_split_text_to_fit_balances_two_parts_at_word_boundaries():
    font = inter_font(36, weight=400)
    text = normalize_whitespace(" ".join(["Haushalt"] * 12))
    width = 300
    line_height = 36 * 1.4

    parts = split_text_to_fit(
        text,
        font,
        width=width,
        max_heights=(180, 180),
        line_height=line_height,
        allow_char_split=False,
    )

    assert parts is not None
    assert len(parts) == 2
    assert " ".join(parts) == text
    assert abs(len(parts[0]) - len(parts[1])) <= len("Haushalt") + 1


def test_split_text_balanced_prefers_a_sentence_boundary_and_reconstructs():
    font = inter_font(36, weight=400)
    sentences = [
        "Der Rat beschließt den Haushalt einstimmig.",
        "Die Verwaltung zahlt die Mittel im Frühjahr aus.",
        "Der Radweg an der Hauptstraße wird im Sommer gebaut.",
        "Die Anwohner werden vorher informiert.",
        "Die Kosten teilen sich Land und Gemeinde.",
    ]
    text = normalize_whitespace(" ".join(sentences))

    parts = split_text_balanced(
        text,
        font,
        width=300,
        first_capacity=400,
        continuation_capacity=500,
        line_height=36 * 1.4,
    )

    assert len(parts) == 2
    assert " ".join(parts) == text
    assert parts[0] == " ".join(sentences[:2])
    assert parts[1] == " ".join(sentences[2:])


def test_split_text_balanced_does_not_split_after_common_abbreviations():
    font = inter_font(36, weight=400)
    sentences = [
        "Der Rat hat z. B. die Mittel für alle Ortsteile freigegeben.",
        "Die Verwaltung zahlt d. h. die Beiträge im Frühjahr aus.",
        "Der Radweg wird u. a. im Sommer gebaut.",
        "Die Anwohner werden vorher informiert.",
    ]
    text = normalize_whitespace(" ".join(sentences))

    parts = split_text_balanced(
        text,
        font,
        width=300,
        first_capacity=500,
        continuation_capacity=500,
        line_height=36 * 1.4,
    )

    assert len(parts) == 2
    assert " ".join(parts) == text
    # The abbreviation boundaries "d." / "h." / "u." / "a." are closer to the
    # middle than the real sentence boundary, but must not count as sentence
    # ends.
    assert parts[0] == " ".join(sentences[:2])


@pytest.mark.parametrize(
    "middle",
    [
        "Das ist ein ausführlicher Test.",
        "Die Reise führt quer durch Africa.",
        "Das ist ein ausführlicher Test.“",
    ],
)
def test_split_text_balanced_keeps_sentence_ends_that_look_like_abbreviations(
    middle,
):
    font = inter_font(36, weight=400)
    first = "Der Rat beschließt den Haushalt."
    last = "Die Zahlen werden geprüft. Der Ausschuss tagt am Montag."
    text = normalize_whitespace(" ".join([first, middle, last]))
    line_height = 36 * 1.4

    parts = split_text_balanced(
        text,
        font,
        width=300,
        first_capacity=4 * line_height,
        continuation_capacity=4 * line_height,
        line_height=line_height,
    )

    assert len(parts) == 2
    assert " ".join(parts) == text
    # "Test." ends in "st." and "Africa." ends in "ca.", but neither is an
    # abbreviation; both remain valid sentence boundaries.
    assert parts[0] == f"{first} {middle}"


def test_split_text_balanced_uses_a_balanced_word_fallback_for_one_sentence():
    font = inter_font(36, weight=400)
    text = normalize_whitespace(" ".join(["Haushalt"] * 12))
    line_height = 36 * 1.4

    parts = split_text_balanced(
        text,
        font,
        width=300,
        first_capacity=4 * line_height,
        continuation_capacity=4 * line_height,
        line_height=line_height,
    )

    assert len(parts) >= 2
    assert " ".join(parts) == text
    assert all(part for part in parts)
    assert not any(part.endswith("-") for part in parts)
    assert parts[0].count(" ") != 0


def test_split_text_to_fit_returns_none_when_nothing_fits():
    font = inter_font(36, weight=400)

    parts = split_text_to_fit(
        "Ein sehr langer Text",
        font,
        width=100,
        max_heights=(10,),
        line_height=50,
        allow_char_split=False,
    )

    assert parts is None
