"""Direct, deterministic tests for the orange 1080x1350 topic renderer."""

from dataclasses import replace
from datetime import date
from types import SimpleNamespace

import pytest
from PIL import Image

from app.core.post_models import TopicDraft
from app.services import render_common
from app.services.caption_writer import CAPTION_FIRST_LINE, compose_caption
from app.services.post_renderer import RenderError
from app.services.slide_composer import (
    TOPIC_COVER_INSET_X,
    compose_topic_slides,
)
from app.services.topic_renderer import (
    CONTENT_TEXT_X_LEFT,
    CONTENT_TEXT_X_RIGHT,
    TOPIC_SIZE,
    render_topic_frames,
    topic_composition_from_stored,
    write_topic_output,
)
from tests.support.render_helpers import (
    LOGO_COLOR,
    color_bbox as _color_bbox,
    use_empty_logo as _use_empty_logo,
    use_transparent_logo as _use_transparent_logo,
)

ORANGE = (233, 79, 35)
ORANGE_DEEP = (201, 62, 24)
SURFACE_BASE = (30, 30, 33)
ON_SURFACE = (255, 255, 255)
OUTLINE = (70, 70, 75)
WHITE = (255, 255, 255)

PAIR_LEFT = (190, 70, 40)
PAIR_RIGHT = (40, 80, 150)
SINGLE_COLOR = (70, 150, 90)


def _paragraph(length: int = 700) -> str:
    seed = (
        "Der Rat hat zu diesem Thema beraten und eine Entscheidung getroffen. "
        "Die Verwaltung setzt die Mittel im Frühjahr um."
    )
    text = ""
    while len(text) < length:
        text = f"{text} {seed}".strip()
    if len(text) > length:
        text = text[:length].rsplit(" ", 1)[0]
    return text.rstrip(" ,;") + "."


def _draft(lengths: tuple[int, ...] = (700, 700)) -> TopicDraft:
    return TopicDraft(
        title="Was der Rat zum Haushalt in Rosdorf entschieden hat",
        sections=[
            {
                "h2": f"Der Rat hat zu Abschnitt {index} ausführlich entschieden",
                "paragraphs": [_paragraph(length)],
            }
            for index, length in enumerate(lengths, start=1)
        ],
    )


def _composition(lengths: tuple[int, ...] = (700, 700)):
    draft = _draft(lengths)
    return draft, compose_topic_slides(draft)


def _cover_art() -> Image.Image:
    return Image.new("RGB", TOPIC_SIZE, (35, 55, 75))


def _pair_art(count: int = 2) -> dict[int, Image.Image]:
    art: dict[int, Image.Image] = {}
    for index in range(1, count + 1):
        image = Image.new("RGB", (720, 1350), PAIR_LEFT)
        image.paste(PAIR_RIGHT, (360, 0, 720, 1350))
        # A unique marker column per pair makes slice mix-ups visible.
        image.paste(
            (10 * index, 20 * index, 30 * index), (350, 0, 370, 1350)
        )
        art[index] = image
    return art


def _single_art() -> Image.Image:
    return Image.new("RGB", (360, 1350), SINGLE_COLOR)


def _render(lengths: tuple[int, ...] = (700, 700)):
    draft, composition = _composition(lengths)
    content_count = len(composition.slides) - 1
    pair_count = content_count // 2
    single = _single_art() if content_count % 2 else None
    frames = render_topic_frames(
        draft,
        composition,
        cover_art=_cover_art(),
        pair_art=_pair_art(pair_count),
        single_art=single,
        organ="Gemeinderat Rosdorf",
    )
    return draft, composition, frames


def _has_color(image: Image.Image, box, color) -> bool:
    region = image.crop(box)
    colors = region.getcolors(maxcolors=region.width * region.height) or []
    return any(pixel == color for _, pixel in colors)


def _render_cover(*, art: Image.Image | None = None) -> Image.Image:
    draft, composition = _composition()
    content_count = len(composition.slides) - 1
    pair_count = content_count // 2
    single = _single_art() if content_count % 2 else None
    return render_topic_frames(
        draft,
        composition,
        cover_art=_cover_art() if art is None else art,
        pair_art=_pair_art(pair_count),
        single_art=single,
        organ="Gemeinderat Rosdorf",
    )[0]


