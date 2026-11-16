"""Tests for the pure prompt builders of the summary content path."""

from datetime import date

from app.core.post_models import (
    CaptionDraft,
    SourceExcerpt,
    SummaryBrief,
    SummaryDraft,
    SummaryPoint,
)
from app.core.post_prompts import (
    build_caption_prompt,
    build_fact_check_prompt,
    build_planner_prompt,
    build_repair_prompt,
    build_summary_visual_prompt,
    build_summary_writer_prompt,
)

PROTOCOL_TEXT = (
    "TOP 1 Begrüßung\n"
    "Der Vorsitzende eröffnet die Sitzung.\n"
    "\n"
    "TOP 5 Haushalt\n"
    "Der Rat beschließt den Haushalt einstimmig.\n"
)

BRIEFS = [
    SummaryBrief(
        point="Der Haushalt wurde einstimmig beschlossen.",
        relevance="Die Mittel sind für alle Ortsteile wichtig.",
        source_anchors=["Der Rat beschließt den Haushalt einstimmig."],
    ),
    SummaryBrief(
        point="Der Radweg an der Hauptstraße wird gebaut.",
        relevance="Das verbessert die Verbindung im Ort.",
        source_anchors=["Der Radweg wird im Sommer gebaut."],
    ),
]

EXCERPTS = [
    SourceExcerpt(
        anchor="Der Rat beschließt den Haushalt einstimmig.",
        excerpt="Der Rat beschließt den Haushalt einstimmig.",
    ),
    SourceExcerpt(
        anchor="Der Radweg wird im Sommer gebaut.",
        excerpt="Der Radweg an der Hauptstraße wird im Sommer gebaut.",
    ),
]

DRAFT = SummaryDraft(
    cover_title="Was der Rat in Rosdorf entschieden hat",
    points=[
        SummaryPoint(
            kicker="Haushalt",
            heading="Der Rat hat den Haushalt beschlossen",
            body="x" * 120,
        ),
        SummaryPoint(
            kicker="Radweg",
            heading="Der Radweg kommt im Sommer",
            body="y" * 120,
        ),
    ],
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


def test_summary_writer_prompt_contains_only_briefs_excerpts_and_rules():
    prompt = build_summary_writer_prompt(briefs=BRIEFS, excerpts=EXCERPTS)

    for brief in BRIEFS:
        assert brief.point in prompt
    for excerpt in EXCERPTS:
        assert excerpt.excerpt in prompt
    assert "120" in prompt
    assert "320" in prompt
    assert "Ein-Wort-Kicker" in prompt
    assert "20" in prompt
    assert "100" in prompt
    assert "2 bis 6" in prompt
    assert "Personennamen" in prompt
    assert "Clickbait" in prompt

    # The writer never sees the protocol or topic briefs.
    assert PROTOCOL_TEXT not in prompt
    assert "TOP 5 Haushalt" not in prompt
    assert "Themenbrief" not in prompt


def test_summary_writer_prompt_appends_validation_feedback_without_new_inputs():
    prompt = build_summary_writer_prompt(
        briefs=BRIEFS,
        excerpts=EXCERPTS,
        feedback="body must contain 120 to 320 characters including spaces",
    )

    assert "Korrekturhinweis" in prompt
    assert "120 to 320" in prompt
    assert PROTOCOL_TEXT not in prompt
    assert prompt.count(BRIEFS[0].point) == 1


def test_fact_check_prompt_contains_the_draft_and_excerpts_only():
    prompt = build_fact_check_prompt(draft=DRAFT, excerpts=EXCERPTS)

    assert '"cover_title"' in prompt
    assert DRAFT.cover_title in prompt
    assert EXCERPTS[0].excerpt in prompt
    assert "issues" in prompt
    assert PROTOCOL_TEXT not in prompt
    assert "Themenbrief" not in prompt


def test_repair_prompt_contains_draft_issues_and_excerpts_only():
    issues = ["Die Zahl 12 ist in den Quellen nicht belegt."]

    prompt = build_repair_prompt(draft=DRAFT, issues=issues, excerpts=EXCERPTS)

    assert DRAFT.cover_title in prompt
    assert issues[0] in prompt
    assert EXCERPTS[0].excerpt in prompt
    assert PROTOCOL_TEXT not in prompt
    assert "Themenbrief" not in prompt


def test_caption_prompt_contains_draft_and_metadata_only():
    prompt = build_caption_prompt(
        draft=CaptionDraft(body="Der Rat hat den Haushalt beschlossen."),
        organ="Gemeinderat Rosdorf",
        session_date=date(2024, 1, 15),
    )

    assert "Der Rat hat den Haushalt beschlossen." in prompt
    assert "Gemeinderat Rosdorf" in prompt
    assert "15.01.2024" in prompt
    assert "Illustration: KI-generiert." not in prompt
    assert "http" not in prompt
    assert PROTOCOL_TEXT not in prompt
    assert EXCERPTS[0].excerpt not in prompt


def test_summary_visual_prompt_contains_only_the_draft_and_design_guardrails():
    prompt = build_summary_visual_prompt(DRAFT)

    assert DRAFT.cover_title in prompt
    for point in DRAFT.points:
        assert point.heading in prompt
    assert "9:16" in prompt
    assert "Eine atmosphärische Illustration" in prompt
    assert "breite, ruhige" in prompt
    assert "durchgehenden Horizont" in prompt
    assert "Kein zentrales Motiv" in prompt
    assert "Kein Text" in prompt
    assert "Logos" in prompt
    assert "Parteisymbole" in prompt
    assert "erkennbaren Minderjährigen" in prompt
    assert "fotorealistischen" in prompt
    assert "Politiker" in prompt
    assert "artwork_prompts" in prompt

    # The visual prompt writer never sees protocol text, excerpts or topic briefs.
    assert PROTOCOL_TEXT not in prompt
    assert EXCERPTS[0].excerpt not in prompt
    assert "Themenbrief" not in prompt
    assert "Quellenauszüge" not in prompt


def test_summary_visual_prompt_is_deterministic():
    first = build_summary_visual_prompt(DRAFT)
    second = build_summary_visual_prompt(DRAFT)

    assert first == second
    assert first.startswith("Du bist")
