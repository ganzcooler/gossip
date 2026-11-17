"""Pure prompt builders for the stateless post-pipeline roles.

No I/O happens here; each builder returns one deterministic string. The
provider-facing JSON schema is supplied separately through the LLM port.
Every builder receives only its own step inputs: the planner gets the full
protocol, writers and fact-check get excerpts, and the caption gets metadata.
"""

from collections.abc import Sequence
from datetime import date, datetime

from pydantic import BaseModel

from app.core.post_models import (
    SourceExcerpt,
    SummaryBrief,
    SummaryDraft,
    TopicBrief,
    TopicDraft,
)


def _format_date(value: date | datetime | str) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    return str(value)


def _format_german_date(value: date | datetime | str) -> str:
    if isinstance(value, (date, datetime)):
        return value.strftime("%d.%m.%Y")
    return str(value)


def _json(value: BaseModel) -> str:
    return value.model_dump_json(indent=2)


def _excerpt_block(excerpts: Sequence[SourceExcerpt]) -> str:
    return "\n\n".join(
        f"[{index}] Anker: {excerpt.anchor}\nAuszug: {excerpt.excerpt}"
        for index, excerpt in enumerate(excerpts, start=1)
    )


def _brief_block(briefs: Sequence[SummaryBrief]) -> str:
    return "\n\n".join(
        f"[{index}] Punkt: {brief.point}\n"
        f"Relevanz: {brief.relevance}\n"
        f"Quellenanker: {' | '.join(brief.source_anchors)}"
        for index, brief in enumerate(briefs, start=1)
    )


def build_planner_prompt(
    *,
    protocol_title: str,
    session_date: date | datetime | str,
    protocol_text: str,
) -> str:
    """Build the Redaktionsplaner prompt from the full protocol text."""
    date_text = _format_date(session_date)
    return f"""Du bist der Redaktionsplaner von Gossip Rosdorf. Du liest ein \
kommunalpolitisches Protokoll und planst daraus genau einen Summary-Beitrag \
sowie null bis fünf Themenbeiträge.

Sitzung: {protocol_title}
Datum: {date_text}

## Aufgabe

Erstelle einen Redaktionsplan mit diesen Feldern:

- summary_focus: der rote Faden des Summary-Beitrags in einem kurzen Satz.
- summary_title: ein konkreter, lokaler Titel für den Summary-Beitrag.
- summary_briefs: 2 bis 6 Summary-Punkte. Jeder Punkt hat point (was passiert \
ist), relevance (warum es die Leserinnen und Leser betrifft) und mindestens \
einen Quellenanker. Die späteren Summary-Cards bekommen zusätzlich einen \
Ein-Wort-Kicker; plane den Kicker noch nicht als eigenes Feld.
- topic_briefs: 0 bis 5 Themenbriefs, nur für Themen mit echtem Deep-Dive-Wert. \
Jeder Themenbrief hat slug (nur [a-z0-9-]+), title, focus, relevance und \
mindestens einen Quellenanker. Slugs müssen innerhalb des Plans eindeutig sein.

Quellenanker sind kurze, exakte Zitate aus dem Protokoll oder präzise \
Abschnittsbezeichnungen (zum Beispiel eine TOP-Überschrift). Sie müssen im \
Protokoll wörtlich auffindbar sein, damit der Quellen-Retriever die passenden \
Auszüge deterministisch ziehen kann.

## Redaktionelle Regeln

- Schreibe auf Deutsch, nah an den Menschen in Rosdorf: sachlich, lokal, \
informativ und leicht trocken.
- Keine Personennamen. Rollen, Orte, Zahlen und Daten sind erlaubt und \
erwünscht.
- Keine Parteiframing, keine politische Wertung, keine Ironie, keine \
Übertreibung, kein Clickbait und keine Emojis.
- Wähle nur Themen, die im Protokoll tatsächlich verhandelt wurden. Erfinde \
keine Fakten, Zahlen oder Beschlüsse.
- Der Summary-Beitrag fasst die Sitzung im Überblick zusammen; die \
Themenbeiträge gehen nur bei ausreichend Substanz in die Tiefe.
- Der wichtigste Summary-Punkt kommt zuerst.

## Protokoll

{protocol_text}

## Ausgabeformat

Antworte ausschließlich mit einem einzigen JSON-Objekt, das dem vorgegebenen \
Schema entspricht. Kein Markdown, keine Erklärungen und kein Text außerhalb \
des JSON.
"""