def _lower_white_bbox(cover: Image.Image, top: int):
    return _color_bbox(cover, (0, top, TOPIC_SIZE[0], TOPIC_SIZE[1]), ON_SURFACE)


def _wide_orange_box(cover: Image.Image) -> tuple[int, int, int]:
    """Locate the kicker block by its wide run of the deep orange fill."""
    pixels = cover.load()
    rows = []
    for y in range(400, cover.height):
        xs = [
            x
            for x in range(cover.width)
            if pixels[x, y] == ORANGE_DEEP
        ]
        if len(xs) > 40:
            rows.append((y, min(xs)))
    assert rows
    return min(x for _, x in rows), min(y for y, _ in rows), max(
        y for y, _ in rows
    )


def test_renderer_produces_cover_and_four_content_slides_at_1080x1350_rgb():
    _, composition, frames = _render()

    assert len(composition.slides) == 5
    assert len(frames) == 5
    for frame in frames:
        assert frame.size == TOPIC_SIZE == (1080, 1350)
        assert frame.mode == "RGB"


def test_cover_has_orange_rule_badge_kicker_and_bottom_anchored_title():
    _, _, frames = _render()
    cover = frames[0]

    assert cover.getpixel((540, 2)) == ORANGE
    assert cover.getpixel((1000, 180)) == ORANGE_DEEP
    assert _has_color(cover, (64, 500, 700, 900), ORANGE_DEEP)
    assert _has_color(cover, (44, 700, 54, 1210), ORANGE_DEEP)
    assert _has_color(cover, (64, 1150, 1014, 1201), ON_SURFACE)

    title_bbox = _lower_white_bbox(cover, 600)
    assert title_bbox is not None
    assert abs(title_bbox[3] - 1200) <= 6

    # The title ink bbox ends at y=1200; no white brand/title pixel below it.
    assert not _has_color(cover, (0, 1201, 1080, 1350), ON_SURFACE)


def test_cover_composites_a_transparent_288px_logo_at_the_top_left_without_a_plate(
    tmp_path, monkeypatch
):
    _use_transparent_logo(monkeypatch, tmp_path)

    _, _, frames = _render()
    cover = frames[0]

    assert _color_bbox(cover, (40, 130, 520, 440), LOGO_COLOR) == (
        64,
        150,
        352,
        294,
    )
    assert cover.getpixel((208, 222)) not in (WHITE, LOGO_COLOR)
    assert not _has_color(cover, (64, 150, 456, 507), WHITE)


def test_cover_badge_kicker_and_accent_bar_have_rounded_corners():
    _, _, frames = _render()
    cover = frames[0]

    assert cover.getpixel((1015, 160)) != ORANGE_DEEP
    assert cover.getpixel((800, 160)) == ORANGE_DEEP
    assert cover.getpixel((1000, 180)) == ORANGE_DEEP

    kicker_rows = [
        y for y in range(cover.height) if cover.getpixel((100, y)) == ORANGE_DEEP
    ]
    kicker_top, kicker_bottom = min(kicker_rows), max(kicker_rows)
    assert cover.getpixel((64, kicker_top)) != ORANGE_DEEP
    assert cover.getpixel((200, kicker_top)) == ORANGE_DEEP
    assert cover.getpixel((64, kicker_top + 32)) == ORANGE_DEEP
    assert cover.getpixel((64, kicker_bottom)) != ORANGE_DEEP

    # The accent bar is 10 px wide, so the 10 px token is clamped to 5 px.
    # The tip rows still carry fill at the bar midpoint; a pill would not.
    accent_rows = [
        y for y in range(cover.height) if cover.getpixel((49, y)) == ORANGE_DEEP
    ]
    accent_top, accent_bottom = min(accent_rows), max(accent_rows)
    assert cover.getpixel((49, accent_top)) == ORANGE_DEEP
    assert cover.getpixel((49, accent_bottom)) == ORANGE_DEEP
    assert cover.getpixel((44, accent_top)) != ORANGE_DEEP
    assert cover.getpixel((44, accent_bottom)) != ORANGE_DEEP
    accent_middle = (accent_top + accent_bottom) // 2
    assert cover.getpixel((44, accent_middle)) == ORANGE_DEEP
    assert cover.getpixel((53, accent_middle)) == ORANGE_DEEP


