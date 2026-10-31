"""Prompts for the two-post pipeline.

Every prompt is a single, fresh-context task. Placeholders use ``{NAME}`` and
are filled with plain ``str.replace`` so JSON examples can keep their braces.
"""

def render_prompt(template: str, **values: str) -> str:
    """Fill a prompt template without leaking JSON braces.

    The templates use doubled braces around JSON examples, so ``str.format``
    is the right tool: it turns ``{{`` into ``{`` and leaves the inserted
    values untouched.
    """

    return template.format(STYLE_GUIDE=STYLE_GUIDE, **values)


STYLE_GUIDE = """
Ton und Haltung:
- Deutsch, sachlich, informativ und locker formuliert.
- Keine Ironie, keine Sarkasmus, keine Wertung, keine reißerischen Fragen.
- Keine Namen von Personen. Verwende Rollen wie "die Verwaltung", "ein Ratsmitglied", "die Opposition".
- Nur Fakten aus dem Protokoll. Erfinde keine Zahlen, Daten, Zitate oder Hintergründe.
- Kurze, klare Sätze. Erkläre Fachbegriffe, wenn sie für Leser ohne Verwaltungswissen nötig sind.
- Schreibe für interessierte Bürger, nicht für Verwaltungsfachleute.
- Die Sitzungsbezeichnung (z. B. "Ortsrat Obernjesa", "Gemeinderat Rosdorf") gehört nicht in Titel, Headlines oder Kicker. Sie wird im Cover-Badge angezeigt.
""".strip()


EDITORIAL_PLAN_PROMPT = """
Du bist Redaktionsplaner für einen lokalen Nachrichtenkanal. Deine Aufgabe ist es, aus einem Ratsprotokoll die redaktionell interessanten Inhalte auszuwählen.

{STYLE_GUIDE}

Aufgabe:
1. Bestimme den Fokus für eine Zusammenfassung der gesamten Sitzung.
2. Bestimme null bis fünf Themen für eigenständige Themenbeiträge.
3. Leite die Sitzungsbezeichnung aus dem Protokoll ab und klassifiziere sie kurz, z. B. "Ortsrat Obernjesa", "Gemeinderat Rosdorf" oder "Jugendausschuss".

Regeln für die Zusammenfassung:
- Wähle die drei bis sieben wichtigsten Punkte für die Leser.
- Der Fokus soll in einem Satz beschreiben, worum es in der Sitzung im Kern ging.
- Der Arbeitstitel soll neutral und konkret sein, keine Frage und kein Clickbait.

Regeln für Themen:
- Die Anzahl richtet sich nach der Substanz und dem Leserinteresse, nicht nach der Länge des Protokolls.
- Lieber wenige starke Themen als viele schwache. Wenn das Protokoll nichts Leserrelevantes enthält, gib eine leere Themenliste zurück.
- Ein Thema muss genug Stoff für einen eigenständigen Artikel haben: Beschluss, Debatte, Hintergrund, Auswirkung oder nächster Schritt.
- Keine Themen, die nur aus einem Tagesordnungspunkt ohne Inhalt bestehen.
- `protocol_anchors` enthält kurze wörtliche Zitate oder präzise Abschnittsbezeichnungen aus dem Protokoll, damit der Themenautor die relevanten Stellen findet.
- `slug` ist kleingeschrieben, ASCII, mit Bindestrichen, z. B. "windpark-vertagung".
- `session_label` ist die konkrete Sitzungsbezeichnung aus dem Protokoll, keine Person und kein Datum. Wenn keine eindeutige Bezeichnung erkennbar ist, nutze "Gemeinderat Rosdorf".

Antworte ausschließlich mit gültigem JSON in diesem Format:
{{
  "session_label": "Ortsrat Obernjesa",
  "summary": {{
    "working_title": "Neutraler Arbeitstitel",
    "focus": "Ein Satz zum Kern der Sitzung",
    "key_points": ["Punkt 1", "Punkt 2", "Punkt 3"]
  }},
  "topics": [
    {{
      "slug": "thema-slug",
      "working_title": "Neutraler Arbeitstitel",
      "focus": "Worum es in diesem Thema geht",
      "why_relevant": "Warum das für Leser interessant ist",
      "protocol_anchors": ["Kurzes Zitat oder Abschnittsbezeichnung"]
    }}
  ]
}}

Protokoll:
{PROTOCOL_TEXT}
""".strip()


