"""Final output manifest for one protocol folder.

Only the assets referenced by the database plus the current captions belong in
the reader-facing output folder. Everything else is a temporary artifact.
"""

from __future__ import annotations

import re
from pathlib import Path

_SAFE_SLUG = re.compile(r"[^a-z0-9_-]+")


def _caption_filename(post_index: int, slug: str) -> str:
    safe_slug = _SAFE_SLUG.sub("-", slug.lower()).strip("-") or "post"
    return f"caption_{post_index:02d}_{safe_slug}.txt"


def cleanup_protocol_output(
    folder: Path,
    captions: list[tuple[int, str, str]],
    allowed_files: list[Path],
) -> list[Path]:
    """Write current captions and delete every unreferenced file.

    ``allowed_files`` must come from the persisted ``PostAsset`` rows. This
    makes the cleanup independent of filename conventions and removes stale
    artwork or slide files from earlier runs.
    """
    folder.mkdir(parents=True, exist_ok=True)
    allowed = {
        (Path(path) if Path(path).is_absolute() else folder / path).resolve()
        for path in allowed_files
    }

    for post_index, slug, caption in captions:
        if not caption or not caption.strip():
            continue
        caption_path = folder / _caption_filename(post_index, slug)
        caption_path.write_text(caption.strip(), encoding="utf-8")
        allowed.add(caption_path.resolve())

    removed: list[Path] = []
    for path in sorted(folder.iterdir()):
        if not path.is_file():
            continue
        if path.resolve() in allowed:
            continue
        path.unlink()
        removed.append(path)
    return removed