def test_top_rule_heading_rule_hairline_and_image_edge_stay_square():
    _, _, frames = _render()
    cover, first, second = frames[0], frames[1], frames[2]

    assert cover.getpixel((0, 0)) == ORANGE
    assert cover.getpixel((1079, 5)) == ORANGE
    assert first.getpixel((710, 0)) == ORANGE_DEEP
    assert first.getpixel((719, 0)) == ORANGE_DEEP
    assert first.getpixel((710, 1349)) == ORANGE_DEEP
    assert first.getpixel((719, 1349)) == ORANGE_DEEP
    assert first.getpixel((60, 236)) == ORANGE
    assert first.getpixel((659, 238)) == ORANGE
    assert second.getpixel((420, 135)) == OUTLINE
    assert second.getpixel((1019, 135)) == OUTLINE


def test_inset_cover_title_keeps_the_kicker_on_the_same_left_edge():
    # The long compound word does not fit the normal 930px column, so the
    # composer uses the x=48 inset title fallback.
    title = "Der Rat beschließt die Haushaltskonsolidierungskonzeption"
    draft = TopicDraft(
        title=title,
        sections=[
            {
                "h2": "Der Rat hat zu Abschnitt 1 ausführlich entschieden",
                "paragraphs": [_paragraph(700)],
            },
            {
                "h2": "Der Rat hat zu Abschnitt 2 ausführlich entschieden",
                "paragraphs": [_paragraph(700)],
            },
        ],
    )
    composition = compose_topic_slides(draft)
    cover_plan = composition.slide_plan["cover"]
    assert cover_plan["title_x"] == TOPIC_COVER_INSET_X

    content_count = len(composition.slides) - 1
    pair_count = content_count // 2
    cover = render_topic_frames(
        draft,
        composition,
        cover_art=_cover_art(),
        pair_art=_pair_art(pair_count),
        single_art=_single_art() if content_count % 2 else None,
        organ="Gemeinderat Rosdorf",
    )[0]

    kicker_left, _, kicker_bottom = _wide_orange_box(cover)
    title_bbox = _lower_white_bbox(cover, kicker_bottom + 2)
    assert title_bbox is not None
    assert TOPIC_COVER_INSET_X <= kicker_left <= TOPIC_COVER_INSET_X + 8
    assert title_bbox[0] == kicker_left


def test_cover_has_no_local_gray_box_and_shows_the_artwork():
    white_art = Image.new("RGB", TOPIC_SIZE, ON_SURFACE)
    white_cover = _render_cover(art=white_art)

    kicker_bbox = _color_bbox(white_cover, (60, 600, 1080, 1350), ORANGE_DEEP)
    assert kicker_bbox is not None
    title_bbox = _lower_white_bbox(white_cover, kicker_bbox[3])
    assert title_bbox is not None

    row = title_bbox[1] - 4
    row_colors = {
        white_cover.getpixel((x, row)) for x in range(64, 1017)
    }
    assert len(row_colors) == 1

    other_cover = _render_cover(
        art=Image.new("RGB", TOPIC_SIZE, (200, 40, 40))
    )
    assert other_cover.getpixel((200, row)) != white_cover.getpixel((200, row))


def test_cover_has_a_single_bottom_up_scrim_with_a_transparent_top():
    height = TOPIC_SIZE[1]
    cover = _render_cover(art=Image.new("RGB", TOPIC_SIZE, ON_SURFACE))

    assert cover.getpixel((1050, 100)) == ON_SURFACE
    assert cover.getpixel((1050, int(0.35 * (height - 1)))) == ON_SURFACE

    assert sum(cover.getpixel((1050, int(0.60 * (height - 1))))) < 700

    luminances = [
        sum(cover.getpixel((1050, y)))
        for y in range(int(0.42 * (height - 1)), height)
    ]
    assert luminances[0] < 765
    assert all(
        later <= earlier for earlier, later in zip(luminances, luminances[1:])
    )