SUMMARY_WRITER_PROMPT = """
Du bist Journalist für einen lokalen Nachrichtenkanal. Schreibe einen vollständigen Artikel, der die gesamte Ratssitzung für interessierte Bürger zusammenfasst.

{STYLE_GUIDE}

Wichtig:
- Schreibe den vollständigen Artikeltext. Denke nicht an Slides, Bildanzahl oder Zeichenlimits. Die visuelle Verdichtung übernimmt ein späterer, separater Schritt.
- Der Artikel muss für sich allein lesbar sein.
- Erkläre bei jedem wichtigen Punkt: Was wurde entschieden oder besprochen? Warum ist das wichtig? Was passiert als Nächstes?
- Priorisiere die Punkte, die den Alltag der Bürger betreffen.
- Lass unwichtige Verfahrensdetails weg.
- Wenn das Protokoll eine Information nicht enthält, schreibe sie nicht.

Struktur:
- `title`: neutrale, konkrete Überschrift, maximal 80 Zeichen.
- `kicker`: immer "SITZUNG KOMPAKT".
- `lead`: ein bis zwei Sätze, die den Kern der Sitzung zusammenfassen.
- `sections`: drei bis sieben Abschnitte. Jeder Abschnitt hat eine kurze Überschrift und ein bis drei Absätze.
- `key_takeaways`: drei bis sieben kurze Kernaussagen.

Länge: So lang wie nötig, typischerweise 500 bis 900 Wörter. Keine künstliche Kürzung.

Antworte ausschließlich mit gültigem JSON in diesem Format:
{{
  "title": "Neutrale Überschrift",
  "kicker": "SITZUNG KOMPAKT",
  "lead": "Ein bis zwei Sätze.",
  "sections": [
    {{"heading": "Kurze Überschrift", "paragraphs": ["Absatz 1", "Absatz 2"]}}
  ],
  "key_takeaways": ["Kernaussage 1", "Kernaussage 2"]
}}

Redaktionsbrief:
{SUMMARY_BRIEF}

Protokoll:
{PROTOCOL_TEXT}
""".strip()


TOPIC_WRITER_PROMPT = """
Du bist Journalist für einen lokalen Nachrichtenkanal. Schreibe einen vollständigen Artikel zu genau einem Thema aus einer Ratssitzung.

{STYLE_GUIDE}

Wichtig:
- Schreibe den vollständigen Artikeltext. Denke nicht an Slides, Bildanzahl oder Zeichenlimits. Die visuelle Verdichtung übernimmt ein späterer, separater Schritt.
- Bleibe beim Thema. Andere Tagesordnungspunkte sind nur relevant, wenn sie für dieses Thema unmittelbar notwendig sind.
- Erkläre: Was ist passiert? Was wurde beschlossen? Warum ist das wichtig? Welche Argumente gab es? Was passiert als Nächstes?
- Wenn das Protokoll eine Information nicht enthält, schreibe sie nicht.
- Keine Spekulation über Motive oder Hintergründe, die nicht im Protokoll stehen.

Struktur:
- `title`: neutrale, konkrete Überschrift, maximal 80 Zeichen.
- `kicker`: immer "THEMA IM FOKUS".
- `lead`: ein bis zwei Sätze, die den Kern des Themas zusammenfassen.
- `sections`: drei bis sechs Abschnitte. Jeder Abschnitt hat eine kurze Überschrift und ein bis drei Absätze.
- `key_takeaways`: drei bis sechs kurze Kernaussagen.

Länge: So lang wie nötig, typischerweise 600 bis 1100 Wörter. Keine künstliche Kürzung.

Antworte ausschließlich mit gültigem JSON in diesem Format:
{{
  "title": "Neutrale Überschrift",
  "kicker": "THEMA IM FOKUS",
  "lead": "Ein bis zwei Sätze.",
  "sections": [
    {{"heading": "Kurze Überschrift", "paragraphs": ["Absatz 1", "Absatz 2"]}}
  ],
  "key_takeaways": ["Kernaussage 1", "Kernaussage 2"]
}}

Redaktionsbrief:
{TOPIC_BRIEF}

Protokoll:
{PROTOCOL_TEXT}
""".strip()


