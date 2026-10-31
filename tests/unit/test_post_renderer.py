"""Renderer tests: output dimensions, file structure, and fixed-size overflow."""

from pathlib import Path

import pytest
from PIL import Image

from app.core.post_models import (
    CoverPlan,
    SlideContent,
    SummarySlidePlan,
    TopicSlidePair,
    TopicSlidePlan,
)
from app.services.errors import TextOverflowError
from app.services.post_renderer import (
    _strip_session_label,
    render_summary_story,
    render_topic_carousel,
)

RES_DIR = Path(__file__).resolve().parents[2] / "app" / "res"


def _image(size=(1080, 1350), color=(70, 90, 110)) -> Image.Image:
    return Image.new("RGB", size, color)


def _summary_plan(body: str = "Der Rat hat den Haushalt mit knapper Mehrheit verabschiedet.") -> SummarySlidePlan:
    return SummarySlidePlan(
        cover=CoverPlan(
            kicker="SITZUNG KOMPAKT",
            headline="Haushalt, Windpark, Radwege: Das war die Sitzung",
            image_brief="A calm town hall at dusk",
        ),
        slides=[
            SlideContent(
                label="HAUSHALT",
                headline="Haushalt 2026 beschlossen",
                body=body,
            ),
            SlideContent(
                label="WINDPARK",
                headline="Standortentscheidung vertagt",
                body="Die Entscheidung über den Standort wird in die nächste Sitzung verschoben.",
            ),
            SlideContent(
                label="AUSBLICK",
                headline="Wie es weitergeht",
                body="Die nächste Sitzung ist für April angesetzt.",
            ),
        ],
    )


def _topic_plan() -> TopicSlidePlan:
    return TopicSlidePlan(
        cover=CoverPlan(
            kicker="THEMA IM FOKUS",
            headline="Windpark: Warum die Entscheidung vertagt wurde",
            image_brief="A calm landscape with a wind turbine",
        ),
        pairs=[
            TopicSlidePair(
                slides=[
                    SlideContent(
                        label="BESCHLUSS",
                        headline="Was beschlossen wurde",
                        body="Der Rat hat den Tagesordnungspunkt vertagt.",
                    ),
                    SlideContent(
                        label="HINTERGRUND",
                        headline="Warum das wichtig ist",
                        body="Anwohner hatten Fragen zum Lärmschutz eingereicht.",
                    ),
                ],
                artwork_brief="One calm landscape, no text",
            ),
            TopicSlidePair(
                slides=[
                    SlideContent(
                        label="AUSBLICK",
                        headline="Wie es weitergeht",
                        body="Bis April soll ein Gutachten vorliegen.",
                    ),
                    SlideContent(
                        label="FAZIT",
                        headline="Was offen bleibt",
                        body="Die Verwaltung prüft einen neuen Standortvorschlag.",
                    ),
                ],
                artwork_brief="A quiet field at dusk, no text",
            ),
        ],
    )


def test_render_summary_story_creates_cover_and_content_slides(tmp_path):
    paths = render_summary_story(
        cover_image=_image((1080, 1920)),
        plan=_summary_plan(),
        output_dir=tmp_path,
        res_dir=RES_DIR,
    )

    assert len(paths) == 4
    assert paths[0].name == "summary_cover.jpg"
    assert [path.name for path in paths[1:]] == [
        "summary_slide_01.jpg",
        "summary_slide_02.jpg",
        "summary_slide_03.jpg",
    ]
    with Image.open(paths[0]) as image:
        assert image.size == (1080, 1920)
    with Image.open(paths[1]) as image:
        assert image.size == (1080, 1920)


def test_render_topic_carousel_creates_paired_slides(tmp_path):
    paths = render_topic_carousel(
        cover_image=_image(),
        artwork_images=[_image((1920, 1080)), _image((1920, 1080))],
        plan=_topic_plan(),
        output_dir=tmp_path,
        post_index=1,
        res_dir=RES_DIR,
    )

    assert len(paths) == 5
    assert paths[0].name == "topic_01_cover.jpg"
    assert [path.name for path in paths[1:]] == [
        "topic_01_slide_01.jpg",
        "topic_01_slide_02.jpg",
        "topic_01_slide_03.jpg",
        "topic_01_slide_04.jpg",
    ]
    with Image.open(paths[0]) as image:
        assert image.size == (1080, 1350)
    with Image.open(paths[1]) as image:
        assert image.size == (1080, 1350)


def test_summary_renderer_rejects_overlong_body_without_shrinking(tmp_path):
    body = "Wort " * 500
    with pytest.raises(TextOverflowError):
        render_summary_story(
            cover_image=_image((1080, 1920)),
            plan=_summary_plan(body=body),
            output_dir=tmp_path,
            res_dir=RES_DIR,
        )


def test_strip_session_label_removes_leading_committee():
    assert (
        _strip_session_label(
            "Ortsrat Obernjesa: Haushalt, Windpark, Radwege",
            "Ortsrat Obernjesa",
        )
        == "Haushalt, Windpark, Radwege"
    )
    assert (
        _strip_session_label(
            "Haushalt, Windpark, Radwege",
            "Ortsrat Obernjesa",
        )
        == "Haushalt, Windpark, Radwege"
    )