def test_cover_contrast_passes_against_a_worst_case_white_image():
    cover = _render_cover(art=Image.new("RGB", TOPIC_SIZE, ON_SURFACE))

    assert _has_color(cover, (64, 900, 1014, 1201), ON_SURFACE)
    assert sum(cover.getpixel((1050, 1200))) < 250


def test_cover_contrast_failure_is_a_hard_render_error(monkeypatch):
    draft, composition = _composition()
    monkeypatch.setattr(
        render_common, "COVER_SCRIM_STOPS", ((0.0, 0.0), (1.0, 0.0))
    )

    with pytest.raises(RenderError, match="contrast"):
        render_topic_frames(
            draft,
            composition,
            cover_art=Image.new("RGB", TOPIC_SIZE, (10, 10, 10)),
            pair_art=_pair_art(2),
            organ="Gemeinderat Rosdorf",
        )


def test_heading_slide_geometry_zigzag_edge_and_image_side():
    _, _, frames = _render()
    first = frames[1]

    assert first.getpixel((715, 600)) == ORANGE_DEEP
    assert first.getpixel((800, 600)) == PAIR_LEFT
    assert first.getpixel((400, 600)) == SURFACE_BASE
    assert _has_color(first, (60, 90, 260, 190), ORANGE)
    assert first.getpixel((60, 236)) == ORANGE
    assert first.getpixel((659, 238)) == ORANGE
    assert _has_color(first, (60, 263, 660, 430), ON_SURFACE)
    assert _has_color(first, (60, 447, 660, 1000), (226, 223, 216))


def test_even_content_slide_flips_zigzag_and_edge_to_the_left():
    _, _, frames = _render()
    second = frames[2]

    assert second.getpixel((365, 600)) == ORANGE_DEEP
    assert second.getpixel((100, 600)) == PAIR_RIGHT
    assert second.getpixel((800, 600)) == SURFACE_BASE
    assert _has_color(second, (420, 90, 1020, 140), ON_SURFACE)
    assert _has_color(second, (900, 90, 1020, 140), ORANGE)
    assert second.getpixel((420, 135)) == OUTLINE
    assert second.getpixel((1019, 135)) == OUTLINE


def test_pair_slices_concatenate_to_the_processed_720x1350_artwork():
    _, _, frames = _render()
    pair = _pair_art()[1]

    combined = Image.new("RGB", (720, 1350))
    combined.paste(frames[1].crop((720, 0, 1080, 1350)), (0, 0))
    combined.paste(frames[2].crop((0, 0, 360, 1350)), (360, 0))

    assert combined.tobytes() == pair.tobytes()
    assert frames[1].getpixel((1079, 675)) == pair.getpixel((359, 675))
    assert frames[2].getpixel((0, 675)) == pair.getpixel((360, 675))


def test_unpaired_last_slide_uses_the_standalone_strip_without_a_seam():
    draft, composition, frames = _render((700, 700, 150))
    content_count = len(composition.slides) - 1
    assert content_count == 5

    last = frames[-1]
    assert last.getpixel((800, 675)) == SINGLE_COLOR
    assert last.getpixel((1079, 675)) == SINGLE_COLOR
    # It is not the final pair's right half (which is PAIR_RIGHT).
    assert last.getpixel((800, 675)) != PAIR_RIGHT
    assert last.getpixel((715, 675)) == ORANGE_DEEP
    assert last.getpixel((400, 675)) == SURFACE_BASE


def test_every_content_slide_has_a_transparent_footer_logo_right_aligned_to_the_column(
    tmp_path, monkeypatch
):
    _use_transparent_logo(monkeypatch, tmp_path)

    _, _, frames = _render()
    for frame_index in (1, 2):
        frame = frames[frame_index]
        text_x = CONTENT_TEXT_X_LEFT if frame_index == 1 else CONTENT_TEXT_X_RIGHT
        expected = (text_x + 496, 1110, text_x + 600, 1162)
        assert (
            _color_bbox(
                frame, (text_x + 400, 1080, text_x + 620, 1220), LOGO_COLOR
            )
            == expected
        )
        assert frame.getpixel((text_x + 548, 1136)) not in (
            WHITE,
            LOGO_COLOR,
        )
        assert not _has_color(
            frame, (text_x + 438, 1110, text_x + 600, 1260), WHITE
        )