FACT_CHECK_PROMPT = """
Du bist ein strenger Faktenprüfer für einen lokalen Nachrichtenkanal. Vergleiche den Artikel mit dem Protokoll.

{STYLE_GUIDE}

Prüfe jede Tatsachenbehauptung:
- Steht sie so im Protokoll?
- Sind Zahlen, Daten, Beträge und Namen korrekt?
- Wurden Fakten erfunden, verdreht oder aus dem Zusammenhang gerissen?
- Wird eine Person namentlich genannt? Das ist immer ein Problem.
- Gibt es Ironie, Wertung, Clickbait oder reißerische Fragen?
- Gibt es Widersprüche im Artikel selbst?

Melde nur echte Fehler, keine Stilwünsche und keine korrekten Aussagen. Die Liste `issues` enthält ausschließlich Aussagen, die du als falsch, unbelegt, irreführend oder unzulässig einstufst. Korrekte Aussagen und Überlegungen gehören nicht in die Liste. Wenn du keinen klaren Fehler findest, gib `issues: []` und `verdict: "ok"` zurück. Setze `verdict` auf `"needs_repair"`, sobald mindestens ein echter Fehler in `issues` steht. Maximal zehn Einträge; halte `problem` kurz und konkret.

Antworte ausschließlich mit gültigem JSON in diesem Format:
{{
  "issues": [
    {{
      "claim": "Die problematische Aussage",
      "problem": "Was daran falsch oder unzulässig ist",
      "evidence": "Kurzes Zitat aus dem Protokoll oder 'nicht im Protokoll'"
    }}
  ],
  "verdict": "ok"
}}

Artikel:
{ARTICLE_JSON}

Protokoll:
{PROTOCOL_TEXT}
""".strip()


REPAIR_ARTICLE_PROMPT = """
Du bist Journalist und Lektor für einen lokalen Nachrichtenkanal. Überarbeite den folgenden Artikel so, dass alle gemeldeten Probleme behoben sind.

{STYLE_GUIDE}

Regeln:
- Behalte die guten Teile und die Struktur bei.
- Entferne oder korrigiere alle unbelegten Aussagen.
- Entferne alle Personennamen.
- Neutralisiere Ironie, Wertung und Clickbait.
- Erfinde keine neuen Fakten. Nutze nur das Protokoll.
- Gib den vollständigen korrigierten Artikel zurück, nicht nur die geänderten Stellen.

Antworte ausschließlich mit gültigem JSON im selben Format wie der Ausgangsartikel:
{{
  "title": "Neutrale Überschrift",
  "kicker": "SITZUNG KOMPAKT oder THEMA IM FOKUS",
  "lead": "Ein bis zwei Sätze.",
  "sections": [
    {{"heading": "Kurze Überschrift", "paragraphs": ["Absatz 1"]}}
  ],
  "key_takeaways": ["Kernaussage 1"]
}}

Probleme:
{ISSUES_JSON}

Artikel:
{ARTICLE_JSON}

Protokoll:
{PROTOCOL_TEXT}
""".strip()


