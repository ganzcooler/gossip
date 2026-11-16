"""Validation tests for the pipeline I/O models."""

import pytest
from pydantic import ValidationError

from app.core.post_models import EditorialPlan, SourceExcerpt, SummaryBrief, TopicBrief


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
