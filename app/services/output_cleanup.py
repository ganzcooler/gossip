"""Safe cleanup of generated files for force-retry and protocol reprocess.

Only the Summary files in the protocol folder and a topic's own
``topic-<slug>/`` subfolder are touched. Unrelated files, other topics and a
path-traversal slug are left alone.
"""

from __future__ import annotations

import re
import shutil
from datetime import date
from pathlib import Path
from typing import Any

from app.utils.folder_utils import protocol_folder_path

_SLUG_PATTERN = re.compile(r"^[a-z0-9-]+$")


def _protocol_folder(output_dir: Path | str, protocol: Any) -> Path | None:
    session_date = getattr(protocol, "session_date", None)
    title = getattr(protocol, "title", None)
    if not isinstance(session_date, date) or not title:
        return None
    return protocol_folder_path(output_dir, session_date, str(title))


def _summary_files(folder: Path) -> list[Path]:
    return sorted(
        path
        for path in folder.iterdir()
        if path.is_file()
        and (
            (path.name.startswith("summary-") and path.suffix == ".png")
            or path.name.startswith("caption-summary-")
        )
    )


def cleanup_summary_output(
    output_dir: Path | str, protocol: Any
) -> list[Path]:
    """Delete only Summary images and Summary caption files for a protocol."""
    folder = _protocol_folder(output_dir, protocol)
    if folder is None or not folder.is_dir():
        return []
    removed: list[Path] = []
    for path in _summary_files(folder):
        path.unlink(missing_ok=True)
        removed.append(path)
    return removed


def cleanup_topic_output(
    output_dir: Path | str, protocol: Any, slug: str
) -> list[Path]:
    """Delete only one topic's ``topic-<slug>/`` subfolder."""
    value = str(slug or "").strip()
    if not _SLUG_PATTERN.fullmatch(value):
        return []
    folder = _protocol_folder(output_dir, protocol)
    if folder is None or not folder.is_dir():
        return []
    topic_folder = folder / f"topic-{value}"
    if not topic_folder.is_dir() or topic_folder.is_symlink():
        return []
    shutil.rmtree(topic_folder)
    return [topic_folder]


def cleanup_protocol_output(
    output_dir: Path | str, protocol: Any
) -> list[Path]:
    """Delete all generated output for a protocol during reprocess.

    Summary files and every generated ``topic-*`` subfolder are removed.
    Unrelated files in the protocol folder are never touched.
    """
    removed = cleanup_summary_output(output_dir, protocol)
    folder = _protocol_folder(output_dir, protocol)
    if folder is None or not folder.is_dir():
        return removed
    for path in sorted(folder.iterdir()):
        if (
            path.is_dir()
            and not path.is_symlink()
            and path.name.startswith("topic-")
        ):
            shutil.rmtree(path)
            removed.append(path)
    return removed


__all__ = [
    "cleanup_protocol_output",
    "cleanup_summary_output",
    "cleanup_topic_output",
]
