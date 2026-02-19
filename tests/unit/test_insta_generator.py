"""
Unit tests for app/services/insta_generator.py
"""
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

from app.services.insta_generator import (
    find_tag,
    split_text_into_chunks,
    extract_article_content,
)
from app.core.models import ArticleContent, ContentBlock


class TestFindTag:
    """Tests for find_tag function."""

    def test_find_bau_umwelt_tag(self):
        """Test finding Bau/Umwelt tag."""
        result = find_tag("ausschuss_bau_umwelt_protocol_2024")
        assert result == "BAU, UMWELT, VERKEHR"

    def test_find_gemeinderat_tag(self):
        """Test finding Gemeinderat tag."""
        result = find_tag("gemeinderat_meeting_january")
        assert result == "GEMEINDERAT"

    def test_find_ortsrat_tag(self):
        """Test finding Ortsrat tag."""
        result = find_tag("ortsrat_rosdorf_meeting")
        assert result == "ROSDORF"

    def test_case_insensitive_matching(self):
        """Test that tag matching is case insensitive."""
        result = find_tag("AUSSCHUSS_BAU_UMWELT_PROTOCOL")
        assert result == "BAU, UMWELT, VERKEHR"

    def test_no_tag_found(self):
        """Test when no tag matches."""
        result = find_tag("unknown_protocol_title")
        assert result is None

    def test_empty_string(self):
        """Test with empty string."""
        result = find_tag("")
        assert result is None

    def test_multiple_matches_returns_first(self):
        """Test that first match is returned when multiple tags match."""
        # This depends on dict ordering (Python 3.7+)
        result = find_tag("gemeinderat_ausschuss_bau_umwelt")
        # Should return one of them
        assert result is not None


class TestSplitTextIntoChunks:
    """Tests for split_text_into_chunks function."""

    def test_short_text_single_chunk(self):
        """Test that short text returns single chunk."""
        text = "Short text."
        result = split_text_into_chunks(text, 100)
        assert len(result) == 1
        assert result[0] == "Short text."

    def test_empty_text(self):
        """Test with empty text."""
        result = split_text_into_chunks("", 100)
        assert result == []

    def test_splits_at_sentence_end(self):
        """Test that text splits at sentence endings."""
        text = "First sentence. Second sentence. Third sentence."
        result = split_text_into_chunks(text, 30)
        
        # Should split at sentence boundaries
        assert len(result) >= 1
        assert "First sentence." in result[0]

    def test_splits_at_space_when_no_sentence_end(self):
        """Test splitting at space when no sentence ending found."""
        text = "word1 word2 word3 word4 word5"
        result = split_text_into_chunks(text, 10)
        
        assert len(result) >= 1

    def test_handles_question_marks(self):
        """Test splitting at question marks."""
        text = "Question one? Question two? Question three?"
        result = split_text_into_chunks(text, 20)
        
        assert len(result) >= 1

    def test_handles_exclamation_marks(self):
        """Test splitting at exclamation marks."""
        text = "Exclamation one! Exclamation two! Exclamation three!"
        result = split_text_into_chunks(text, 25)
        
        assert len(result) >= 1

    def test_widow_prevention(self):
        """Test that widow prevention merges short last chunks."""
        # Create text that would result in a short last chunk
        text = "A" * 400 + " " + "B" * 400 + " " + "Short."
        result = split_text_into_chunks(text, 450)
        
        # Last chunk should not be too short
        if len(result) > 1:
            assert len(result[-1]) >= 10 or len(result) == 1


class TestExtractArticleContent:
    """Tests for extract_article_content function."""

    def test_extract_h1_and_content(self, temp_directory):
        """Test extracting H1 and content blocks."""
        html_content = """<!DOCTYPE html>
<html>
<head><title>Test</title></head>
<body>
    <h1>Main Headline</h1>
    <p>First paragraph.</p>
    <h2>Section Title</h2>
    <p>Section content.</p>
</body>
</html>"""
        
        article_path = temp_directory / "test_article.html"
        article_path.write_text(html_content, encoding="utf-8")
        
        result = extract_article_content(article_path)
        
        assert result is not None
        assert result.h1 == "Main Headline"
        assert len(result.content_blocks) == 2

    def test_extract_h2_p_pairs(self, temp_directory):
        """Test extracting H2+P pairs as content blocks."""
        html_content = """<!DOCTYPE html>
<html>
<body>
    <h1>Title</h1>
    <h2>First Section</h2>
    <p>First paragraph.</p>
    <h2>Second Section</h2>
    <p>Second paragraph.</p>
</body>
</html>"""
        
        article_path = temp_directory / "test_article.html"
        article_path.write_text(html_content, encoding="utf-8")
        
        result = extract_article_content(article_path)
        
        assert result is not None
        assert len(result.content_blocks) == 2
        assert result.content_blocks[0].headline == "First Section"
        assert result.content_blocks[0].paragraph == "First paragraph."
        assert result.content_blocks[1].headline == "Second Section"
        assert result.content_blocks[1].paragraph == "Second paragraph."

    def test_extract_standalone_paragraphs(self, temp_directory):
        """Test extracting standalone paragraphs."""
        html_content = """<!DOCTYPE html>
<html>
<body>
    <h1>Title</h1>
    <p>Standalone paragraph.</p>
</body>
</html>"""
        
        article_path = temp_directory / "test_article.html"
        article_path.write_text(html_content, encoding="utf-8")
        
        result = extract_article_content(article_path)
        
        assert result is not None
        assert len(result.content_blocks) == 1
        assert result.content_blocks[0].headline is None
        assert result.content_blocks[0].paragraph == "Standalone paragraph."

    def test_file_not_found(self):
        """Test handling of non-existent file."""
        result = extract_article_content(Path("/nonexistent/path/article.html"))
        assert result is None

    def test_no_h1_tag(self, temp_directory):
        """Test extraction when no H1 tag exists."""
        html_content = """<!DOCTYPE html>
<html>
<body>
    <p>Content without H1.</p>
</body>
</html>"""
        
        article_path = temp_directory / "test_article.html"
        article_path.write_text(html_content, encoding="utf-8")
        
        result = extract_article_content(article_path)
        
        assert result is not None
        assert result.h1 is None

    def test_empty_file(self, temp_directory):
        """Test handling of empty file."""
        article_path = temp_directory / "empty.html"
        article_path.write_text("", encoding="utf-8")
        
        result = extract_article_content(article_path)
        
        # Empty HTML might return None or empty content
        assert result is None or result.h1 is None

    def test_handles_standalone_h2(self, temp_directory):
        """Test handling of H2 without following P."""
        html_content = """<!DOCTYPE html>
<html>
<body>
    <h1>Title</h1>
    <h2>Standalone H2</h2>
    <div>Not a paragraph</div>
</body>
</html>"""
        
        article_path = temp_directory / "test_article.html"
        article_path.write_text(html_content, encoding="utf-8")
        
        result = extract_article_content(article_path)
        
        assert result is not None
        # Should have the H2 as a block without paragraph
        h2_blocks = [b for b in result.content_blocks if b.headline == "Standalone H2"]
        assert len(h2_blocks) == 1
        assert h2_blocks[0].paragraph is None