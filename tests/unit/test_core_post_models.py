"""Validation tests for the pipeline I/O models."""

import pytest
from pydantic import ValidationError

from app.core.post_models import (
    CaptionDraft,
    EditorialPlan,
    FactCheckResult,
    SourceExcerpt,
    SummaryBrief,
    SummaryDraft,
    SummaryPoint,
    TopicBrief,
    TopicDraft,
    TopicSection,
    VisualPrompts,
)


def _summary_point(**overrides):
    values = {
        "kicker": "Haushalt",
        "heading": "Der Rat hat den Haushalt beschlossen",
        "body": "x" * 120,
    }
    values.update(overrides)
    return SummaryPoint(**values)


def _summary_draft(**overrides):
    values = {
        "cover_title": "Was der Rat in Rosdorf entschieden hat",
        "points": [_summary_point(), _summary_point(kicker="Radweg")],
    }
    values.update(overrides)
    return SummaryDraft(**values)


def _summary_brief(**overrides):
    values = {
        "point": "Der Rat beschließt den Haushalt.",
        "relevance": "Wichtige Entscheidung für Rosdorf.",
        "source_anchors": ["Der Rat beschließt den Haushalt."],
    }
    values.update(overrides)
    return SummaryBrief(**values)


def _topic_brief(**overrides):
    values = {
        "slug": "haushalt",
        "title": "Haushalt beschlossen",
        "focus": "Die wichtigsten Posten",
        "relevance": "Relevanz für alle Ortsteile",
        "source_anchors": ["TOP 5 Haushalt"],
    }
    values.update(overrides)
    return TopicBrief(**values)


def _plan(**overrides):
    values = {
        "summary_focus": "Haushalt und Verkehr",
        "summary_title": "Was der Rat entschieden hat",
        "summary_briefs": [_summary_brief(), _summary_brief(point="Der Radweg kommt.")],
        "topic_briefs": [_topic_brief()],
    }
    values.update(overrides)
    return EditorialPlan(**values)


def test_valid_plan_round_trips_and_allows_no_topics():
    plan = _plan(topic_briefs=[])

    dumped = plan.model_dump()

    assert len(dumped["summary_briefs"]) == 2
    assert dumped["topic_briefs"] == []
    assert EditorialPlan.model_validate(dumped) == plan


@pytest.mark.parametrize("count", [1, 7])
def test_summary_brief_count_is_bounded_to_two_through_six(count):
    with pytest.raises(ValidationError, match="summary_briefs"):
        _plan(summary_briefs=[_summary_brief() for _ in range(count)])


def test_plan_rejects_more_than_five_topics():
    with pytest.raises(ValidationError, match="topic_briefs"):
        _plan(
            topic_briefs=[
                _topic_brief(slug=f"thema-{index}") for index in range(6)
            ]
        )


@pytest.mark.parametrize(
    "slug",
    ["Haushalt", "haus halt", "haus_halt", "haushalt!", ""],
)
def test_topic_slug_must_match_lowercase_slug_pattern(slug):
    with pytest.raises(ValidationError, match="slug"):
        _topic_brief(slug=slug)


def test_plan_rejects_duplicate_topic_slugs():
    with pytest.raises(ValidationError, match="unique"):
        _plan(
            topic_briefs=[
                _topic_brief(slug="haushalt"),
                _topic_brief(slug="haushalt", title="Anderer Titel"),
            ]
        )


@pytest.mark.parametrize("anchors", [[], ["   "], [""]])
def test_briefs_require_non_empty_source_anchors(anchors):
    with pytest.raises(ValidationError, match="source_anchors"):
        _summary_brief(source_anchors=anchors)
    with pytest.raises(ValidationError, match="source_anchors"):
        _topic_brief(source_anchors=anchors)


def test_models_forbid_unknown_fields():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        _summary_brief(unexpected="value")
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        _plan(extra_field=True)


def test_source_excerpt_requires_anchor_and_excerpt():
    excerpt = SourceExcerpt(anchor="TOP 5 Haushalt", excerpt="Der Rat ...")
    assert excerpt.anchor == "TOP 5 Haushalt"

    with pytest.raises(ValidationError):
        SourceExcerpt(anchor="", excerpt="Text")
    with pytest.raises(ValidationError):
        SourceExcerpt(anchor="TOP 5", excerpt="   ")


