from pydantic import BaseModel
from typing import List, Optional


class SingleArticle(BaseModel):
    """Model for a single generated article."""
    ueberschrift: str
    inhalt: str


class LLMGeneratedArticles(BaseModel):
    """Model for the LLM response containing multiple articles."""
    artikel: List[SingleArticle]


class ContentBlock(BaseModel):
    """Model for a content block in an article."""
    headline: Optional[str] = None
    paragraph: Optional[str] = None


class ArticleContent(BaseModel):
    """Model for extracted article content."""
    h1: str | None
    content_blocks: List[ContentBlock]
