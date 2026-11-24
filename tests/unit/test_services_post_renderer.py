"""Direct, deterministic tests for the blue 1080x1920 Summary renderer."""

from dataclasses import replace
from datetime import date
from types import SimpleNamespace

import pytest
from PIL import Image

from app.core.post_models import SummaryDraft
from app.services import render_common
from app.services.caption_writer import CAPTION_FIRST_LINE, compose_caption
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
from tests.support.render_helpers import (
    LOGO_COLOR,
    color_bbox as _color_bbox,
    use_empty_logo as _use_empty_logo,
    use_transparent_logo as _use_transparent_logo,
)

BLUE = (30, 123, 181)
SURFACE_BASE = (30, 30, 33)
OUTLINE = (70, 70, 75)
WHITE = (255, 255, 255)

SHORT_COVER_TITLE = "Haushalt beschlossen"
LONG_COVER_TITLE = (
    "Was der Rat zum Haushalt und zum Radweg in Rosdorf entschieden hat"
)


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


def _render_cover(
    *, title: str | None = None, art: Image.Image | None = None
) -> Image.Image:
    draft = (
        _draft()
        if title is None
        else _draft().model_copy(update={"cover_title": title})
    )
    composition = compose_summary_slides(draft)
    return render_summary_frames(
        draft,
        composition,
        cover_art=_cover_art() if art is None else art,
        organ="Gemeinderat Rosdorf",
    )[0]


def _lower_white_bbox(cover: Image.Image, top: int):
    return _color_bbox(cover, (0, top, SUMMARY_SIZE[0], SUMMARY_SIZE[1]), WHITE)


def test_renderer_produces_cover_and_two_cards_at_1080x1920_rgb():
    _, composition, frames = _render_frames()

    assert len(composition.slides) == 3
    assert len(frames) == 3
    for frame in frames:
        assert frame.size == SUMMARY_SIZE == (1080, 1920)
        assert frame.mode == "RGB"


def test_cover_has_the_blue_top_rule_badge_kicker_and_white_title():
    _, _, frames = _render_frames()
    cover = frames[0]

    assert cover.getpixel((540, 2)) == BLUE
    assert cover.getpixel((1000, 280)) == BLUE
    assert _has_color(cover, (64, 1200, 600, 1730), BLUE)
    assert _has_color(cover, (64, 1200, 1014, 1730), WHITE)


@pytest.mark.parametrize(
    "title",
    [
        SHORT_COVER_TITLE,
        "Was der Rat in Rosdorf entschieden hat",
        LONG_COVER_TITLE,
    ],
    ids=["one-line", "two-line", "three-line"],
)
def test_cover_title_is_bottom_anchored_by_its_ink_box_at_1720(title):
    cover = _render_cover(title=title)

    title_bbox = _lower_white_bbox(cover, 1200)

    assert title_bbox is not None
    assert abs(title_bbox[3] - 1720) <= 6


def test_cover_kicker_sits_directly_above_the_left_aligned_title():
    cover = _render_cover(title=LONG_COVER_TITLE)

    kicker_bbox = _color_bbox(cover, (0, 1200, 1080, 1920), BLUE)
    assert kicker_bbox is not None
    title_bbox = _lower_white_bbox(cover, kicker_bbox[3])
    assert title_bbox is not None

    assert kicker_bbox[0] == 64
    assert 20 <= title_bbox[1] - kicker_bbox[3] <= 28
    assert title_bbox[0] <= 74


def test_cover_has_a_single_bottom_up_scrim_with_a_transparent_top():
    height = SUMMARY_SIZE[1]
    cover = _render_cover(art=Image.new("RGB", SUMMARY_SIZE, WHITE))

    assert cover.getpixel((1050, 100)) == WHITE
    assert cover.getpixel((1050, int(0.35 * (height - 1)))) == WHITE

    assert sum(cover.getpixel((1050, int(0.60 * (height - 1))))) < 700

    luminances = [
        sum(cover.getpixel((1050, y)))
        for y in range(int(0.42 * (height - 1)), height)
    ]
    assert luminances[0] < 765
    assert all(
        later <= earlier for earlier, later in zip(luminances, luminances[1:])
    )


