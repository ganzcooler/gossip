# Themenbeitrag = H1 + H2 + Absätze, Folien deterministisch

Ein Themenbeitrag besteht inhaltlich nur aus einer H1 und mehreren H2-Abschnitten mit Absätzen. Es gibt keinen Lead, keine Kicker-Felder, keine Takeaway-Liste. Der Writer liefert genau diese Struktur; die Folien entstehen danach deterministisch aus dem Text. Die H1 ist der Artikelkopf und zugleich der Cover-Titel; jede H2 beginnt einen Themenabschnitt.

Jede H2 beginnt auf einer neuen Folie. Passen die zugehörigen Absätze nicht auf die Folie, laufen sie auf Folgeslides weiter, auf denen die H2 klein oben steht. Der Text wird dabei nicht umgeschrieben und nicht gekürzt. Die H1 hat 20–100 Zeichen, es gibt 2–6 H2 mit je 20–60 Zeichen, und der gesamte Artikeltext aus H1, H2 und Absätzen hat eine harte Obergrenze von 3.000 Zeichen inklusive Leerzeichen. Für einzelne Absätze gibt es keine Obergrenze. Nach dem Layout entstehen 4–7 Content-Slides. Verletzt ein Entwurf diese Grenzen, bekommt der Writer einen frischen Versuch mit Validierungsfeedback; danach ist der Beitrag failed.

Der Grund: Der Text bleibt die Wahrheit, das Layout ist eine Ableitung. Ein LLM-Slide-Editor würde den Text umformulieren und die Faktenprüfung unterlaufen.

## Nachtrag: Absatz-Vorabprüfung und Satzgrenzen-Split

Die folgende Verfeinerung ersetzt die ursprüngliche Aussage „Absätze laufen zeilenweise weiter“; die Grundentscheidung (Text bleibt die Wahrheit, Folien entstehen deterministisch, 4–7 Content-Slides) bleibt unverändert.

- Vor dem Packen wird jeder Absatz bei jeder Kandidaten-Body-Größe (42/39/36) gegen seine Seitenkapazität geprüft. Der erste Absatz eines Abschnitts wird an der kleineren Heading-Folie gemessen, weil dort die H2 Platz braucht; alle späteren Absätze an der Continuation-Folie. Eine Heading-Folie ohne Body wird so vermieden.
- Ein Absatz, der auf seine volle Seite passt, ist atomar. Passt er nicht mehr in den Rest der aktuellen Folie, wandert er ganz auf die nächste Folie. Nur Absätze, die eine volle Seite überschreiten, werden geteilt.
- Ein überlanger Absatz wird bevorzugt an einer Satzgrenze nahe der Mitte geteilt. Hat der Absatz mindestens drei Sätze, enthält die Fortsetzung mindestens zwei vollständige Sätze. Rendert der Absatz mindestens vier Zeilen, umfasst die Fortsetzung zusätzlich mindestens zwei gerenderte Zeilen und mindestens 25 % der Absatzhöhe. Bei Absätzen unter vier Zeilen entfallen diese beiden Größenregeln; dann wird ausgewogen geteilt.
- Ohne passende Satzgrenze wird der bestmögliche ausgewogene Wortumbruch nahe der Mitte gewählt. Der Text wird nie umformuliert, gekürzt, hypheniert oder zeichenweise getrennt; die Teile setzen sich exakt zum normalisierten Ausgangstext zusammen.
- Die Satzgrenzenerkennung ist eine statische Heuristik über `. ! ? …` und schließende Anführungszeichen. Häufige Abkürzungen (`z. B.`, `d. h.`, `u. a.`, `usw.`, `Nr.`, `Dr.`, `St.`, `ca.`) gelten nicht als Satzende; `Test.` oder `Africa.` bleiben dagegen echte Satzenden, weil die Abkürzungsprüfung eine Wortgrenze voraussetzt.
- Jeder Teil eines geteilten Absatzes steht als eigener Body-Block auf einer eigenen Folie. Dadurch entsteht innerhalb des Absatzes kein Absatzabstand. Die harte 4–7-Grenze und die Body-Größen 42/39/36 bleiben unverändert.
