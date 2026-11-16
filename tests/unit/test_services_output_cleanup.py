"""Output cleanup stays scoped to one post's generated files."""

from datetime import date
from types import SimpleNamespace

from app.services.output_cleanup import (
    cleanup_protocol_output,
    cleanup_summary_output,
    cleanup_topic_output,
)


def _protocol() -> SimpleNamespace:
    return SimpleNamespace(session_date=date(2024, 1, 15), title="Gemeinderat")


def _protocol_folder(tmp_path):
    folder = tmp_path / "240115_gemeinderat"
    folder.mkdir()
    return folder


def test_summary_cleanup_removes_only_summary_images_and_caption(tmp_path):
    folder = _protocol_folder(tmp_path)
    summary_cover = folder / "summary-2024-01-15-story-01.png"
    summary_card = folder / "summary-2024-01-15-story-02.png"
    summary_caption = folder / "caption-summary-summary.txt"
    unrelated = folder / "notes.txt"
    other_caption = folder / "caption-topic-haushalt.txt"
    topic_folder = folder / "topic-haushalt"
    topic_folder.mkdir()
    topic_image = topic_folder / "topic-2024-01-15-01.png"
    for path in (
        summary_cover,
        summary_card,
        summary_caption,
        unrelated,
        other_caption,
        topic_image,
    ):
        path.write_text("x", encoding="utf-8")

    removed = cleanup_summary_output(tmp_path, _protocol())

    assert set(removed) == {summary_cover, summary_card, summary_caption}
    assert not summary_cover.exists()
    assert not summary_card.exists()
    assert not summary_caption.exists()
    assert unrelated.exists()
    assert other_caption.exists()
    assert topic_image.exists()


def test_topic_cleanup_removes_only_that_topics_subfolder(tmp_path):
    folder = _protocol_folder(tmp_path)
    summary = folder / "summary-2024-01-15-story-01.png"
    summary.write_text("x", encoding="utf-8")
    haushalt = folder / "topic-haushalt"
    haushalt.mkdir()
    (haushalt / "topic-2024-01-15-01.png").write_text("x", encoding="utf-8")
    radweg = folder / "topic-radweg"
    radweg.mkdir()
    radweg_image = radweg / "topic-2024-01-15-01.png"
    radweg_image.write_text("x", encoding="utf-8")
    unrelated = folder / "keep.txt"
    unrelated.write_text("x", encoding="utf-8")

    removed = cleanup_topic_output(tmp_path, _protocol(), "haushalt")

    assert removed == [haushalt]
    assert not haushalt.exists()
    assert radweg_image.exists()
    assert summary.exists()
    assert unrelated.exists()


def test_topic_cleanup_ignores_unsafe_or_missing_slugs(tmp_path):
    folder = _protocol_folder(tmp_path)
    outside = tmp_path / "topic-outside"
    outside.mkdir()
    unrelated = folder / "keep.txt"
    unrelated.write_text("x", encoding="utf-8")

    assert cleanup_topic_output(tmp_path, _protocol(), "../outside") == []
    assert cleanup_topic_output(tmp_path, _protocol(), "missing") == []
    assert outside.exists()
    assert unrelated.exists()


def test_protocol_cleanup_removes_generated_output_but_keeps_unrelated_files(tmp_path):
    folder = _protocol_folder(tmp_path)
    summary = folder / "summary-2024-01-15-story-01.png"
    caption = folder / "caption-summary-summary.txt"
    stale_topic = folder / "topic-stale"
    stale_topic.mkdir()
    stale_image = stale_topic / "topic-2024-01-15-01.png"
    keep = folder / "keep.txt"
    for path in (summary, caption, stale_image, keep):
        path.write_text("x", encoding="utf-8")

    cleanup_protocol_output(tmp_path, _protocol())

    assert not summary.exists()
    assert not caption.exists()
    assert not stale_topic.exists()
    assert keep.exists()
