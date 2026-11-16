"""Direct, deterministic tests for the blue 1080x1920 Summary renderer."""

from dataclasses import replace
from datetime import date
from types import SimpleNamespace

import pytest
from PIL import Image

from app.core.post_models import SummaryDraft
from app.services import render_common
from app.services.caption_writer import compose_caption
from app.services.post_renderer import (
    CARD_BOX,
    SUMMARY_SIZE,
    RenderError,
    render_summary_frames,
    summary_body_top,
    summary_composition_from_stored,
    write_summary_output,
)
from app.services.slide_composer import compose_summary_slides

BLUE = (30, 123, 181)
SURFACE_BASE = (30, 30, 33)
OUTLINE = (70, 70, 75)
PLATE_WHITE = (255, 255, 255)


def _draft() -> SummaryDraft:
    return SummaryDraft(
        cover_title="Was der Rat in Rosdorf entschieden hat",
        points=[
            {
                "kicker": "Haushalt",
                "heading": "Der Rat hat den Haushalt beschlossen",
                "body": (
                    "Der Rat hat den Haushalt einstimmig beschlossen. "
                    "Die Mittel werden im Frühjahr ausgezahlt und kommen "
                    "allen Ortsteilen zugute. Die Verwaltung setzt die "
                    "Beschlüsse Schritt für Schritt um."
                ),
            },
            {
                "kicker": "Radweg",
                "heading": "Der Radweg kommt im Sommer",
                "body": (
                    "Der neue Radweg an der Hauptstraße wird im Sommer "
                    "gebaut. Er verbindet die Ortsteile und macht den "
                    "Schulweg sicherer. Die Bauarbeiten beginnen nach den "
                    "Sommerferien und dauern mehrere Wochen."
                ),
            },
        ],
    )


def _cover_art() -> Image.Image:
    image = Image.new("RGB", SUMMARY_SIZE, (80, 120, 90))
    image.paste((150, 110, 60), (0, 0, 540, 1920))
    return image


def _render_frames(organ: str = "Gemeinderat Rosdorf"):
    draft = _draft()
    composition = compose_summary_slides(draft)
    return (
        draft,
        composition,
        render_summary_frames(
            draft,
            composition,
            cover_art=_cover_art(),
            organ=organ,
        ),
    )


def _has_color(image: Image.Image, box, color) -> bool:
    region = image.crop(box)
    colors = region.getcolors(maxcolors=region.width * region.height) or []
    return any(pixel == color for _, pixel in colors)


def test_renderer_produces_cover_and_two_cards_at_1080x1920_rgb():
    _, composition, frames = _render_frames()

    assert len(composition.slides) == 3
    assert len(frames) == 3
    for frame in frames:
        assert frame.size == SUMMARY_SIZE == (1080, 1920)
        assert frame.mode == "RGB"


def test_cover_has_the_blue_top_rule_logo_plate_badge_kicker_and_white_title():
    _, _, frames = _render_frames()
    cover = frames[0]

    assert cover.getpixel((540, 2)) == BLUE
    assert cover.getpixel((80, 290)) == PLATE_WHITE
    assert cover.getpixel((63, 290)) != PLATE_WHITE
    assert cover.getpixel((1000, 320)) == BLUE
    assert cover.getpixel((64, 720)) == BLUE
    assert _has_color(cover, (64, 800, 1014, 1100), (255, 255, 255))


def test_card_has_the_blue_edge_profile_card_rule_number_and_page_label():
    _, _, frames = _render_frames()
    card = frames[1]

    assert card.getpixel((70, 1000)) == BLUE
    assert card.getpixel((100, 1000)) == SURFACE_BASE
    assert card.getpixel((540, 1670)) == SURFACE_BASE
    assert card.getpixel((40, 1000)) != SURFACE_BASE
    assert card.getpixel((118, 691)) == OUTLINE
    assert card.getpixel((540, 692)) == OUTLINE
    assert card.getpixel((80, 290)) == PLATE_WHITE
    assert card.getpixel((63, 290)) != PLATE_WHITE
    assert _has_color(card, (118, 500, 320, 630), BLUE)
    assert _has_color(card, (118, 1630, 400, 1660), BLUE)
    assert _has_color(card, (118, 718, 918, 1000), (255, 255, 255))


def test_body_top_follows_the_heading_line_boxes_plus_38px():
    assert summary_body_top(76, 1) == pytest.approx(838.08)
    assert summary_body_top(76, 2) == pytest.approx(920.16)
    assert summary_body_top(76, 3) == pytest.approx(1002.24)
    assert summary_body_top(68, 1) == pytest.approx(829.44)


def test_card_geometry_is_the_approved_952x1220_box():
    assert CARD_BOX == (64, 460, 1016, 1680)
    x0, y0, x1, y1 = CARD_BOX
    assert (x1 - x0, y1 - y0) == (952, 1220)


def test_stored_slide_plan_and_slides_reconstruct_the_rendering_composition():
    draft, composition, _ = _render_frames()
    stored_slides = [
        SimpleNamespace(
            slide_index=slide.slide_index,
            slide_type=slide.slide_type,
            label=slide.label,
            headline=slide.headline,
            body=slide.body,
            alt_text=slide.alt_text,
        )
        for slide in composition.slides
    ]

    restored = summary_composition_from_stored(
        draft, composition.slide_plan, stored_slides
    )

    assert [slide.page_label for slide in restored.slides] == [
        None,
        "02 / 03",
        "03 / 03",
    ]
    assert [slide.heading_lines for slide in restored.slides[1:]] == [
        composition.slides[1].heading_lines,
        composition.slides[2].heading_lines,
    ]
    assert restored.body_size == composition.body_size
    assert restored.slides[0].heading_size == composition.cover_title_size


