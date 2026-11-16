"""Tests for deterministic Quellenanker retrieval."""

import pytest

from app.services.protocol_excerpts import (
    MissingSourceAnchor,
    retrieve_source_excerpt,
    retrieve_source_excerpts,
)

PROTOCOL_TEXT = (
    "TOP 1 Begrüßung\n"
    "Der Vorsitzende eröffnet die Sitzung.\n"
    "\n"
    "TOP 5 Haushalt\n"
    "Der Rat beschließt den Haushalt einstimmig.\n"
    "Die Verwaltung soll die Mittel im Frühjahr auszahlen.\n"
    "\n"
    "TOP 6 Verkehr\n"
    "Der Radweg an der Hauptstraße wird im Sommer gebaut.\n"
)


def test_exact_anchor_returns_containing_paragraph():
    excerpt = retrieve_source_excerpt(
        PROTOCOL_TEXT, "Der Rat beschließt den Haushalt einstimmig."
    )

    assert excerpt.anchor == "Der Rat beschließt den Haushalt einstimmig."
    assert "TOP 5 Haushalt" in excerpt.excerpt
    assert "Die Verwaltung soll" in excerpt.excerpt
    assert "TOP 6 Verkehr" not in excerpt.excerpt


def test_anchor_matching_normalises_whitespace_and_case():
    excerpt = retrieve_source_excerpt(
        PROTOCOL_TEXT, "der rat beschließt   den haushalt\neinstimmig"
    )

    assert "Haushalt einstimmig" in excerpt.excerpt


def test_missing_anchor_raises_with_the_anchor():
    with pytest.raises(MissingSourceAnchor, match="nicht im Protokoll"):
        retrieve_source_excerpt(PROTOCOL_TEXT, "Dieser Satz fehlt")


@pytest.mark.parametrize("anchor", ["", "   ", "\n\t"])
def test_empty_anchor_is_missing(anchor):
    with pytest.raises(MissingSourceAnchor):
        retrieve_source_excerpt(PROTOCOL_TEXT, anchor)


def test_multiple_anchors_keep_order_and_deduplicate_excerpts():
    anchors = [
        "TOP 6 Verkehr",
        "TOP 5 Haushalt",
        "TOP 6 Verkehr",
        "Der Radweg an der Hauptstraße",
    ]

    excerpts = retrieve_source_excerpts(PROTOCOL_TEXT, anchors)

    assert [excerpt.anchor for excerpt in excerpts] == [
        "TOP 6 Verkehr",
        "TOP 5 Haushalt",
    ]
    assert len({excerpt.excerpt for excerpt in excerpts}) == 2


def test_long_paragraph_is_bounded_around_the_anchor():
    prefix = "Vorspann " * 500
    suffix = "Nachspann " * 500
    anchor = "Der entscheidende Beschluss zum Haushalt."
    text = f"{prefix}{anchor}{suffix}"

    excerpt = retrieve_source_excerpt(text, anchor, max_chars=1200)

    assert anchor in excerpt.excerpt
    assert len(excerpt.excerpt) <= 1200


def test_retrieval_is_deterministic():
    first = retrieve_source_excerpts(PROTOCOL_TEXT, ["TOP 5 Haushalt", "TOP 6 Verkehr"])
    second = retrieve_source_excerpts(PROTOCOL_TEXT, ["TOP 5 Haushalt", "TOP 6 Verkehr"])

    assert first == second
