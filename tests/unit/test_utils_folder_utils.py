"""
Unit tests for app/utils/folder_utils.py
"""
import pytest
from datetime import date
from pathlib import Path
import re

from app.utils.folder_utils import create_protocol_folder, ensure_directories


class TestCreateProtocolFolder:
    """Tests for create_protocol_folder function."""

    def test_creates_folder_with_correct_format(self, temp_directory):
        """Test that folder is created with correct naming format."""
        base_dir = temp_directory / "articles"
        session_date = date(2024, 1, 15)
        title = "Test Protocol"

        result = create_protocol_folder(base_dir, session_date, title)

        # Check folder exists
        assert result.exists()
        assert result.is_dir()

        # Check naming format: YYMMDD_normalized_title
        expected_prefix = "240115_"
        assert result.name.startswith(expected_prefix)

    def test_normalizes_umlauts(self, temp_directory):
        """Test that umlauts are properly normalized."""
        base_dir = temp_directory / "articles"
        session_date = date(2024, 1, 15)
        title = "München Ärger Über Öffentlichkeit"

        result = create_protocol_folder(base_dir, session_date, title)

        # Check umlauts are replaced
        assert "ue" in result.name.lower() or "ae" in result.name.lower() or "oe" in result.name.lower()
        assert "ü" not in result.name
        assert "ä" not in result.name
        assert "ö" not in result.name

    def test_replaces_spaces_with_underscores(self, temp_directory):
        """Test that spaces are replaced with underscores."""
        base_dir = temp_directory / "articles"
        session_date = date(2024, 1, 15)
        title = "Test Protocol Title"

        result = create_protocol_folder(base_dir, session_date, title)

        assert " " not in result.name
        assert "_" in result.name

    def test_converts_to_lowercase(self, temp_directory):
        """Test that folder name is lowercase."""
        base_dir = temp_directory / "articles"
        session_date = date(2024, 1, 15)
        title = "UPPERCASE TITLE"

        result = create_protocol_folder(base_dir, session_date, title)

        # Name after date prefix should be lowercase
        name_after_prefix = result.name[7:]  # Skip YYMMDD_
        assert name_after_prefix == name_after_prefix.lower()

    def test_removes_special_characters(self, temp_directory):
        """Test that special characters are removed."""
        base_dir = temp_directory / "articles"
        session_date = date(2024, 1, 15)
        title = "Test@#$%^&*()Protocol!"

        result = create_protocol_folder(base_dir, session_date, title)

        # Only alphanumeric and underscore allowed after date prefix
        name_after_prefix = result.name[7:]
        assert re.match(r'^[a-z0-9_]+$', name_after_prefix)

    def test_truncates_long_titles(self, temp_directory):
        """Test that long titles are truncated to 80 characters."""
        base_dir = temp_directory / "articles"
        session_date = date(2024, 1, 15)
        title = "A" * 200  # Very long title

        result = create_protocol_folder(base_dir, session_date, title)

        # Name after date prefix should be max 80 chars
        name_after_prefix = result.name[7:]
        assert len(name_after_prefix) <= 80

    def test_raises_error_if_folder_exists(self, temp_directory):
        """Test that FileExistsError is raised if folder already exists."""
        base_dir = temp_directory / "articles"
        base_dir.mkdir(parents=True, exist_ok=True)
        session_date = date(2024, 1, 15)
        title = "Test Protocol"

        # Create folder first time
        create_protocol_folder(base_dir, session_date, title)

        # Second attempt should raise error
        with pytest.raises(FileExistsError):
            create_protocol_folder(base_dir, session_date, title)

    def test_handles_esszet(self, temp_directory):
        """Test that ß is properly converted to ss."""
        base_dir = temp_directory / "articles"
        session_date = date(2024, 1, 15)
        title = "Straße Größe"

        result = create_protocol_folder(base_dir, session_date, title)

        assert "ß" not in result.name
        assert "ss" in result.name.lower()


class TestEnsureDirectories:
    """Tests for ensure_directories function."""

    def test_creates_single_directory(self, temp_directory):
        """Test creating a single directory."""
        test_dir = temp_directory / "test_dir"

        ensure_directories([test_dir])

        assert test_dir.exists()
        assert test_dir.is_dir()

    def test_creates_multiple_directories(self, temp_directory):
        """Test creating multiple directories."""
        dirs = [
            temp_directory / "dir1",
            temp_directory / "dir2",
            temp_directory / "dir3",
        ]

        ensure_directories(dirs)

        for d in dirs:
            assert d.exists()
            assert d.is_dir()

    def test_handles_nested_paths(self, temp_directory):
        """Test creating nested directory paths."""
        nested_dir = temp_directory / "parent" / "child" / "grandchild"

        ensure_directories([nested_dir])

        assert nested_dir.exists()
        assert nested_dir.is_dir()

    def test_handles_existing_directories(self, temp_directory):
        """Test that existing directories don't cause errors."""
        existing_dir = temp_directory / "existing"
        existing_dir.mkdir()

        # Should not raise error
        ensure_directories([existing_dir])

        assert existing_dir.exists()

    def test_empty_list(self, temp_directory):
        """Test that empty list doesn't cause errors."""
        # Should not raise error
        ensure_directories([])