def build_summary_writer_prompt(
    *,
    briefs: Sequence[SummaryBrief],
    excerpts: Sequence[SourceExcerpt],
    feedback: str | None = None,
) -> str:
    """Build the Summary-Writer prompt from Summary-Briefs and excerpts only."""
    feedback_block = ""
    if feedback:
        feedback_block = f"""
## Korrekturhinweis

Dein vorheriger Entwurf wurde abgelehnt:
{feedback}

Liefere einen vollständig neuen, gültigen Entwurf. Behalte nur die Fakten aus \
den Briefs und Quellenauszügen bei.
"""

    return f"""Du bist der Summary-Writer von Gossip Rosdorf. Du schreibst den \
Summary-Beitrag für eine Sitzung: einen Cover-Titel und zwei bis sechs \
Summary-Punkte.

## Summary-Briefs

{_brief_block(briefs)}

## Quellenauszüge

{_excerpt_block(excerpts)}

## Aufgabe

- cover_title: ein konkreter, lokaler Titel. Er ist die Überschrift des \
Covers und muss auf das Cover passen (maximal 3 Zeilen).
- points: 2 bis 6 Summary-Punkte in der Reihenfolge der Briefs. Der wichtigste \
Punkt kommt zuerst.
- Jeder Punkt hat:
  - kicker: ein Ein-Wort-Kicker, zum Beispiel Haushalt oder Radweg.
  - heading: eine kurze, konkrete Überschrift.
  - body: 120 bis 320 Zeichen inklusive Leerzeichen, ein zusammenhängender \
Absatz. Keine Aufzählung, keine Überschrift im Body.

## Redaktionelle Regeln

- Schreibe auf Deutsch, nah an den Menschen in Rosdorf: sachlich, lokal, \
informativ und leicht trocken.
- Keine Personennamen. Rollen, Orte, Zahlen und Daten sind erlaubt und \
erwünscht.
- Kein Parteiframing, keine politische Wertung, keine Ironie, keine \
Übertreibung, kein Clickbait und keine Emojis.
- Erfinde keine Fakten, Zahlen oder Beschlüsse. Stütze dich ausschließlich auf \
die Briefs und die Quellenauszüge.
- Formuliere in vollständigen Sätzen. Keine Abkürzungen erfinden und keine \
wörtlichen Zitate aus den Auszügen kopieren.
- Der Body wird nie gekürzt oder umgeschrieben; halte deshalb die 120 bis 320 \
Zeichen sicher ein.
{feedback_block}
## Ausgabeformat

Antworte ausschließlich mit einem einzigen JSON-Objekt, das dem vorgegebenen \
Schema entspricht. Kein Markdown, keine Erklärungen und kein Text außerhalb \
des JSON.
"""


def _topic_brief_block(brief: TopicBrief) -> str:
    return (
        f"Slug: {brief.slug}\n"
        f"Arbeitstitel: {brief.title}\n"
        f"Fokus: {brief.focus}\n"
        f"Relevanz: {brief.relevance}\n"
        f"Quellenanker: {' | '.join(brief.source_anchors)}"
    )


def build_topic_writer_prompt(
    *,
    brief: TopicBrief,
    excerpts: Sequence[SourceExcerpt],
    feedback: str | None = None,
) -> str:
    """Build the Themen-Writer prompt from one brief and its excerpts only."""
    feedback_block = ""
    if feedback:
        feedback_block = f"""
## Korrekturhinweis

Dein vorheriger Entwurf wurde abgelehnt:
{feedback}

Liefere einen vollständig neuen, gültigen Entwurf. Behalte nur die Fakten aus \
dem Brief und den Quellenauszügen bei.
"""

    return f"""Du bist der Themen-Writer von Gossip Rosdorf. Du schreibst genau \
einen Themenbeitrag zu einem einzelnen Thema aus einer Sitzung.

## Themenbrief

{_topic_brief_block(brief)}

## Quellenauszüge

{_excerpt_block(excerpts)}

## Aufgabe

Schreibe einen vollständigen Artikel mit genau dieser Struktur:

- title: der Artikelkopf (H1) mit 20 bis 100 Zeichen inklusive Leerzeichen. Er \
ist zugleich der Cover-Titel.
- sections: 2 bis 6 Themenabschnitte. Jeder Abschnitt hat:
  - h2: die Abschnittsüberschrift mit 20 bis 60 Zeichen inklusive Leerzeichen.
  - paragraphs: eine nicht-leere Liste vollständiger Absätze. Für einzelne \
Absätze gibt es keine Obergrenze.

Es gibt keinen Lead, keine Zusammenfassung, keine Takeaway-Liste, kein \
Kicker-Feld und keine weiteren Felder. Der gesamte Artikeltext aus H1, H2 und \
Absätzen darf zusammen höchstens 3000 Zeichen inklusive Leerzeichen enthalten.

## Design- und Inhaltsregeln

- Schreibe auf Deutsch, nah an den Menschen in Rosdorf: informativ, lokal, \
sachlich und leicht trocken.
- Keine Personennamen. Rollen, Orte, Zahlen und Daten sind erlaubt und \
erwünscht.
- Kein Parteiframing, keine politische Wertung, keine Ironie, keine \
Übertreibung, kein Clickbait und keine Emojis.
- Erfinde keine Fakten, Zahlen oder Beschlüsse. Stütze dich ausschließlich auf \
den Brief und die Quellenauszüge.
- Jede H2 beginnt später eine neue Folie; zu lange Absätze laufen auf \
Folgefolien weiter. Schreibe deshalb vollständige Absätze ohne manuelle \
Folienumbrüche und ohne Markdown.
- Der Beitrag soll nach dem Layout vier bis sieben Content-Slides ergeben. \
Halte den Text entsprechend kompakt und verteile ihn auf zwei bis sechs \
Abschnitte.
{feedback_block}
## Ausgabeformat

Antworte ausschließlich mit einem einzigen JSON-Objekt, das dem vorgegebenen \
Schema entspricht. Kein Markdown, keine Erklärungen und kein Text außerhalb \
des JSON.
"""


