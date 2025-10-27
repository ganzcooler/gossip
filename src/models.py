from pydantic import BaseModel
from typing import List

class SingleArticle(BaseModel):
    ueberschrift: str
    inhalt: str

class LLMGeneratedArticles(BaseModel):
    artikel: List[SingleArticle]

class H2Section(BaseModel):
    headline: str
    paragraphs: List[str]

class ArticleContent(BaseModel):
    h1: str | None
    h2_sections: List[H2Section]
