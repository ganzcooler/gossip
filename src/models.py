from pydantic import BaseModel
from typing import List

class SingleArticle(BaseModel):
    ueberschrift: str
    inhalt: str

class LLMGeneratedArticles(BaseModel):
    artikel: List[SingleArticle]