def test_heading_and_continuation_share_one_body_size_and_body_zone():
    _, composition, frames = _render()

    assert composition.body_size in (42, 39, 36)
    heading = composition.slides[1]
    continuation = composition.slides[2]
    assert heading.slide_type == "heading"
    assert continuation.slide_type == "continuation"
    assert heading.body_size == continuation.body_size == composition.body_size
    assert heading.heading_zone in (160, 204)
    assert continuation.heading_lines == ()
    assert composition.slides[1].content_position == 1
    assert composition.slides[2].content_position == 2


def test_counter_systems_render_the_content_number_and_chapter_counter():
    _, _, frames = _render()
    heading = frames[1]
    continuation = frames[2]

    # The heading shows a large orange two-digit number at the left text x.
    assert _has_color(heading, (CONTENT_TEXT_X_LEFT, 90, 260, 200), ORANGE)
    # The continuation shows a right-aligned orange n/N counter at the column
    # right edge; its glyphs are much smaller than the heading number.
    assert _has_color(
        continuation,
        (CONTENT_TEXT_X_RIGHT + 500, 90, CONTENT_TEXT_X_RIGHT + 600, 140),
        ORANGE,
    )
    # No second page number at the bottom.
    assert heading.getpixel((100, 1300)) == SURFACE_BASE
    assert continuation.getpixel((500, 1300)) == SURFACE_BASE


def test_stored_slide_plan_and_slides_reconstruct_the_render_composition():
    draft, composition, _ = _render()
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

    restored = topic_composition_from_stored(
        draft, composition.slide_plan, stored_slides
    )

    assert restored.body_size == composition.body_size
    assert restored.cover_title_size == composition.cover_title_size
    assert [slide.content_position for slide in restored.slides[1:]] == [
        slide.content_position for slide in composition.slides[1:]
    ]
    assert [slide.body_lines for slide in restored.slides[1:]] == [
        slide.body_lines for slide in composition.slides[1:]
    ]
    assert restored.slides[0].headline == draft.title


def test_write_topic_output_creates_exact_filenames_and_one_caption(tmp_path):
    draft, composition, frames = _render()
    caption = compose_caption(
        body="Der Rat hat wichtige Entscheidungen getroffen.",
        organ="Gemeinderat Rosdorf",
        session_date=date(2024, 3, 12),
        protocol=SimpleNamespace(getfile_id=4711),
        base_url="https://sessionnet.example/rosdorf/BI/",
    )
    post = SimpleNamespace(caption=caption, slug="haushalt")
    protocol = SimpleNamespace(
        session_date=date(2024, 3, 12), title="Gemeinderat"
    )

    output = write_topic_output(
        frames, post=post, protocol=protocol, output_dir=tmp_path
    )

    folder = tmp_path / "240312_gemeinderat" / "topic-haushalt"
    assert output.folder == folder
    assert sorted(path.name for path in folder.iterdir()) == [
        "caption-topic-haushalt.txt",
        "topic-2024-03-12-01.png",
        "topic-2024-03-12-02.png",
        "topic-2024-03-12-03.png",
        "topic-2024-03-12-04.png",
        "topic-2024-03-12-05.png",
    ]
    assert output.image_paths == [
        folder / f"topic-2024-03-12-{index:02d}.png"
        for index in range(1, 6)
    ]
    assert output.caption_path == folder / "caption-topic-haushalt.txt"
    assert output.caption_path.read_text(encoding="utf-8") == caption
    assert caption.splitlines()[0] == CAPTION_FIRST_LINE
    assert "12.03.2024" in caption
    assert "https://sessionnet.example/rosdorf/BI/getfile.asp?id=4711" in caption
    for path in output.image_paths:
        with Image.open(path) as image:
            assert image.size == TOPIC_SIZE
            assert image.mode == "RGB"

    again = write_topic_output(
        frames, post=post, protocol=protocol, output_dir=tmp_path
    )
    assert sorted(path.name for path in again.folder.iterdir()) == sorted(
        path.name for path in folder.iterdir()
    )