@pytest.mark.parametrize("length", [120, 320])
def test_summary_point_body_accepts_the_inclusive_bounds(length):
    point = _summary_point(body="x" * length)

    assert len(point.body) == length


@pytest.mark.parametrize("length", [119, 321])
def test_summary_point_body_rejects_out_of_bounds_lengths(length):
    with pytest.raises(ValidationError, match="120"):
        _summary_point(body="x" * length)


def test_summary_point_strips_body_and_rejects_a_multi_word_kicker():
    point = _summary_point(body="  " + "x" * 120 + "  ")

    assert point.body == "x" * 120
    with pytest.raises(ValidationError, match="one word"):
        _summary_point(kicker="Haus halt")
    with pytest.raises(ValidationError, match="one word"):
        _summary_point(kicker="   ")
    with pytest.raises(ValidationError):
        _summary_point(heading="   ")


@pytest.mark.parametrize("cover_title", ["Haushalt", "T" * 101])
def test_summary_cover_title_accepts_short_and_long_non_empty_text(cover_title):
    draft = _summary_draft(cover_title=f"  {cover_title}  ")

    assert draft.cover_title == cover_title


def test_summary_cover_title_rejects_empty_text():
    with pytest.raises(ValidationError, match="must not be empty"):
        _summary_draft(cover_title="   ")


@pytest.mark.parametrize("count", [2, 6])
def test_summary_draft_accepts_two_to_six_points(count):
    draft = _summary_draft(points=[_summary_point() for _ in range(count)])

    assert len(draft.points) == count


@pytest.mark.parametrize("count", [1, 7])
def test_summary_draft_rejects_out_of_bounds_point_counts(count):
    with pytest.raises(ValidationError, match="points"):
        _summary_draft(points=[_summary_point() for _ in range(count)])


def test_summary_models_forbid_unknown_fields():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        _summary_point(unexpected="value")
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        _summary_draft(extra_field=True)


def test_empty_fact_check_result_means_pass():
    result = FactCheckResult(issues=[])

    assert result.issues == []
    assert result.passed is True
    assert FactCheckResult(issues=["Zahl 12 ist nicht belegt."]).passed is False


def test_fact_check_issues_must_be_non_empty_and_actionable_strings():
    assert FactCheckResult(issues=["  Die Zahl 12 fehlt in den Quellen.  "]).issues == [
        "Die Zahl 12 fehlt in den Quellen."
    ]
    with pytest.raises(ValidationError, match="actionable"):
        FactCheckResult(issues=["   "])
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        FactCheckResult(issues=[], ok=True)


def _topic_section(**overrides):
    values = {
        "h2": "Der Rat hat den Haushalt beschlossen",
        "paragraphs": [
            "Der Rat hat den Haushalt einstimmig beschlossen und die Mittel "
            "für alle Ortsteile freigegeben."
        ],
    }
    values.update(overrides)
    return TopicSection(**values)


def _topic_draft(**overrides):
    values = {
        "title": "Was der Rat in Rosdorf entschieden hat",
        "sections": [
            _topic_section(),
            _topic_section(
                h2="Der Radweg wird im Sommer gebaut",
                paragraphs=[
                    "Der Radweg an der Hauptstraße wird im Sommer gebaut."
                ],
            ),
        ],
    }
    values.update(overrides)
    return TopicDraft(**values)


@pytest.mark.parametrize("length", [20, 100])
def test_topic_title_accepts_the_inclusive_bounds(length):
    draft = _topic_draft(title="T" * length)

    assert draft.title == "T" * length


@pytest.mark.parametrize("length", [19, 101])
def test_topic_title_rejects_out_of_bounds_lengths(length):
    with pytest.raises(ValidationError, match="20"):
        _topic_draft(title="T" * length)


@pytest.mark.parametrize("length", [20, 60])
def test_topic_section_h2_accepts_the_inclusive_bounds(length):
    section = _topic_section(h2="H" * length)

    assert section.h2 == "H" * length


@pytest.mark.parametrize("length", [19, 61])
def test_topic_section_h2_rejects_out_of_bounds_lengths(length):
    with pytest.raises(ValidationError, match="20"):
        _topic_section(h2="H" * length)


