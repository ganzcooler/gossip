"""Tests for the pure prompt builders of the post pipeline."""

from datetime import date

import pytest

from app.core.post_models import (
    CaptionDraft,
    SourceExcerpt,
    SummaryBrief,
    SummaryDraft,
    SummaryPoint,
    TopicBrief,
    TopicDraft,
)
from app.core.post_prompts import (
    build_caption_prompt,
    build_fact_check_prompt,
    build_planner_prompt,
    build_repair_prompt,
    build_summary_visual_prompt,
    build_summary_writer_prompt,
    build_topic_visual_prompt,
    build_topic_writer_prompt,
)
from app.services.caption_writer import CAPTION_FIRST_LINE

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
    assert "2 to 6" in prompt
    assert "0 to 5" in prompt
    assert "source anchor" in prompt.lower()
    assert "personal names" in prompt
    assert "party" in prompt
    assert "clickbait" in prompt
    assert "German" in prompt
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
    assert first.startswith("You are")


def test_summary_writer_prompt_contains_only_briefs_excerpts_and_rules():
    prompt = build_summary_writer_prompt(briefs=BRIEFS, excerpts=EXCERPTS)

    for brief in BRIEFS:
        assert brief.point in prompt
    for excerpt in EXCERPTS:
        assert excerpt.excerpt in prompt
    assert "120" in prompt
    assert "320" in prompt
    assert "one-word kicker" in prompt
    assert "German noun" in prompt
    assert "at most 3 lines" in prompt
    assert "2 to 6" in prompt
    assert "personal names" in prompt
    assert "clickbait" in prompt
    assert "German" in prompt

    # The writer never sees the protocol or topic briefs.
    assert PROTOCOL_TEXT not in prompt
    assert "TOP 5 Haushalt" not in prompt
    assert "Topic brief" not in prompt


def test_summary_writer_prompt_appends_validation_feedback_without_new_inputs():
    prompt = build_summary_writer_prompt(
        briefs=BRIEFS,
        excerpts=EXCERPTS,
        feedback="body must contain 120 to 320 characters including spaces",
    )

    assert "Correction Note" in prompt
    assert "120 to 320" in prompt
    assert PROTOCOL_TEXT not in prompt
    assert prompt.count(BRIEFS[0].point) == 1


TOPIC_BRIEF = TopicBrief(
    slug="haushalt",
    title="Haushalt beschlossen",
    focus="Die wichtigsten Posten im Gemeindehaushalt",
    relevance="Die Entscheidung betrifft alle Ortsteile.",
    source_anchors=["Der Rat beschließt den Haushalt einstimmig."],
)

TOPIC_EXCERPTS = [EXCERPTS[0]]


def test_topic_writer_prompt_contains_only_the_brief_excerpts_and_rules():
    prompt = build_topic_writer_prompt(
        brief=TOPIC_BRIEF, excerpts=TOPIC_EXCERPTS
    )

    assert TOPIC_BRIEF.slug in prompt
    assert TOPIC_BRIEF.title in prompt
    assert TOPIC_BRIEF.focus in prompt
    assert TOPIC_BRIEF.relevance in prompt
    assert TOPIC_BRIEF.source_anchors[0] in prompt
    assert TOPIC_EXCERPTS[0].excerpt in prompt
    assert "20 to 100" in prompt
    assert "20 to 60" in prompt
    assert "2 to 6" in prompt
    assert "3000" in prompt
    assert "three to seven" in prompt
    assert "German" in prompt
    assert "personal names" in prompt
    assert "party" in prompt
    assert "clickbait" in prompt
    assert "emojis" in prompt
    assert "JSON" in prompt

    # The topic writer never sees the protocol, Summary briefs or other topics.
    assert PROTOCOL_TEXT not in prompt
    assert "TOP 5 Haushalt" not in prompt
    assert "Summary" not in prompt
    assert "Radweg an der Hauptstraße" not in prompt