SUMMARY_SLIDE_PLAN_PROMPT = """
Du bist Slide-Planer für eine 9:16-Story. Verdichte den fertigen Artikel zu einer Cover-Slide und drei bis sieben Content-Slides. Maximal acht Content-Slides.

{STYLE_GUIDE}

Wichtig:
- Der Artikel ist die einzige Faktenquelle. Du darfst kürzen, umformulieren und weniger wichtige Details weglassen, aber keine Fakten hinzufügen.
- Nutze die H2-Abschnitte als Anker: eine H2 pro Content-Slide, wenn möglich. Teile lange Abschnitte an Absatz- oder Satzgrenzen.
- Behalte die Reihenfolge des Artikels bei.
- Die Cover-Slide enthält Kicker, Headline und einen englischen Bild-Brief.
- Cover-Headline: maximal 70 Zeichen, neutral, keine Frage.
- Jede Content-Slide enthält ein kurzes Label, eine Headline und einen Body.
- Label: ein bis zwei Wörter, Großbuchstaben, z. B. "HAUSHALT", "WINDPARK", "AUSBLICK".
- Headline: maximal 60 Zeichen, neutral, keine Frage.
- Body: maximal 220 Zeichen, ein bis zwei Sätze, keine Aufzählung.
- Keine Personennamen, keine Ironie, keine Wertung.

Antworte ausschließlich mit gültigem JSON in diesem Format:
{{
  "cover": {{
    "kicker": "SITZUNG KOMPAKT",
    "headline": "Neutrale Cover-Headline",
    "image_brief": "English one-sentence image brief"
  }},
  "slides": [
    {{
      "label": "HAUSHALT",
      "headline": "Neutrale Slide-Headline",
      "body": "Ein bis zwei Sätze."
    }}
  ]
}}

Artikel:
{ARTICLE_JSON}
""".strip()


TOPIC_SLIDE_PLAN_PROMPT = """
Du bist Slide-Planer für ein 4:5-Karussell. Verdichte den fertigen Artikel zu einer Cover-Slide und höchstens acht Content-Slides (zwei bis vier Paare). Die Content-Slides bilden Paare.

{STYLE_GUIDE}

Wichtig:
- Der Artikel ist die einzige Faktenquelle. Du darfst kürzen, umformulieren und weniger wichtige Details weglassen, aber keine Fakten hinzufügen.
- Wähle höchstens vier Aspekte. Wenn der Artikel mehr H2-Abschnitte hat, gruppiere sie zu zwei bis vier Paaren. Zähle die Paare vor der Ausgabe.
- Nutze die H2-Abschnitte als Anker: ein H2 pro Paar, wenn möglich. Teile lange Abschnitte an Absatz- oder Satzgrenzen.
- Jedes Paar erzählt einen Aspekt des Themas. Die zwei Slides eines Paares sind eine Doppelseite: Slide 1 hat das Textpanel links, Slide 2 hat das Textpanel rechts.
- Jedes Paar bekommt einen englischen `artwork_brief`: eine zusammenhängende Szene, die vertikal in der Mitte geteilt wird. Die Mitte muss ruhig bleiben; keine kritischen Details auf der Naht. Kein Text im Bild.
- Die Cover-Slide enthält Kicker, Headline und einen englischen Bild-Brief.
- Cover-Headline: maximal 70 Zeichen, neutral, keine Frage.
- Jede Content-Slide enthält ein kurzes Label, eine Headline und einen Body.
- Label: ein bis zwei Wörter, Großbuchstaben, z. B. "BESCHLUSS", "HINTERGRUND", "AUSBLICK".
- Headline: maximal 60 Zeichen, neutral, keine Frage.
- Body: maximal 160 Zeichen, ein bis zwei Sätze, keine Aufzählung.
- Keine Personennamen, keine Ironie, keine Wertung.

Antworte ausschließlich mit gültigem JSON in diesem Format:
{{
  "cover": {{
    "kicker": "THEMA IM FOKUS",
    "headline": "Neutrale Cover-Headline",
    "image_brief": "English one-sentence image brief"
  }},
  "pairs": [
    {{
      "slides": [
        {{"label": "BESCHLUSS", "headline": "Neutrale Headline", "body": "Ein bis zwei Sätze."}},
        {{"label": "HINTERGRUND", "headline": "Neutrale Headline", "body": "Ein bis zwei Sätze."}}
      ],
      "artwork_brief": "English one-sentence artwork brief"
    }}
  ]
}}

Artikel:
{ARTICLE_JSON}
""".strip()


