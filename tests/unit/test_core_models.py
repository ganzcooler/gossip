"""
Unit tests for app/core/models.py
"""
import pytest
from pydantic import ValidationError

from app.core.models import SingleArticle, LLMGeneratedArticles, ContentBlock, ArticleContent


class TestSingleArticle:
    """Tests for SingleArticle model."""

    def test_valid_single_article(self):
        """Test creating a valid SingleArticle."""
        article = SingleArticle(
            ueberschrift="Test Headline",
            inhalt="<p>Test content</p>"
        )
        assert article.ueberschrift == "Test Headline"
        assert article.inhalt == "<p>Test content</p>"

    def test_single_article_missing_required_fields(self):
        """Test that missing required fields raise ValidationError."""
        with pytest.raises(ValidationError):
            SingleArticle(ueberschrift="Test Headline")
        
        with pytest.raises(ValidationError):
            SingleArticle(inhalt="<p>Test content</p>")

    def test_single_article_empty_strings(self):
        """Test that empty strings are accepted (Pydantic doesn't validate content)."""
        article = SingleArticle(ueberschrift="", inhalt="")
        assert article.ueberschrift == ""
        assert article.inhalt == ""

    def test_single_article_with_html_content(self):
        """Test SingleArticle with complex HTML content."""
        html_content = """
        <h2>Section 1</h2>
        <p>This is paragraph 1.</p>
        <h2>Section 2</h2>
        <p>This is paragraph 2 with <strong>bold</strong> text.</p>
        """
        article = SingleArticle(
            ueberschrift="Complex Article",
            inhalt=html_content
        )
        assert "<h2>" in article.inhalt
        assert "<strong>" in article.inhalt


class TestLLMGeneratedArticles:
    """Tests for LLMGeneratedArticles model."""

    def test_valid_llm_generated_articles(self):
        """Test creating valid LLMGeneratedArticles."""
        articles = LLMGeneratedArticles(
            artikel=[
                SingleArticle(ueberschrift="Article 1", inhalt="<p>Content 1</p>"),
                SingleArticle(ueberschrift="Article 2", inhalt="<p>Content 2</p>"),
            ]
        )
        assert len(articles.artikel) == 2
        assert articles.artikel[0].ueberschrift == "Article 1"
        assert articles.artikel[1].ueberschrift == "Article 2"

    def test_empty_article_list(self):
        """Test LLMGeneratedArticles with empty list."""
        articles = LLMGeneratedArticles(artikel=[])
        assert articles.artikel == []

    def test_missing_artikel_field(self):
        """Test that missing artikel field raises ValidationError."""
        with pytest.raises(ValidationError):
            LLMGeneratedArticles()


class TestContentBlock:
    """Tests for ContentBlock model."""

    def test_content_block_with_both_fields(self):
        """Test ContentBlock with headline and paragraph."""
        block = ContentBlock(
            headline="Test Headline",
            paragraph="Test paragraph content."
        )
        assert block.headline == "Test Headline"
        assert block.paragraph == "Test paragraph content."

    def test_content_block_headline_only(self):
        """Test ContentBlock with only headline."""
        block = ContentBlock(headline="Test Headline")
        assert block.headline == "Test Headline"
        assert block.paragraph is None

    def test_content_block_paragraph_only(self):
        """Test ContentBlock with only paragraph."""
        block = ContentBlock(paragraph="Test paragraph content.")
        assert block.headline is None
        assert block.paragraph == "Test paragraph content."

    def test_content_block_empty(self):
        """Test ContentBlock with no fields."""
        block = ContentBlock()
        assert block.headline is None
        assert block.paragraph is None


class TestArticleContent:
    """Tests for ArticleContent model."""

    def test_article_content_with_all_fields(self):
        """Test ArticleContent with all fields."""
        content = ArticleContent(
            h1="Main Title",
            content_blocks=[
                ContentBlock(headline="Section 1", paragraph="Content 1"),
                ContentBlock(headline="Section 2", paragraph="Content 2"),
            ]
        )
        assert content.h1 == "Main Title"
        assert len(content.content_blocks) == 2

    def test_article_content_no_h1(self):
        """Test ArticleContent without h1."""
        content = ArticleContent(
            h1=None,
            content_blocks=[ContentBlock(paragraph="Content only")]
        )
        assert content.h1 is None
        assert len(content.content_blocks) == 1

    def test_article_content_empty_blocks(self):
        """Test ArticleContent with empty content_blocks."""
        content = ArticleContent(
            h1="Title",
            content_blocks=[]
        )
        assert content.content_blocks == []

    def test_article_content_missing_required_field(self):
        """Test that missing content_blocks raises ValidationError."""
        with pytest.raises(ValidationError):
            ArticleContent(h1="Title")