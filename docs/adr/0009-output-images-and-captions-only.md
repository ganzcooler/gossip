# Nur Bilder und Captions als Datei-Output

Nach einem Pipeline-Lauf schreibt die Pipeline ausschließlich die gerenderten Bilder und die zugehörigen Captions in den Protokollordner. Es entstehen keine JSON-, Markdown-, Prompt- oder Manifest-Dateien. Artikel, Slides, Alt-Texte und Entwürfe bleiben in PostgreSQL.

Pro Beitrag entsteht genau eine Caption-Datei `caption-<post-type>-<slug>.txt`; die Bilddateien heißen `summary-<date>-story-<frame>.png` bzw. `topic-<date>-<slide>.png`. Alt-Texte werden nicht als Datei geschrieben, sondern bleiben in der Datenbank und sind über die API abrufbar.

Der Grund: Der Ordner ist das Veröffentlichungsartefakt, die Datenbank ist die Wahrheit für alles Strukturierte. Doppelte Dateiformate würden auseinanderlaufen und die manuelle Weiterverarbeitung erschweren.

Themenbeiträge liegen je Beitrag in einem stabilen Unterordner `topic-<slug>/` innerhalb des Protokollordners. Die Dateinamen bleiben exakt `topic-<date>-<slide>.png` und `caption-topic-<slug>.txt`; der Unterordner ist die kollisionsfreie Anwendung dieses Vertrags, wenn mehrere Themenbeiträge dieselbe Sitzung teilen. Der Summary-Output bleibt flach im Protokollordner, und die Aufräumlogik eines Themenbeitrags bleibt auf dessen Unterordner beschränkt.