def build_fact_check_prompt(
    *, draft: BaseModel, excerpts: Sequence[SourceExcerpt]
) -> str:
    """Build the Faktenprüfung prompt from a draft and its excerpts only."""
    return f"""Du bist die Faktenprüfung von Gossip Rosdorf. Du prüfst einen \
Entwurf ausschließlich gegen die mitgelieferten Quellenauszüge.

## Entwurf

```json
{_json(draft)}
```

## Quellenauszüge

{_excerpt_block(excerpts)}

## Aufgabe

Prüfe jede Aussage im Entwurf: Namen, Rollen, Orte, Zahlen, Daten, Beschlüsse \
und Wirkungen. Melde nur konkrete Probleme, die sich aus den Quellenauszügen \
belegen lassen:

- nicht belegte oder falsche Aussagen,
- unzulässige Personennamen, Parteiframing, Ironie, Übertreibung, Clickbait \
oder Emojis,
- Struktur- oder Budgetverstöße, die im Entwurf sichtbar sind.

Jedes Issue ist ein vollständiger, umsetzbarer Korrekturhinweis. Ist alles \
belegt und regelkonform, liefere eine leere Liste. Mache keine allgemeinen \
Anmerkungen und keine Empfehlungen ohne konkreten Fehler.

## Ausgabeformat

Antworte ausschließlich mit einem einzigen JSON-Objekt mit dem Feld issues. \
Kein Markdown, keine Erklärungen und kein Text außerhalb des JSON.
"""


def build_repair_prompt(
    *,
    draft: BaseModel,
    issues: Sequence[str],
    excerpts: Sequence[SourceExcerpt],
) -> str:
    """Build the one repair prompt from the draft, issues and excerpts only."""
    issue_block = "\n".join(f"- {issue}" for issue in issues)
    return f"""Du bist die Reparatur von Gossip Rosdorf. Korrigiere den Entwurf \
minimal und ausschließlich anhand der gemeldeten Probleme und Quellenauszüge.

## Entwurf

```json
{_json(draft)}
```

## Gemeldete Probleme

{issue_block}

## Quellenauszüge

{_excerpt_block(excerpts)}

## Regeln

- Behebe jedes gemeldete Problem. Erfinde keine neuen Fakten, Zahlen oder \
Beschlüsse.
- Behalte die Struktur und alle nicht betroffenen Formulierungen bei.
- Entferne Personennamen, Parteiframing, Ironie, Übertreibung, Clickbait und \
Emojis.
- Kürze oder erweitere den Text nur so weit, wie es die Probleme und das \
Schema verlangen.
- Gib den vollständigen korrigierten Entwurf zurück, nicht nur die Änderungen.

## Ausgabeformat

Antworte ausschließlich mit einem einzigen JSON-Objekt, das dem vorgegebenen \
Schema entspricht. Kein Markdown, keine Erklärungen und kein Text außerhalb \
des JSON.
"""


def build_caption_prompt(
    *,
    draft: BaseModel,
    organ: str,
    session_date: date | datetime | str,
) -> str:
    """Build the caption-body prompt from the draft and metadata only."""
    return f"""Du bist der Caption-Writer von Gossip Rosdorf. Schreibe den \
Fließtext der Instagram-Caption für einen bereits fertigen Beitrag.

## Metadaten

- Organ: {organ}
- Sitzungsdatum: {_format_german_date(session_date)}

## Entwurf

```json
{_json(draft)}
```

## Aufgabe

- Schreibe ein bis drei kurze Sätze als Caption-Body: Was ist passiert und \
warum ist es für Rosdorf wichtig?
- Greife nur Fakten aus dem Entwurf auf. Erfinde nichts dazu.
- Keine Personennamen, kein Parteiframing, keine politische Wertung, keine \
Ironie, keine Übertreibung, kein Clickbait und keine Emojis.
- Kein Quellenlink, kein Quellenhinweis und kein KI-Hinweis; diese Teile \
werden deterministisch ergänzt.
- Keine Hashtags.

## Ausgabeformat

Antworte ausschließlich mit einem einzigen JSON-Objekt mit dem Feld body. Kein \
Markdown, keine Erklärungen und kein Text außerhalb des JSON.
"""


