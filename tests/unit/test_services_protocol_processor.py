"""
Unit tests for app/services/protocol_processor.py
"""
import pytest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

from app.services.protocol_processor import (
    sanitize_filename,
    save_article_to_file,
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


class TestSaveArticleToFile:
    """Tests for save_article_to_file function."""

    @pytest.fixture
    def mock_article(self):
        """Create a mock article object."""
        article = MagicMock()
        article.ueberschrift = "Test Article Headline"
        article.inhalt = "<p>Test content</p><h2>Section</h2><p>More content.</p>"
        return article

    def test_creates_html_file(self, temp_directory, mock_article):
        """Test that HTML file is created."""
        result = save_article_to_file(mock_article, temp_directory, 1)

        assert result.exists()
        assert result.suffix == ".html"

    def test_filename_contains_index(self, temp_directory, mock_article):
        """Test that filename contains article index."""
        result = save_article_to_file(mock_article, temp_directory, 5)

        assert "05" in result.name

    def test_filename_contains_headline(self, temp_directory, mock_article):
        """Test that filename contains sanitized headline."""
        result = save_article_to_file(mock_article, temp_directory, 1)

        assert "Test_Article" in result.name or "test_article" in result.name.lower()

    def test_file_contains_html_structure(self, temp_directory, mock_article):
        """Test that file contains proper HTML structure."""
        result = save_article_to_file(mock_article, temp_directory, 1)

        content = result.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in content
        assert "<html" in content
        assert "</html>" in content

    def test_file_contains_headline_in_title(self, temp_directory, mock_article):
        """Test that HTML title contains article headline."""
        result = save_article_to_file(mock_article, temp_directory, 1)

        content = result.read_text(encoding="utf-8")
        assert "<title>Test Article Headline</title>" in content

    def test_file_contains_content(self, temp_directory, mock_article):
        """Test that file contains article content."""
        result = save_article_to_file(mock_article, temp_directory, 1)

        content = result.read_text(encoding="utf-8")
        assert "Test content" in content
        assert "Section" in content
        assert "More content" in content

    def test_escapes_html_in_headline(self, temp_directory):
        """Test that HTML special chars in headline are escaped."""
        mock_article = MagicMock()
        mock_article.ueberschrift = "Test <script>alert('xss')</script>"
        mock_article.inhalt = "<p>Content</p>"

        result = save_article_to_file(mock_article, temp_directory, 1)

        content = result.read_text(encoding="utf-8")
        # The script tag should be escaped (not present as raw HTML)
        assert "<script>" not in content
        # Should be HTML escaped entities
        assert "&lt;script&gt;" in content or "&#x27;" in content

    def test_truncates_long_headlines(self, temp_directory):
        """Test that long headlines are truncated in filename."""
        mock_article = MagicMock()
        mock_article.ueberschrift = "A" * 100  # Very long headline
        mock_article.inhalt = "<p>Content</p>"

        result = save_article_to_file(mock_article, temp_directory, 1)

        # Filename should be reasonable length
        assert len(result.name) < 100


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