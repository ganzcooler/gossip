"""Tests for the manual smoke test's retained diagnostics."""

import json

from tests.manual import test_e2e_smoke as smoke


def test_smoke_run_dir_stays_under_the_manual_output_root(monkeypatch, tmp_path):
    monkeypatch.setattr(smoke, "MANUAL_OUTPUT_ROOT", tmp_path)

    run_dir = smoke._smoke_run_dir()

    assert run_dir.parent == tmp_path
    assert run_dir.is_dir()
    assert run_dir.name.count("-") >= 2


def test_smoke_report_records_assets_prompts_and_rejected_files(tmp_path):
    rejected = tmp_path / "rejected" / "summary"
    rejected.mkdir(parents=True)
    (rejected / "cover-attempt-1-rejected.png").write_bytes(b"png")
    (rejected / "cover-attempt-1-rejected.json").write_text(
        "{}", encoding="utf-8"
    )
    result = {
        "protocol_id": 1,
        "plan_status": "ready",
        "processed": True,
        "post_counts": {"draft": 0, "ready": 1, "failed": 0},
    }
    posts = [
        {
            "id": 1,
            "post_type": "summary",
            "slug": "summary",
            "status": "ready",
            "failed_step": None,
            "error": None,
        }
    ]
    details = {
        1: {
            "assets": [
                {
                    "role": "cover",
                    "status": "ready",
                    "error": None,
                    "prompt": "English image prompt",
                    "path": "summary-2024-05-14-story-01.png",
                }
            ]
        }
    }

    report_path = smoke._write_smoke_report(
        tmp_path,
        protocol_id=1,
        result=result,
        posts=posts,
        details=details,
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["result"] == result
    assert report["posts"][0]["slug"] == "summary"
    assert report["assets"][0]["prompt"] == "English image prompt"
    assert report["asset_status_counts"] == {
        "ready": 1,
        "fallback": 0,
        "failed": 0,
    }
    assert report["rejected_files"] == [
        "rejected/summary/cover-attempt-1-rejected.json",
        "rejected/summary/cover-attempt-1-rejected.png",
    ]
