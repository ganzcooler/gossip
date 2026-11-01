"""Tests for article budgets and deterministic slide distribution."""

from app.core.post_models import ArticleDraft, ArticleSection
from app.services.article_budget import TOPIC_BUDGET, validate_article_budget
from app.services.slide_distributor import build_summary_slides, build_topic_slides


def _article(section_text: str = "Der Ortsrat hat eine Entscheidung getroffen. Die Verwaltung prüft die nächsten Schritte."):
    return ArticleDraft(
        title="Testtitel",
        kicker="THEMA IM FOKUS",
        lead="Ein kurzer Lead.",
        sections=[
            ArticleSection(heading="Beschluss", paragraphs=[section_text]),
            ArticleSection(heading="Hintergrund", paragraphs=[section_text]),
            ArticleSection(heading="Ausblick", paragraphs=[section_text]),
        ],
        key_takeaways=["Nicht auf die Slides"],
    )


def test_article_budget_reports_section_and_word_problems():
    errors = validate_article_budget(_article(), TOPIC_BUDGET)
    assert any("Wortzahl" in error for error in errors)
    assert not any("H2-Anzahl" in error for error in errors)


def test_topic_distribution_preserves_text_and_pairs():
    article = _article()
    plan = build_topic_slides(article)

    assert len(plan.pairs) >= 1
    assert all(len(pair.slides) == 2 for pair in plan.pairs)
    distributed = " ".join(
        slide.body for pair in plan.pairs for slide in pair.slides
    )
    expected = " ".join(
        [article.lead] + [p for section in article.sections for p in section.paragraphs]
    )
    assert " ".join(distributed.split()) == " ".join(expected.split())
    assert all("Nicht auf die Slides" not in slide.body for pair in plan.pairs for slide in pair.slides)


def test_summary_distribution_preserves_text():
    article = _article()
    plan = build_summary_slides(article)
    distributed = " ".join(slide.body for slide in plan.slides)
    expected = " ".join(
        [article.lead] + [p for section in article.sections for p in section.paragraphs]
    )
    assert " ".join(distributed.split()) == " ".join(expected.split())
    assert len(plan.slides) <= 7
