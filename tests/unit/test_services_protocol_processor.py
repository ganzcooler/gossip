"""
Unit tests for app/services/protocol_processor.py
"""
import pytest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

from app.services.protocol_processor import (
    sanitize_filename,
    save_image_to_file,
)


class TestSanitizeFilename:
    """Tests for sanitize_filename function."""

    def test_replaces_spaces_with_underscores(self):
        """Test that spaces are replaced with underscores."""
        result = sanitize_filename("test file name")
        assert " " not in result
        assert "_" in result
        assert result == "test_file_name"

    def test_removes_special_characters(self):
        """Test that special characters are removed."""
        result = sanitize_filename("test@#$%^&*()file")
        assert "@" not in result
        assert "#" not in result
        assert "$" not in result

    def test_keeps_allowed_characters(self):
        """Test that allowed characters are preserved."""
        result = sanitize_filename("test-file_name.txt")
        assert "test-file_name.txt" == result

    def test_removes_multiple_underscores(self):
        """Test that multiple consecutive underscores are reduced."""
        result = sanitize_filename("test___file____name")
        assert "___" not in result
        assert "____" not in result

    def test_strips_leading_trailing_special_chars(self):
        """Test that leading/trailing special chars are stripped."""
        result = sanitize_filename("._-test-file-_.")
        assert not result.startswith(".")
        assert not result.startswith("_")
        assert not result.startswith("-")
        assert not result.endswith(".")
        assert not result.endswith("_")
        assert not result.endswith("-")

    def test_handles_empty_string(self):
        """Test handling of empty string."""
        result = sanitize_filename("")
        assert result == ""

    def test_handles_only_special_chars(self):
        """Test handling of string with only special characters."""
        result = sanitize_filename("@#$%^&*")
        assert result == ""

    def test_preserves_unicode_letters(self):
        """Test that unicode letters are preserved."""
        result = sanitize_filename("München Köln")
        assert "München" in result or "muenchen" in result.lower()


class TestSaveImageToFile:
    """Tests for save_image_to_file function."""

    def test_creates_png_file(self, temp_directory):
        """Test that PNG file is created."""
        image_bytes = b"\x89PNG\r\n\x1a\n"  # PNG magic bytes

        result = save_image_to_file(image_bytes, temp_directory, 1)

        assert result.exists()
        assert result.suffix == ".png"

    def test_filename_contains_index(self, temp_directory):
        """Test that filename contains article index."""
        image_bytes = b"fake image data"

        result = save_image_to_file(image_bytes, temp_directory, 7)

        assert "07" in result.name

    def test_filename_with_suffix(self, temp_directory):
        """Test that suffix is added to filename."""
        image_bytes = b"fake image data"

        result = save_image_to_file(image_bytes, temp_directory, 1, suffix="_main")

        assert "_main" in result.name

    def test_saves_correct_content(self, temp_directory):
        """Test that correct bytes are saved."""
        image_bytes = b"\x89PNG\r\n\x1a\nfake image content"

        result = save_image_to_file(image_bytes, temp_directory, 1)

        saved_content = result.read_bytes()
        assert saved_content == image_bytes
