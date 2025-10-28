from pydantic import BaseModel
from typing import List, Optional

class SingleArticle(BaseModel):
    ueberschrift: str
    inhalt: str

class LLMGeneratedArticles(BaseModel):
    artikel: List[SingleArticle]

class ContentBlock(BaseModel):
    headline: Optional[str] = None
    paragraph: Optional[str] = None

class ArticleContent(BaseModel):
    h1: str | None
    content_blocks: List[ContentBlock]