def test_cover_has_no_local_gray_box_and_shows_the_artwork():
    white_art = Image.new("RGB", SUMMARY_SIZE, WHITE)
    white_cover = _render_cover(title=LONG_COVER_TITLE, art=white_art)

    kicker_bbox = _color_bbox(white_cover, (0, 1200, 1080, 1920), BLUE)
    assert kicker_bbox is not None
    title_bbox = _lower_white_bbox(white_cover, kicker_bbox[3])
    assert title_bbox is not None

    row = title_bbox[1] - 4
    row_colors = {
        white_cover.getpixel((x, row)) for x in range(64, 1017)
    }
    assert len(row_colors) == 1

    other_cover = _render_cover(
        title=LONG_COVER_TITLE,
        art=Image.new("RGB", SUMMARY_SIZE, (200, 40, 40)),
    )
    assert other_cover.getpixel((200, row)) != white_cover.getpixel((200, row))


def test_cover_contrast_passes_against_a_worst_case_white_image():
    cover = _render_cover(art=Image.new("RGB", SUMMARY_SIZE, WHITE))

    assert _has_color(cover, (64, 1300, 1014, 1730), WHITE)
    assert sum(cover.getpixel((1050, 1720))) < 250


def test_cover_contrast_failure_is_a_hard_render_error(monkeypatch):
    draft = _draft()
    composition = compose_summary_slides(draft)
    monkeypatch.setattr(
        render_common, "COVER_SCRIM_STOPS", ((0.0, 0.0), (1.0, 0.0))
    )

    with pytest.raises(RenderError, match="contrast"):
        render_summary_frames(
            draft,
            composition,
            cover_art=Image.new("RGB", SUMMARY_SIZE, (10, 10, 10)),
            organ="Gemeinderat Rosdorf",
        )


def test_cover_uses_the_real_square_logo_with_its_white_plate():
    _, _, frames = _render_frames()
    cover = frames[0]

    assert _color_bbox(cover, (40, 200, 520, 520), WHITE) == (
        64,
        240,
        304,
        480,
    )
    # The plate's transparent rounded corner lets the artwork through.
    assert cover.getpixel((65, 241)) != WHITE


def test_cover_composites_a_synthetic_transparent_240px_logo_without_adding_a_plate(
    tmp_path, monkeypatch
):
    _use_transparent_logo(monkeypatch, tmp_path)

    _, _, frames = _render_frames()
    cover = frames[0]

    assert _color_bbox(cover, (40, 200, 520, 500), LOGO_COLOR) == (
        64,
        240,
        304,
        360,
    )
    # The synthetic logo's transparent center shows the artwork; the renderer
    # adds no plate of its own.
    assert cover.getpixel((184, 300)) not in (WHITE, LOGO_COLOR)
    assert not _has_color(cover, (64, 240, 396, 543), WHITE)


def test_card_has_the_blue_edge_profile_card_rule_number_and_page_label():
    _, _, frames = _render_frames()
    card = frames[1]

    assert card.getpixel((70, 1000)) == BLUE
    assert card.getpixel((100, 1000)) == SURFACE_BASE
    assert card.getpixel((540, 1710)) == SURFACE_BASE
    assert card.getpixel((40, 1000)) != SURFACE_BASE
    assert card.getpixel((118, 651)) == OUTLINE
    assert card.getpixel((540, 652)) == OUTLINE
    assert _has_color(card, (118, 460, 320, 590), BLUE)
    assert _has_color(card, (118, 1670, 400, 1700), BLUE)
    assert _has_color(card, (118, 678, 918, 1000), WHITE)


def test_card_uses_the_real_square_logo_with_its_white_plate():
    _, _, frames = _render_frames()
    card = frames[1]

    assert _color_bbox(card, (40, 200, 520, 520), WHITE) == (
        64,
        240,
        176,
        352,
    )
    # The plate's transparent rounded corner lets the card surface through.
    assert card.getpixel((65, 241)) != WHITE


def test_card_composites_a_synthetic_transparent_112px_logo_without_adding_a_plate(
    tmp_path, monkeypatch
):
    _use_transparent_logo(monkeypatch, tmp_path)

    _, _, frames = _render_frames()
    card = frames[1]

    assert _color_bbox(card, (40, 200, 520, 500), LOGO_COLOR) == (
        64,
        240,
        176,
        296,
    )
    assert card.getpixel((120, 268)) not in (WHITE, LOGO_COLOR)
    assert not _has_color(card, (64, 240, 236, 399), WHITE)


