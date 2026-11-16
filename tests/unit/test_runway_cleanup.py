"""Regression tests for the ticket 01 runway cleanup.

These tests protect the repository hygiene decisions: no remote CI, local
pre-commit quality gates, and no lingering imports or routes for the removed
one-call pipeline.
"""

import importlib.util
from pathlib import Path

import pytest
import yaml

from app.main import app


REPO_ROOT = Path(__file__).resolve().parents[2]

REMOVED_MODULES = [
    "app.services.article_generator",
    "app.services.caption_generator",
    "app.services.image_generator",
    "app.services.insta_generator",
    "app.services.insta_job",
    "app.services.protocol_processor",
]


class TestRepositoryHygiene:
    """Tests for removed GitHub Actions and local pre-commit setup."""

    def test_github_actions_workflows_are_gone(self):
        """No GitHub Actions workflows should remain in the repository."""
        assert not (REPO_ROOT / ".github" / "workflows").exists()

    def test_pre_commit_config_exists(self):
        """The local pre-commit configuration must exist."""
        assert (REPO_ROOT / ".pre-commit-config.yaml").is_file()

    def test_pre_commit_uses_only_local_system_hooks(self):
        """Hooks must be local and use the active environment."""
        config = yaml.safe_load((REPO_ROOT / ".pre-commit-config.yaml").read_text())

        repos = config["repos"]
        assert [repo["repo"] for repo in repos] == ["local"]

        hooks = repos[0]["hooks"]
        assert hooks
        for hook in hooks:
            assert hook["language"] == "system"
            assert hook["pass_filenames"] is False

    def test_pre_commit_defines_ruff_and_pytest_hooks(self):
        """Ruff runs on commit and the standard test suite runs before push."""
        config = yaml.safe_load((REPO_ROOT / ".pre-commit-config.yaml").read_text())
        hooks = {hook["id"]: hook for hook in config["repos"][0]["hooks"]}

        assert "ruff" in hooks
        assert hooks["ruff"]["entry"].startswith("ruff check")
        assert "pre-commit" in hooks["ruff"]["stages"]

        assert "pytest" in hooks
        assert 'pytest -m "not manual"' in hooks["pytest"]["entry"]
        assert "pre-push" in hooks["pytest"]["stages"]


class TestRemovedPipelineModules:
    """Tests that the legacy one-call pipeline cannot be imported."""

    @pytest.mark.parametrize("module_name", REMOVED_MODULES)
    def test_removed_module_is_not_importable(self, module_name):
        assert importlib.util.find_spec(module_name) is None

    def test_services_package_no_longer_exports_removed_jobs(self):
        import app.services

        assert not hasattr(app.services, "process_protocols_job")
        assert not hasattr(app.services, "generate_insta_images_job")


class TestRetainedApiSurface:
    """Tests for the interim API surface."""

    def _paths(self):
        return app.openapi()["paths"]

    @pytest.mark.parametrize(
        "path",
        [
            "/api/health",
            "/api/protocols",
            "/api/protocols/{protocol_id}/articles",
            "/api/stats",
            "/api/pipeline/fetch",
            "/api/pipeline/status",
        ],
    )
    def test_retained_endpoint_exists(self, path):
        assert path in self._paths()

    @pytest.mark.parametrize(
        "path",
        [
            "/api/pipeline/process",
            "/api/pipeline/run",
            "/api/pipeline/generate-insta",
        ],
    )
    def test_removed_endpoint_is_gone(self, path):
        assert path not in self._paths()
