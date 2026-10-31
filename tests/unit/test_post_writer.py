"""Tests for prompt rendering and article-to-Markdown conversion."""

from app.core import post_prompts
from app.core.post_models import ArticleDraft, ArticleSection
from app.services.post_writer import article_to_markdown


def test_render_prompt_keeps_json_examples_intact():
    prompt = post_prompts.render_prompt(
        post_prompts.SUMMARY_WRITER_PROMPT,
        SUMMARY_BRIEF="{}",
        PROTOCOL_TEXT="Protokoll",
    )

    assert "{{" not in prompt
    assert "}}" not in prompt
    assert '"title":' in prompt
    assert "Protokoll" in prompt


def test_article_to_markdown_includes_sections_and_takeaways():
    article = ArticleDraft(
        title="Das war die Sitzung",
        kicker="SITZUNG KOMPAKT",
        lead="Ein Lead.",
        sections=[
            ArticleSection(heading="Haushalt", paragraphs=["Absatz eins.", "Absatz zwei."])
        ],
        key_takeaways=["Haushalt beschlossen"],
    )

    markdown = article_to_markdown(article)

    assert "# Das war die Sitzung" in markdown
    assert "## Haushalt" in markdown
    assert "Absatz zwei." in markdown
    assert "## Das Wichtigste in Kürze" in markdown
    assert "- Haushalt beschlossen" in markdown