def test_write_summary_output_creates_exact_filenames_and_one_caption(tmp_path):
    draft, composition, frames = _render_frames()
    caption = compose_caption(
        body="Der Rat hat wichtige Entscheidungen getroffen.",
        organ="Gemeinderat Rosdorf",
        session_date=date(2024, 3, 12),
        protocol=SimpleNamespace(getfile_id=4711),
        base_url="https://sessionnet.example/rosdorf/BI/",
    )
    post = SimpleNamespace(caption=caption)
    protocol = SimpleNamespace(
        session_date=date(2024, 3, 12), title="Gemeinderat"
    )

    output = write_summary_output(
        frames, post=post, protocol=protocol, output_dir=tmp_path
    )

    folder = tmp_path / "240312_gemeinderat"
    assert output.folder == folder
    assert sorted(path.name for path in folder.iterdir()) == [
        "caption-summary-summary.txt",
        "summary-2024-03-12-story-01.png",
        "summary-2024-03-12-story-02.png",
        "summary-2024-03-12-story-03.png",
    ]
    assert output.image_paths == [
        folder / "summary-2024-03-12-story-01.png",
        folder / "summary-2024-03-12-story-02.png",
        folder / "summary-2024-03-12-story-03.png",
    ]
    assert output.caption_path == folder / "caption-summary-summary.txt"
    assert output.caption_path.read_text(encoding="utf-8") == caption
    assert caption.splitlines()[0] == "Illustration: KI-generiert."
    assert "12.03.2024" in caption
    assert "https://sessionnet.example/rosdorf/BI/getfile.asp?id=4711" in caption
    for path in output.image_paths:
        with Image.open(path) as image:
            assert image.size == SUMMARY_SIZE
            assert image.mode == "RGB"

    again = write_summary_output(
        frames, post=post, protocol=protocol, output_dir=tmp_path
    )
    assert sorted(path.name for path in again.folder.iterdir()) == sorted(
        path.name for path in folder.iterdir()
    )


def test_write_summary_output_rejects_a_missing_caption_before_writing_files(
    tmp_path,
):
    _, _, frames = _render_frames()
    post = SimpleNamespace(caption=None)
    protocol = SimpleNamespace(
        session_date=date(2024, 3, 12), title="Gemeinderat"
    )

    with pytest.raises(RenderError, match="caption"):
        write_summary_output(
            frames, post=post, protocol=protocol, output_dir=tmp_path
        )

    assert list(tmp_path.iterdir()) == []


def test_write_summary_output_writes_the_manual_link_hint_when_the_link_is_missing(
    tmp_path,
):
    _, _, frames = _render_frames()
    caption = compose_caption(
        body="Der Rat hat wichtige Entscheidungen getroffen.",
        organ="Gemeinderat Rosdorf",
        session_date=date(2024, 3, 12),
        protocol=SimpleNamespace(getfile_id=None),
    )
    output = write_summary_output(
        frames,
        post=SimpleNamespace(caption=caption),
        protocol=SimpleNamespace(
            session_date=date(2024, 3, 12), title="Gemeinderat"
        ),
        output_dir=tmp_path,
    )

    text = output.caption_path.read_text(encoding="utf-8")
    assert text == caption
    assert text.startswith("Illustration: KI-generiert.\n")
    assert "Hinweis: Der SessionNet-Link fehlt" in text
    assert "http" not in text


def test_overlong_heading_lines_are_a_render_failure_not_truncation():
    draft, composition, _ = _render_frames()
    broken_slide = replace(
        composition.slides[1],
        heading_lines=("W" * 200,),
    )
    broken = replace(
        composition,
        slides=(composition.slides[0], broken_slide, composition.slides[2]),
    )

    with pytest.raises(RenderError, match="heading"):
        render_summary_frames(
            draft, broken, cover_art=_cover_art(), organ="Gemeinderat Rosdorf"
        )


def test_body_overflow_is_a_render_failure_and_writes_no_files(tmp_path):
    draft, composition, _ = _render_frames()
    broken_slide = replace(
        composition.slides[1],
        body_lines=tuple("W" * 40 for _ in range(60)),
    )
    broken = replace(
        composition,
        slides=(composition.slides[0], broken_slide, composition.slides[2]),
    )

    with pytest.raises(RenderError, match="body"):
        render_summary_frames(
            draft, broken, cover_art=_cover_art(), organ="Gemeinderat Rosdorf"
        )
    assert list(tmp_path.iterdir()) == []


def test_missing_logo_is_a_hard_render_failure(monkeypatch):
    draft, composition, _ = _render_frames()
    monkeypatch.setattr(
        render_common, "LOGO_PATH", render_common.RESOURCE_DIR / "missing-logo.png"
    )

    with pytest.raises(RenderError, match="logo"):
        render_summary_frames(
            draft, composition, cover_art=_cover_art(), organ="Gemeinderat Rosdorf"
        )


def test_missing_font_is_a_hard_render_failure(monkeypatch):
    draft, composition, _ = _render_frames()
    monkeypatch.setitem(
        render_common.FONT_PATHS,
        "oswald",
        render_common.RESOURCE_DIR / "missing-font.ttf",
    )

    with pytest.raises(RenderError, match="font"):
        render_summary_frames(
            draft, composition, cover_art=_cover_art(), organ="Gemeinderat Rosdorf"
        )