def test_write_topic_output_removes_stale_topic_frames_and_rejects_missing_caption(
    tmp_path,
):
    draft, composition, frames = _render()
    caption = compose_caption(
        body="Caption",
        organ="Gemeinderat Rosdorf",
        session_date=date(2024, 3, 12),
        protocol=SimpleNamespace(getfile_id=4711),
    )
    post = SimpleNamespace(caption=caption, slug="haushalt")
    protocol = SimpleNamespace(
        session_date=date(2024, 3, 12), title="Gemeinderat"
    )
    folder = tmp_path / "240312_gemeinderat" / "topic-haushalt"
    folder.mkdir(parents=True)
    (folder / "topic-2024-03-12-09.png").write_bytes(b"stale")
    other = tmp_path / "240312_gemeinderat" / "topic-other"
    other.mkdir()
    (other / "topic-2024-03-12-01.png").write_bytes(b"other topic")

    output = write_topic_output(
        frames, post=post, protocol=protocol, output_dir=tmp_path
    )

    assert not (folder / "topic-2024-03-12-09.png").exists()
    assert (other / "topic-2024-03-12-01.png").read_bytes() == b"other topic"
    assert len(output.image_paths) == 5

    with pytest.raises(RenderError, match="caption"):
        write_topic_output(
            frames,
            post=SimpleNamespace(caption=None, slug="haushalt"),
            protocol=protocol,
            output_dir=tmp_path,
        )


def test_overlong_body_is_a_render_failure_not_truncation():
    draft, composition, _ = _render()
    broken = replace(
        composition.slides[2],
        body_lines=tuple("W" * 40 for _ in range(80)),
        body_paragraphs=(tuple("W" * 40 for _ in range(80)),),
    )
    composition = replace(
        composition,
        slides=(composition.slides[0], composition.slides[1], broken, *composition.slides[3:]),
    )

    with pytest.raises(RenderError, match="body"):
        render_topic_frames(
            draft,
            composition,
            cover_art=_cover_art(),
            pair_art=_pair_art(2),
            organ="Gemeinderat Rosdorf",
        )


def test_missing_pair_art_is_a_render_failure():
    draft, composition = _composition()

    with pytest.raises(RenderError, match="pair"):
        render_topic_frames(
            draft,
            composition,
            cover_art=_cover_art(),
            pair_art={1: _pair_art()[1]},
            organ="Gemeinderat Rosdorf",
        )


def test_missing_logo_is_a_hard_render_failure(monkeypatch):
    draft, composition = _composition()
    monkeypatch.setattr(
        render_common, "LOGO_PATH", render_common.RESOURCE_DIR / "missing-logo.png"
    )

    with pytest.raises(RenderError, match="logo"):
        render_topic_frames(
            draft,
            composition,
            cover_art=_cover_art(),
            pair_art=_pair_art(2),
            organ="Gemeinderat Rosdorf",
        )


def test_empty_logo_is_a_hard_render_failure(monkeypatch, tmp_path):
    draft, composition = _composition()
    _use_empty_logo(monkeypatch, tmp_path)

    with pytest.raises(RenderError, match="no visible pixels"):
        render_topic_frames(
            draft,
            composition,
            cover_art=_cover_art(),
            pair_art=_pair_art(2),
            organ="Gemeinderat Rosdorf",
        )


def test_missing_font_is_a_hard_render_failure(monkeypatch):
    draft, composition = _composition()
    monkeypatch.setitem(
        render_common.FONT_PATHS,
        "oswald",
        render_common.RESOURCE_DIR / "missing-font.ttf",
    )

    with pytest.raises(RenderError, match="font"):
        render_topic_frames(
            draft,
            composition,
            cover_art=_cover_art(),
            pair_art=_pair_art(2),
            organ="Gemeinderat Rosdorf",
        )
