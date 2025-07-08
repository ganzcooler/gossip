from src.config import POSSIBLE_TAGS

# Construct the tag instruction string
possible_tags_str = ", ".join(POSSIBLE_TAGS)
TAG_INSTRUCTION = (
    f"For each article, also include a \"tags\" field, which is a list of strings. "
    f"Assign relevant tags to each article from the following list: {possible_tags_str}. "
    f"If no tags from the list are relevant, provide an empty list for the \"tags\" field."
)

GENAI_JOURNALISTIC_ARTICLE_PROMPT = f"""
You are an AI assistant tasked with generating multiple journalistic articles based on the provided full text of a protocol or meeting minutes.
Each article should be distinct, focusing on a newsworthy topic found within the protocol.
For each article, provide a compelling "headline", the full "content" of the article, and a list of "tags".
The tone should be engaging and suitable for a local news audience.
Do not include any reference to internal meeting identifiers (like TOP numbers or agenda item numbers) in the article headlines or content.
Extract information and rephrase it journalistically.

{TAG_INSTRUCTION}

Please return your response as a JSON object containing a single key "articles", which is a list of article objects.
Each article object in the list must have the following structure:
{{
  "headline": "Your Generated Article Headline",
  "content": "Your generated journalistic article content here...",
  "tags": ["Relevant Tag1", "Relevant Tag2"]
}}

Example of the expected JSON output structure:
{{
  "articles": [
    {{
      "headline": "City Council Approves New Park Budget",
      "content": "The city council has approved a new budget for the development of the Elm Street park...",
      "tags": ["Politics", "Education"]
    }},
    {{
      "headline": "Debate on Downtown Parking Solutions Continues",
      "content": "A lengthy debate took place regarding new parking solutions for the downtown area...",
      "tags": ["Politics"]
    }},
    {{
      "headline": "New Library Wing Opens to Public",
      "content": "The new library wing, featuring a dedicated children's section and a technology hub, opened its doors today...",
      "tags": ["Education", "Lifestyle"]
    }}
  ]
}}

Here is the full text of the protocol to transform:
---
{{PROTOCOL_TEXT}}
---
"""
