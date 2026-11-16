"""Tests for the finite Organ seed list."""

import pytest

from app.services.organs import (
    ORGAN_BY_PROTOCOL_TITLE,
    UnknownOrganError,
    resolve_organ,
)


def test_seed_contains_all_twelve_known_protocol_titles():
    assert len(ORGAN_BY_PROTOCOL_TITLE) == 12
    assert ORGAN_BY_PROTOCOL_TITLE["Gemeinderat"] == "Gemeinderat Rosdorf"
    assert (
        ORGAN_BY_PROTOCOL_TITLE["Ausschuss Wirtschaft, Finanzen, Personal und Digitalisierung"]
        == "Ausschuss Wirtschaft, Finanzen, Personal und Digitalisierung"
    )


@pytest.mark.parametrize(
    ("protocol_title", "expected"),
    [
        ("Ortsrat Atzenhausen", "Ortsrat Atzenhausen"),
        ("Ortsrat Dahlenrode", "Ortsrat Dahlenrode"),
        ("Ortsrat Dramfeld", "Ortsrat Dramfeld"),
        ("Ortsrat Mengershausen", "Ortsrat Mengershausen"),
        ("Ortsrat Obernjesa", "Ortsrat Obernjesa"),
        ("Ortsrat Sieboldshausen", "Ortsrat Sieboldshausen"),
        ("Ortsrat Volkerode", "Ortsrat Volkerode"),
        ("Feuerwehrausschuss", "Feuerwehrausschuss"),
        ("Ausschuss Bau, Umwelt und Verkehr", "Ausschuss Bau, Umwelt und Verkehr"),
        ("Ausschuss Sport, Kultur und Soziales", "Ausschuss Sport, Kultur und Soziales"),
    ],
)
def test_resolver_returns_official_names(protocol_title, expected):
    assert resolve_organ(protocol_title) == expected


def test_resolver_strips_surrounding_whitespace_only():
    assert resolve_organ("  Gemeinderat  ") == "Gemeinderat Rosdorf"


@pytest.mark.parametrize(
    "protocol_title",
    ["Jugendausschuss", "gemeinderat", "Gemeinderat Rosdorf", "Test Protocol", ""],
)
def test_unknown_or_non_exact_titles_fail(protocol_title):
    with pytest.raises(UnknownOrganError, match="Unknown organ"):
        resolve_organ(protocol_title)
