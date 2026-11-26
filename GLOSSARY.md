# Gossip Rosdorf

Gossip turns municipal council protocols from SessionNet into reader-facing Instagram posts for Rosdorf. This glossary defines the vocabulary used by the post pipeline and the design contract.

## Language

**Protokoll**:
The fetched SessionNet document for one meeting, including its PDF text.
_Avoid_: PDF, Dokument, Quelle

**Sitzung**:
The meeting described by one Protokoll. One Sitzung produces one Summary-Beitrag and zero or more Themenbeiträge.
_Avoid_: Ratssitzung, Termin

**Organ**:
The official body that met, shown in the badge; for example Gemeinderat Rosdorf or Ortsrat Atzenhausen.
_Avoid_: Gremium, Veranstalter

**Beitrag**:
A reader-facing unit produced from a Sitzung. A Beitrag is either a Summary-Beitrag or a Themenbeitrag.
_Avoid_: Artikel, Post (when the type matters)

**Summary-Beitrag**:
The blue 9:16 story sequence that gives a 30-second overview of a Sitzung. It has a cover and two to six cards, one card per selected topic.
_Avoid_: Zusammenfassung, Summary-Post, 4:5-Summary

**Summary-Punkt**:
One agenda item in a Summary-Beitrag, made of a kicker, a heading, and a body. One Summary-Card normally shows one Summary-Punkt.
_Avoid_: Point, Bullet, Topic

**Summary-Card**:
The 9:16 story frame that shows one Summary-Punkt.
_Avoid_: Slide, Story-Frame, Karte

**Themenbeitrag**:
The orange 4:5 feed carousel that explains one topic in depth. It has a cover and three to seven content slides.
_Avoid_: Themenpost, Topic-Post, Artikel

**Themenabschnitt**:
One H2 with its paragraphs inside a Themenbeitrag. A Themenabschnitt starts a new slide and may continue across slides.
_Avoid_: Section, Kapitel

**Kicker**:
The one-word uppercase label of a Themenabschnitt, shown on its H2 slide and on every Folgeslide of that section; a Summary-Punkt also carries its Kicker on the Summary-Card.
_Avoid_: chapter_short, section label

**Folgeslide**:
A content slide of a Themenabschnitt without its own H2. It continues the section body and shows the section's Kicker plus the page counter.
_Avoid_: Fortsetzung, Folgeseite

**Artikelkopf**:
The H1 of a Themenbeitrag; it is also the cover title.
_Avoid_: Headline, Überschrift (when the H1 is meant)

**Folie**:
One image in a Beitrag. A Summary-Beitrag uses story frames; a Themenbeitrag uses feed slides.
_Avoid_: Slide, Seite, Frame (when the type matters)

**Redaktionsplan**:
The planner output that selects the Summary focus and the Themenbriefs for one Sitzung.
_Avoid_: Editorial Plan, Inhaltsplan

**Themenbrief**:
The planner's brief for one Themenbeitrag: slug, working title, focus, relevance, and source anchors.
_Avoid_: Topic Brief, Themenauftrag

**Quellenanker**:
A short exact quote or precise section label from the Protokoll used to retrieve only the relevant excerpts for a writer call.
_Avoid_: Anker, Zitat, Referenz

**Faktenprüfung**:
The gate that compares a draft against the retrieved source excerpts from the Protokoll and reports unsupported, wrong, or inadmissible claims.
_Avoid_: Fact Check, QA

**Artefaktprüfung**:
The decision-model gate that inspects each final generated image for unintended borders or blank areas, panels or seams, added watermarks or overlays, rotation, and recognizable minors. It runs on the exact asset that will be published; a flagged image is regenerated once, then replaced by the brand fallback. Scene text, logos, coats of arms, adults and deliberate satirical exaggeration are allowed.
_Avoid_: Bildprüfung, Vision-Check

**Caption**:
The Instagram caption of a Beitrag. It carries source, date, and the first-line label `Bild: KI-generiert.`
_Avoid_: Beschreibung, Text

**Alt-Text**:
The per-slide accessibility text derived from the slide content.
_Avoid_: Bildbeschreibung

**Legacy-Artikel**:
An `articles` row from the pre-post pipeline. It stays readable but is not written by the new pipeline.
_Avoid_: Alter Beitrag, Altartikel