def test_badge_and_kicker_have_rounded_corners_with_straight_edge_midpoints():
    _, _, frames = _render_frames()
    cover = frames[0]

    assert cover.getpixel((1015, 260)) != BLUE
    assert cover.getpixel((800, 260)) == BLUE
    assert cover.getpixel((1000, 280)) == BLUE

    kicker_bbox = _color_bbox(cover, (0, 1200, 1080, 1920), BLUE)
    assert kicker_bbox is not None
    kicker_left, kicker_top = kicker_bbox[0], kicker_bbox[1]
    assert cover.getpixel((kicker_left, kicker_top)) != BLUE
    assert cover.getpixel((kicker_left + 3, kicker_top)) != BLUE
    assert cover.getpixel((kicker_left + 10, kicker_top + 2)) == BLUE
    assert cover.getpixel((kicker_left + 136, kicker_top)) == BLUE
    assert cover.getpixel((kicker_left, kicker_top + 32)) == BLUE


def test_card_corners_show_the_background_and_clip_the_blue_edge():
    _, _, frames = _render_frames()
    card = frames[1]

    for corner in ((64, 420), (1015, 420), (64, 1719), (1015, 1719)):
        assert card.getpixel(corner) not in (SURFACE_BASE, BLUE)

    assert card.getpixel((540, 420)) == SURFACE_BASE
    assert card.getpixel((540, 1719)) == SURFACE_BASE
    assert card.getpixel((70, 1000)) == BLUE
    assert card.getpixel((100, 1000)) == SURFACE_BASE
    assert card.getpixel((1015, 1000)) == SURFACE_BASE

    # The 10 px radius is clamped to the card size, not larger.
    assert card.getpixel((74, 420)) == SURFACE_BASE
    assert card.getpixel((67, 420)) != SURFACE_BASE
    assert card.getpixel((64, 434)) == BLUE
    assert card.getpixel((64, 423)) != BLUE

    # The colored edge shares the card mask, so no square blue tip survives.
    for box in ((64, 420, 66, 422), (64, 1718, 66, 1720)):
        region = card.crop(box)
        colors = region.getcolors(maxcolors=region.width * region.height) or []
        assert all(pixel != BLUE for _, pixel in colors)


def test_top_rule_and_card_rule_stay_square():
    _, _, frames = _render_frames()
    cover, card = frames[0], frames[1]

    assert cover.getpixel((0, 0)) == BLUE
    assert cover.getpixel((1079, 5)) == BLUE
    assert card.getpixel((118, 651)) == OUTLINE
    assert card.getpixel((917, 653)) == OUTLINE


def test_body_top_follows_the_heading_line_boxes_plus_38px():
    assert summary_body_top(76, 1) == pytest.approx(798.08)
    assert summary_body_top(76, 2) == pytest.approx(880.16)
    assert summary_body_top(76, 3) == pytest.approx(962.24)
    assert summary_body_top(68, 1) == pytest.approx(789.44)


def test_card_geometry_is_the_approved_952x1300_box():
    assert CARD_BOX == (64, 420, 1016, 1720)
    x0, y0, x1, y1 = CARD_BOX
    assert (x1 - x0, y1 - y0) == (952, 1300)


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
    assert caption.splitlines()[0] == CAPTION_FIRST_LINE
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
    assert text.startswith(f"{CAPTION_FIRST_LINE}\n")
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


def test_card_body_capacity_follows_the_grown_card_bottom():
    draft, composition, _ = _render_frames()
    assert composition.body_size == 42

    def with_body_lines(line_count: int):
        slide = replace(
            composition.slides[1],
            heading_lines=("Test",),
            body_lines=tuple("Zeile" for _ in range(line_count)),
        )
        return replace(
            composition,
            slides=(composition.slides[0], slide, composition.slides[2]),
        )

    # 798.08 body top + 14 * 58.8 = 1621.28, inside the 1640 body bottom.
    frames = render_summary_frames(
        draft,
        with_body_lines(14),
        cover_art=_cover_art(),
        organ="Gemeinderat Rosdorf",
    )
    assert len(frames) == 3

    # 15 lines end at 1680.08 and still overflow the grown card.
    with pytest.raises(RenderError, match="body"):
        render_summary_frames(
            draft,
            with_body_lines(15),
            cover_art=_cover_art(),
            organ="Gemeinderat Rosdorf",
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


def test_empty_logo_is_a_hard_render_failure(monkeypatch, tmp_path):
    draft, composition, _ = _render_frames()
    _use_empty_logo(monkeypatch, tmp_path)

    with pytest.raises(RenderError, match="no visible pixels"):
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