SLIDE_REPAIR_PROMPT = """
Du bist Slide-Planer. Der folgende Slide-Plan enthält Text, der bei fester Schriftgröße nicht in die vorgesehene Box passt.

{STYLE_GUIDE}

Regeln:
- Kürze oder teile nur die betroffenen Slides.
- Behalte alle Fakten und die Reihenfolge bei.
- Ändere keine Slides, die bereits passen.
- Gib den vollständigen korrigierten Plan im selben JSON-Format zurück.
- Keine neuen Fakten, keine Personennamen, keine Ironie.

Betroffene Slides und Kapazität:
{OVERFLOW}

Bisheriger Plan:
{PLAN_JSON}

Artikel:
{ARTICLE_JSON}
""".strip()


SUMMARY_COVER_IMAGE_PROMPT = """
You are an editorial image prompt engineer. Write ONE English image prompt for a 9:16 cover image for a local news story.

The image must be photorealistic, atmospheric, and calm. It should have one clear main subject or visual metaphor, not a collage. It must not contain text, logos, brands, children, violence, or recognizable politicians. Leave the lower third and the top corners visually calm so typography can sit there. No sarcasm, no exaggerated metaphors.

Return only the image prompt, no explanations.

Cover headline:
{COVER_HEADLINE}

Article:
{ARTICLE_JSON}
""".strip()


TOPIC_COVER_IMAGE_PROMPT = """
You are an editorial image prompt engineer. Write ONE English image prompt for a 4:5 cover image for a local news topic post.

The image must be photorealistic, atmospheric, and calm. It should have one clear main subject or visual metaphor, not a collage. It must not contain text, logos, brands, children, violence, or recognizable politicians. Leave the lower third visually calm so typography can sit there. No sarcasm, no exaggerated metaphors.

Return only the image prompt, no explanations.

Cover headline:
{COVER_HEADLINE}

Article:
{ARTICLE_JSON}
""".strip()


TOPIC_ARTWORK_IMAGE_PROMPT = """
You are an editorial image prompt engineer. Write ONE English image prompt for a wide two-page spread used behind two paired slides of a carousel.

The spread is split into two full-page 4:5 pages: the left page appears as the full-page background of the first slide, the right page as the full-page background of the second slide. On the first slide, a solid text panel covers the left half of the left page, so the page's right half is visible. On the second slide, a solid text panel covers the right half of the right page, so the page's left half is visible. Compose one coherent scene across both pages with a calm vertical center line, so the two visible inner halves join seamlessly when the user swipes between the slides. Do not place a door frame, wall, tree trunk, pole, person, vehicle, or any other strong vertical line on the exact center line; let soft continuous elements such as ground, grass, sky, or foliage cross the seam. Keep critical details away from the center; both pages should still have visual interest. The image must be photorealistic, atmospheric, and calm. It must not contain text, logos, brands, children, violence, or recognizable politicians. No sarcasm.

Return only the image prompt, no explanations.

Slide pair:
{PAIR_JSON}

Article:
{ARTICLE_JSON}
""".strip()


TOPIC_CAPTION_PROMPT = """
Du bist Content-Editor für einen lokalen Nachrichtenkanal. Schreibe eine sehr kurze Instagram-Caption für diesen Themenbeitrag.

{STYLE_GUIDE}

Regeln:
- Ein bis zwei Sätze.
- Neutral, informativ, kein Call to Action, keine Frage.
- Maximal ein Emoji.
- Genau drei Hashtags, darunter #Rosdorf.
- Nur Fakten aus dem Artikel.

Antworte ausschließlich mit gültigem JSON:
{{"caption": "Ein bis zwei Sätze. #Kommunalpolitik #Gemeinderat #Rosdorf"}}

Artikel:
{ARTICLE_JSON}

Slide-Plan:
{SLIDE_PLAN_JSON}
""".strip()
