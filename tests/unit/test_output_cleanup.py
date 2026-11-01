"""Tests for the final protocol output manifest."""

from pathlib import Path

from app.services.output_cleanup import cleanup_protocol_output


def _touch(path: Path) -> Path:
    path.write_text("x", encoding="utf-8")
    return path


def test_cleanup_keeps_referenced_assets_and_writes_captions(tmp_path):
    allowed = [
        _touch(tmp_path / "summary_cover_source.png"),
        _touch(tmp_path / "summary_cover.jpg"),
        _touch(tmp_path / "summary_slide_01.jpg"),
        _touch(tmp_path / "topic_01_cover_source.png"),
        _touch(tmp_path / "topic_01_artwork_01_source.png"),
        _touch(tmp_path / "topic_01_cover.jpg"),
        _touch(tmp_path / "topic_01_slide_01.jpg"),
    ]
    stale = [
        _touch(tmp_path / "editorial_plan.json"),
        _touch(tmp_path / "summary.md"),
        _touch(tmp_path / "artwork_01_prompt.txt"),
        _touch(tmp_path / "run.log"),
        _touch(tmp_path / "caption_99_old.txt"),
        _touch(tmp_path / "topic_01_slide_99.jpg"),
    ]

    removed = cleanup_protocol_output(
        tmp_path,
        [(1, "pavillon", "Der Ortsrat hat den Pavillon erhalten.")],
        allowed,
    )

    assert all(path.exists() for path in allowed)
    assert all(not path.exists() for path in stale)
    assert {path.name for path in removed} == {path.name for path in stale}

    caption = tmp_path / "caption_01_pavillon.txt"
    assert caption.read_text(encoding="utf-8") == "Der Ortsrat hat den Pavillon erhalten."
