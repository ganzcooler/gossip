"""Tests for the pure prompt builders."""

from datetime import date

from app.core.post_prompts import build_planner_prompt

PROTOCOL_TEXT = (
    "TOP 1 Begrüßung\n"
    "Der Vorsitzende eröffnet die Sitzung.\n"
    "\n"
    "TOP 5 Haushalt\n"
    "Der Rat beschließt den Haushalt einstimmig.\n"
)


def test_planner_prompt_contains_the_full_protocol_text_and_rules():
    prompt = build_planner_prompt(
        protocol_title="Gemeinderat",
        session_date=date(2024, 1, 15),
        protocol_text=PROTOCOL_TEXT,
    )

    assert PROTOCOL_TEXT in prompt
    assert "Gemeinderat" in prompt
    assert "2024-01-15" in prompt
    assert "2 bis 6" in prompt
    assert "0 bis 5" in prompt
    assert "Quellenanker" in prompt
    assert "Personennamen" in prompt
    assert "Partei" in prompt
    assert "Clickbait" in prompt
    assert "JSON" in prompt


def test_planner_prompt_is_a_pure_deterministic_string_builder():
    arguments = {
        "protocol_title": "Ortsrat Atzenhausen",
        "session_date": date(2024, 2, 3),
        "protocol_text": "TOP 1 Test",
    }

    first = build_planner_prompt(**arguments)
    second = build_planner_prompt(**arguments)

    assert first == second
    assert first.startswith("Du bist")