def build_topic_visual_prompt(draft: TopicDraft, pair_count: int) -> str:
    """Build the Themen visual-prompt prompt from the topic draft only.

    The writer gets the immutable article draft and the number of artwork
    prompts needed for the pair grid. It never sees the protocol, excerpts,
    the Summary draft, other topic drafts, or any conversation history.
    """
    if pair_count < 1:
        raise ValueError("pair_count must be at least 1")
    return f"""Du bist der Visual-Prompt-Writer von Gossip Rosdorf. Du schreibst \
Bildprompts für das Cover und die Bildpaare eines Themenbeitrags.

## Themenentwurf

```json
{_json(draft)}
```

## Aufgabe

- cover_prompt: ein englischer oder deutscher Prompt für das Cover im \
4:5-Feed-Format. Das Cover trägt später Titel, Logo, Organ-Badge und Kicker.
- artwork_prompts: genau {pair_count} Prompts, einer pro 720×1350-Bildpaar. \
Die Paare werden später in zwei 360×1350-Hälften geteilt; die linke Hälfte \
erscheint auf einer Folie, die rechte auf der nächsten.

## Design-Guardrails

- Eine atmosphärische Illustration, keine Dokumentarfotografie und keine \
gefälschte Beweisfotografie.
- Ein weiter, ruhiger, durchgehend fortlaufender Horizont ohne zentrales \
Motiv; die Szene passt zu einer kommunalpolitischen Sitzung in Rosdorf.
- Kein zentrales Motiv und keine Personen im Vordergrund; der Platz für \
Titel, Logo und Badge bleibt ruhig.
- 4:5-feed-sichere Komposition: wichtige Motive im zentralen Bereich, keine \
kritischen Inhalte am oberen oder unteren Rand.
- Die Bildpaare werden in der Mitte geteilt. Wichtige Inhalte liegen \
mindestens 40 px vom Paar-Seam entfernt; keine harte Kante und kein Motiv, \
das über die Naht hinweg zerschnitten wirkt.
- Kein Text, keine Buchstaben, keine Zahlen, keine Logos, keine Wappen und \
keine Parteisymbole im Bild.
- Keine erkennbaren Minderjährigen und keine fotorealistischen, namentlich \
erkennbaren Politikerinnen oder Politiker.
- Das Branding kommt ausschließlich aus dem Renderer, nie aus dem Bild.

## Ausgabeformat

Antworte ausschließlich mit einem einzigen JSON-Objekt, das dem vorgegebenen \
Schema entspricht. Kein Markdown, keine Erklärungen und kein Text außerhalb \
des JSON.
"""


def build_summary_visual_prompt(draft: SummaryDraft) -> str:
    """Build the Summary visual-prompt prompt from the Summary draft only."""
    return f"""Du bist der Visual-Prompt-Writer von Gossip Rosdorf. Du schreibst \
genau einen Bildprompt für das Cover des Summary-Beitrags.

## Summary-Entwurf

```json
{_json(draft)}
```

## Aufgabe

- cover_prompt: ein englischer oder deutscher Prompt für eine atmosphärische \
Illustration im 9:16-Story-Format.
- artwork_prompts: für den Summary-Beitrag immer eine leere Liste. Die \
Summary-Cards nutzen dasselbe Cover-Bild.

## Design-Guardrails

- Eine atmosphärische Illustration, keine Dokumentarfotografie und keine gefälschte \
Beweisfotografie.
- Eine breite, ruhige, zivile Szene mit einem durchgehenden Horizont, passend zu \
einer kommunalpolitischen Sitzung in Rosdorf.
- Kein zentrales Motiv und keine Personen im Vordergrund; der Platz für Titel, \
Logo und Badge bleibt ruhig.
- 9:16-Story-sichere Komposition: wichtige Motive in der oberen und mittleren \
Bildhälfte, keine kritischen Inhalte am oberen oder unteren Rand.
- Kein Text, keine Buchstaben, keine Zahlen, keine Logos und keine Parteisymbole \
im Bild.
- Keine erkennbaren Minderjährigen und keine fotorealistischen, namentlich \
erkennbaren Politikerinnen oder Politiker.
- Keine Logos, Wappen oder Schriftzüge; das Branding kommt ausschließlich aus \
dem Renderer.

## Ausgabeformat

Antworte ausschließlich mit einem einzigen JSON-Objekt, das dem vorgegebenen \
Schema entspricht. Kein Markdown, keine Erklärungen und kein Text außerhalb \
des JSON.
"""