@pytest.mark.parametrize("count", [2, 6])
def test_topic_draft_accepts_two_to_six_sections(count):
    draft = _topic_draft(sections=[_topic_section() for _ in range(count)])

    assert len(draft.sections) == count


@pytest.mark.parametrize("count", [1, 7])
def test_topic_draft_rejects_out_of_bounds_section_counts(count):
    with pytest.raises(ValidationError, match="sections"):
        _topic_draft(sections=[_topic_section() for _ in range(count)])


def test_topic_draft_accepts_exactly_3000_characters_and_rejects_3001():
    accepted = _topic_draft(
        title="T" * 20,
        sections=[
            _topic_section(h2="H" * 20, paragraphs=["x" * 1470]),
            _topic_section(h2="H" * 20, paragraphs=["y" * 1470]),
        ],
    )
    assert (
        len(accepted.title)
        + sum(
            len(section.h2) + sum(len(p) for p in section.paragraphs)
            for section in accepted.sections
        )
        == 3000
    )

    with pytest.raises(ValidationError, match="3000"):
        _topic_draft(
            title="T" * 20,
            sections=[
                _topic_section(h2="H" * 20, paragraphs=["x" * 1471]),
                _topic_section(h2="H" * 20, paragraphs=["y" * 1470]),
            ],
        )


def test_topic_paragraphs_have_no_individual_length_limit():
    draft = _topic_draft(
        title="T" * 20,
        sections=[
            _topic_section(h2="H" * 20, paragraphs=["x" * 2900]),
            _topic_section(h2="H" * 20, paragraphs=["y"]),
        ],
    )

    assert len(draft.sections[0].paragraphs[0]) == 2900


@pytest.mark.parametrize("paragraphs", [[], ["   "], [""]])
def test_topic_section_requires_non_empty_paragraphs(paragraphs):
    with pytest.raises(ValidationError, match="paragraph"):
        _topic_section(paragraphs=paragraphs)


def test_topic_models_strip_whitespace():
    section = _topic_section(h2="  Der Rat hat den Haushalt beschlossen  ")
    draft = _topic_draft(
        title="  Was der Rat in Rosdorf entschieden hat  ",
        sections=[
            _topic_section(
                h2="  Der Rat hat den Haushalt beschlossen  ",
                paragraphs=["  Der Rat hat den Haushalt beschlossen.  "],
            ),
            _topic_section(h2="  Der Radweg wird im Sommer gebaut  "),
        ],
    )

    assert section.h2 == "Der Rat hat den Haushalt beschlossen"
    assert draft.title == "Was der Rat in Rosdorf entschieden hat"
    assert draft.sections[0].paragraphs == [
        "Der Rat hat den Haushalt beschlossen."
    ]


def test_topic_draft_forbids_lead_takeaways_kicker_and_extra_fields():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        _topic_draft(lead="Ein Lead")
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        _topic_draft(takeaways=["Ein Punkt"])
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        _topic_section(kicker="Haushalt")
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        _topic_section(extra_field=True)


def test_caption_draft_strips_and_requires_body_text():
    draft = CaptionDraft(body="  Der Rat hat entschieden.  ")

    assert draft.body == "Der Rat hat entschieden."
    with pytest.raises(ValidationError):
        CaptionDraft(body="   ")
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CaptionDraft(body="Text", prefix="Illustration")


def test_visual_prompts_require_a_cover_and_allow_empty_artwork_for_summary():
    prompts = VisualPrompts(cover_prompt="  Weite, ruhige Szene am Ortsrand.  ")

    assert prompts.cover_prompt == "Weite, ruhige Szene am Ortsrand."
    assert prompts.artwork_prompts == []


def test_visual_prompts_accept_artwork_prompts_and_strip_them():
    prompts = VisualPrompts(
        cover_prompt="Cover",
        artwork_prompts=["  Paar 1  ", "Paar 2"],
    )

    assert prompts.artwork_prompts == ["Paar 1", "Paar 2"]


@pytest.mark.parametrize("value", ["", "   "])
def test_visual_prompts_reject_empty_prompts(value):
    with pytest.raises(ValidationError):
        VisualPrompts(cover_prompt=value)
    with pytest.raises(ValidationError):
        VisualPrompts(cover_prompt="Cover", artwork_prompts=[value])


def test_visual_prompts_forbid_unknown_fields():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        VisualPrompts(cover_prompt="Cover", style="photorealistic")