def test_topic_writer_prompt_appends_feedback_without_new_inputs():
    prompt = build_topic_writer_prompt(
        brief=TOPIC_BRIEF,
        excerpts=TOPIC_EXCERPTS,
        feedback="The draft produces only two content slides.",
    )

    assert "Correction Note" in prompt
    assert "only two content slides" in prompt
    assert prompt.count(TOPIC_BRIEF.focus) == 1
    assert PROTOCOL_TEXT not in prompt


def test_topic_writer_prompt_is_a_pure_deterministic_string_builder():
    arguments = {"brief": TOPIC_BRIEF, "excerpts": TOPIC_EXCERPTS}

    assert build_topic_writer_prompt(**arguments) == build_topic_writer_prompt(
        **arguments
    )


def test_fact_check_prompt_contains_the_draft_and_excerpts_only():
    prompt = build_fact_check_prompt(draft=DRAFT, excerpts=EXCERPTS)

    assert '"cover_title"' in prompt
    assert DRAFT.cover_title in prompt
    assert EXCERPTS[0].excerpt in prompt
    assert "issues" in prompt
    assert "written in German" in prompt
    assert PROTOCOL_TEXT not in prompt
    assert "Topic brief" not in prompt


def test_repair_prompt_contains_draft_issues_and_excerpts_only():
    issues = ["Die Zahl 12 ist in den Quellen nicht belegt."]

    prompt = build_repair_prompt(draft=DRAFT, issues=issues, excerpts=EXCERPTS)

    assert DRAFT.cover_title in prompt
    assert issues[0] in prompt
    assert EXCERPTS[0].excerpt in prompt
    assert "German" in prompt
    assert PROTOCOL_TEXT not in prompt
    assert "Topic brief" not in prompt


def test_caption_prompt_contains_draft_and_metadata_only():
    prompt = build_caption_prompt(
        draft=CaptionDraft(body="Der Rat hat den Haushalt beschlossen."),
        organ="Gemeinderat Rosdorf",
        session_date=date(2024, 1, 15),
    )

    assert "Der Rat hat den Haushalt beschlossen." in prompt
    assert "Gemeinderat Rosdorf" in prompt
    assert "15.01.2024" in prompt
    assert "German" in prompt
    assert CAPTION_FIRST_LINE not in prompt
    assert "http" not in prompt
    assert PROTOCOL_TEXT not in prompt
    assert EXCERPTS[0].excerpt not in prompt


def test_summary_visual_prompt_contains_only_the_draft_and_design_guardrails():
    prompt = build_summary_visual_prompt(DRAFT)

    assert DRAFT.cover_title in prompt
    for point in DRAFT.points:
        assert point.heading in prompt
    assert "9:16" in prompt
    assert "Photorealistic editorial and reportage photography" in prompt
    assert "natural light" in prompt
    assert "No illustration" in prompt
    assert "No frame" in prompt
    assert "lively, believable civic scene" in prompt
    assert "Adults of different ages" in prompt
    assert "Do not show recognizable minors" in prompt
    assert "Text, letters, numbers" in prompt
    assert "logos, coats of arms" in prompt
    assert "fictional adults" in prompt
    assert "recognizable real politicians" in prompt
    assert "party symbols" in prompt
    assert "dry, gently sarcastic" in prompt
    assert "extreme frame edges" in prompt
    assert "upper and middle" not in prompt
    assert "lower image zone" not in prompt
    assert "No logos, coats of arms" not in prompt
    assert "English only" in prompt
    assert "exactly one image prompt" in prompt
    assert "artwork_prompts" not in prompt

    # The visual prompt writer never sees protocol text, excerpts or topics.
    assert PROTOCOL_TEXT not in prompt
    assert EXCERPTS[0].excerpt not in prompt
    assert "Topic brief" not in prompt
    assert "Source excerpts" not in prompt


def test_summary_visual_prompt_is_deterministic():
    first = build_summary_visual_prompt(DRAFT)
    second = build_summary_visual_prompt(DRAFT)

    assert first == second
    assert first.startswith("You are")


