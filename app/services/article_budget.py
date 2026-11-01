"""Article length and format budgets for the deterministic slide pipeline."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.post_models import ArticleDraft


@dataclass(frozen=True)
class ArticleBudget:
    min_words: int
    max_words: int
    min_sections: int
    max_sections: int
    max_chars: int

    def as_dict(self) -> dict:
        return {
            "min_words": self.min_words,
            "max_words": self.max_words,
            "min_sections": self.min_sections,
            "max_sections": self.max_sections,
            "max_chars": self.max_chars,
        }


SUMMARY_BUDGET = ArticleBudget(
    min_words=500,
    max_words=650,
    min_sections=4,
    max_sections=6,
    max_chars=5000,
)
TOPIC_BUDGET = ArticleBudget(
    min_words=350,
    max_words=450,
    min_sections=3,
    max_sections=4,
    max_chars=3200,
)


def budget_for_post_type(post_type) -> ArticleBudget:
    value = getattr(post_type, "value", post_type)
    return SUMMARY_BUDGET if value == "summary" else TOPIC_BUDGET


def article_text(article: ArticleDraft) -> str:
    parts = [article.lead]
    for section in article.sections:
        parts.extend(section.paragraphs)
    return " ".join(parts)


def article_word_count(article: ArticleDraft) -> int:
    return len(article_text(article).split())


def validate_article_budget(
    article: ArticleDraft, budget: ArticleBudget
) -> list[str]:
    errors: list[str] = []
    words = article_word_count(article)
    chars = len(article_text(article))
    if not article.title.strip():
        errors.append("Titel (H1) fehlt")
    if not (budget.min_words <= words <= budget.max_words):
        errors.append(
            f"Wortzahl {words} liegt außerhalb von "
            f"{budget.min_words}-{budget.max_words}"
        )
    if chars > budget.max_chars:
        errors.append(
            f"Zeichenzahl {chars} überschreitet das Maximum {budget.max_chars}"
        )
    if not (budget.min_sections <= len(article.sections) <= budget.max_sections):
        errors.append(
            f"H2-Anzahl {len(article.sections)} liegt außerhalb von "
            f"{budget.min_sections}-{budget.max_sections}"
        )
    return errors
