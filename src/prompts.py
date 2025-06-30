GENAI_JOURNALISTIC_ARTICLE_PROMPT = """
You are an AI assistant tasked with generating multiple journalistic articles based on the provided full text of a protocol or meeting minutes.
Each article should be distinct, focusing on a newsworthy topic found within the protocol.
For each article, provide a compelling "headline" and the full "content" of the article.
The tone should be engaging and suitable for a local news audience.
Do not include any reference to internal meeting identifiers (like TOP numbers or agenda item numbers) in the article headlines or content.
Extract information and rephrase it journalistically.

Please return your response as a JSON object containing a single key "articles", which is a list of article objects.
Each article object in the list must have the following structure:
{{
  "headline": "Your Generated Article Headline",
  "content": "Your generated journalistic article content here..."
}}

Example of the expected JSON output structure:
{{
  "articles": [
    {{
      "headline": "City Council Approves New Park Budget",
      "content": "The city council has approved a new budget for the development of the Elm Street park..."
    }},
    {{
      "headline": "Debate on Downtown Parking Solutions Continues",
      "content": "A lengthy debate took place regarding new parking solutions for the downtown area..."
    }}
  ]
}}

Here is the full text of the protocol to transform:
---
{PROTOCOL_TEXT}
---
"""

GENAI_TOPIC_SELECTION_PROMPT = """
You are an AI assistant. Your task is to evaluate a list of TOPs (Tagesordnungspunkte / agenda items) from a given protocol (meeting minutes) and decide for each TOP whether it is suitable for a journalistic article.
Base your decision on two main criteria:
1.  **Content Depth**: The TOP should provide enough substantial material for a compelling news story. Purely administrative points, very brief announcements, or items lacking detail are generally not suitable.
2.  **Public Interest/Engagement**: The TOP should offer opportunities to be presented in a way that is likely to engage a broader audience. This might include topics that are emotional, controversial, impactful on the community, or generally sensational.

You will be provided with input in JSON format, containing the protocol's 'title', 'datum' (date), and a 'tops' field. The 'tops' field will be a list of strings, where each string is the content of a TOP.

You must return a JSON object with the original 'title' and 'datum' fields from the input. Additionally, your output must include a field named 'tops_evaluation', which should be a list. This list must contain an entry for *every* TOP present in the input's 'tops' list. Each entry in 'tops_evaluation' must include an 'original_index' (the 0-based index of the TOP in the input 'tops' list), a boolean field 'is_selected_relevant' (true if suitable for an article, false otherwise), and a 'content_preview' (the first few words of the TOP's content for easy reference).

Here are a couple of examples:

**Example 1:**

Input:
```json
{
  "title": "Finance Committee Meeting",
  "datum": "2024-03-15",
  "tops": [
    "Approval of the minutes from the last meeting. The minutes were reviewed and approved without changes.",
    "Budget reallocation proposal for Q3. This involves shifting funds from the deferred park renovation project to the emergency road repair fund due to recent storm damage. Extensive discussion on the urgency and impact on other planned projects. Several local businesses voiced concerns over the park project delay.",
    "Update on software licensing renewals. Standard renewal process, no issues reported."
  ]
}
```

Output:
```json
{
  "title": "Finance Committee Meeting",
  "datum": "2024-03-15",
  "tops_evaluation": [
    {
      "original_index": 0,
      "content_preview": "Approval of the minutes from the last meeting...",
      "is_selected_relevant": false
    },
    {
      "original_index": 1,
      "content_preview": "Budget reallocation proposal for Q3. This involves shifting funds...",
      "is_selected_relevant": true
    },
    {
      "original_index": 2,
      "content_preview": "Update on software licensing renewals. Standard renewal process...",
      "is_selected_relevant": false
    }
  ]
}
```

**Example 2:**

Input:
```json
{
  "title": "School Board Session",
  "datum": "2024-03-18",
  "tops": [
    "Presentation of the new anti-bullying campaign 'Safe Spaces Now'. Includes detailed plans for student workshops, parent information evenings, and teacher training modules. Statistics on bullying incidents from the past year were presented, showing a concerning rise. Discussion included a heartfelt testimony from a parent whose child was affected.",
    "Decision on the vendor for cafeteria supplies for the next school year. Three bids were reviewed, and Vendor X was selected based on cost and compliance with nutritional guidelines. Standard procurement procedure."
  ]
}
```

Output:
```json
{
  "title": "School Board Session",
  "datum": "2024-03-18",
  "tops_evaluation": [
    {
      "original_index": 0,
      "content_preview": "Presentation of the new anti-bullying campaign 'Safe Spaces Now'...",
      "is_selected_relevant": true
    },
    {
      "original_index": 1,
      "content_preview": "Decision on the vendor for cafeteria supplies for the next school year...",
      "is_selected_relevant": false
    }
  ]
}
```
Now, evaluate the following input:
"""

PDF_EXTRACTION_PROMPT = """
        Du bist ein KI-Assistent.
        Extrahiere die Tagesordnungspunkte mitsamt deren Inhalt aus dem PDF-Dokument und gib sie im JSON-Format zurück.
        In "tops" soll eine Liste der Inhalte der einzelnen Tagesordnungspunkte stehen. Jeder Eintrag in der Liste ist ein String, der die Überschrift und den Inhalt des jeweiligen Tagesordnungspunktes enthält.
        In "datum" soll das Datum des Protokolls im Format "YYYY-MM-DD" stehen.
        In "title" soll der Titel des Ausschusses oder der Sitzung stehen, z.B. "Jugendausschuss".

        Hier ein Beispiel für das JSON-Format:
        {
          "title": "Jugendausschuss",
          "datum": "2023-10-01",
          "tops": [
            "Erster Tagesordnungspunkt Inhalt, der sehr spannend ist und viele Details bietet.",
            "Zweiter Tagesordnungspunkt Inhalt, eher administrativ."
          ]
        }
        """
