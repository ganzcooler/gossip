# Zustandslose LLM-Schritte mit frischem Kontext

Die alte Pipeline rief ein Modell einmal für alle Artikel auf. Wir ersetzen das durch getrennte, zustandslose Calls: Redaktionsplan, Summary-Writer, Themen-Writer, Faktenprüfung, Reparatur, Caption und Bild-Prompt. Jeder Call bekommt nur seine eigenen Eingaben (Brief, Quellenauszüge, Designregeln) und keine Gesprächshistorie. Jede Antwort wird gegen ein Pydantic-Modell validiert und als JSON-Schema beim Provider angefragt.

Das macht Fehler pro Schritt isolierbar, macht Retries billig und verhindert, dass eine lange Konversation den Kontext verunreinigt. Der Preis sind mehr Calls pro Protokoll; das ist bewusst akzeptiert.