TOPIC_DRAFT = TopicDraft(
    title="Was der Rat zum Haushalt in Rosdorf entschieden hat",
    sections=[
        {
            "h2": "Der Rat hat den Haushalt einstimmig beschlossen",
            "paragraphs": ["Der Rat hat den Haushalt einstimmig beschlossen."],
        },
        {
            "h2": "Was jetzt mit den Mitteln für die Ortsteile passiert",
            "paragraphs": ["Die Verwaltung setzt die Mittel im Frühjahr um."],
        },
    ],
)


def test_topic_visual_prompt_contains_only_the_draft_and_pair_count():
    prompt = build_topic_visual_prompt(TOPIC_DRAFT, 3)

    assert TOPIC_DRAFT.title in prompt
    for section in TOPIC_DRAFT.sections:
        assert section.h2 in prompt
    assert "Return exactly 4 image prompts" in prompt
    assert "1 cover_prompt" in prompt
    assert "3 artwork_prompts" in prompt
    assert "0 single_prompt values" in prompt
    assert "4:5" in prompt
    assert "Photorealistic editorial and reportage photography" in prompt
    assert "No illustration" in prompt
    assert "No frame" in prompt
    assert "continuous horizon" in prompt
    assert "Adults of different ages" in prompt
    assert "Do not show recognizable minors" in prompt
    assert "Text, letters, numbers" in prompt
    assert "logos, coats of arms" in prompt
    assert "fictional adults" in prompt
    assert "recognizable real politicians" in prompt
    assert "party symbols" in prompt
    assert "dry, gently sarcastic" in prompt
    assert "uninterrupted photograph" in prompt
    assert "40 px from the centre seam" not in prompt
    assert "split into two" not in prompt
    assert "upper and middle" not in prompt
    assert "lower image zone" not in prompt
    assert "No logos, coats of arms" not in prompt
    assert "English only" in prompt
    assert "artwork_prompts" in prompt

    # The topic visual writer sees no protocol, excerpts, Summary or topics.
    assert PROTOCOL_TEXT not in prompt
    assert EXCERPTS[0].excerpt not in prompt
    assert "Source excerpts" not in prompt
    assert "Summary" not in prompt
    assert "Topic brief" not in prompt


def test_topic_visual_prompt_requests_a_dedicated_single_prompt():
    prompt = build_topic_visual_prompt(TOPIC_DRAFT, 2, has_single=True)

    assert "single_prompt" in prompt
    assert "middle third" in prompt
    assert "outer areas may be cropped" in prompt
    assert "no calm, empty" in prompt
    assert "single_prompt values" in prompt


def test_topic_visual_prompt_without_single_requests_zero_single_prompts():
    prompt = build_topic_visual_prompt(TOPIC_DRAFT, 2)

    assert "0 single_prompt values" in prompt
    assert "set single_prompt to null" in prompt
    assert "middle third" not in prompt


def test_topic_visual_prompt_counts_all_required_images():
    one_pair = build_topic_visual_prompt(TOPIC_DRAFT, 1)
    two_pairs_one_single = build_topic_visual_prompt(
        TOPIC_DRAFT, 2, has_single=True
    )

    assert "Return exactly 2 image prompts" in one_pair
    assert "1 artwork_prompt" in one_pair
    assert "Return exactly 4 image prompts" in two_pairs_one_single
    assert "1 single_prompt for the unpaired last slide" in two_pairs_one_single


def test_topic_visual_prompt_is_deterministic_and_requires_pairs():
    first = build_topic_visual_prompt(TOPIC_DRAFT, 2)
    second = build_topic_visual_prompt(TOPIC_DRAFT, 2)

    assert first == second
    assert first.startswith("You are")
    assert "Correction Note" not in first
    with pytest.raises(ValueError, match="pair_count"):
        build_topic_visual_prompt(TOPIC_DRAFT, 0)


def test_topic_visual_prompt_appends_validation_feedback():
    prompt = build_topic_visual_prompt(TOPIC_DRAFT, 2, feedback="0 instead of 2 prompts")

    assert "## Correction Note" in prompt
    assert "0 instead of 2 prompts" in prompt
    assert "exactly 3 image prompts" in prompt
    assert "2 artwork_prompts" in prompt
    assert prompt.index("Correction Note") < prompt.index("## Output format")
