# Additives Post-Schema, Legacy-Artikel bleiben unangetastet

Die neuen Beitragstypen passen nicht in eine Zeile pro Artikel. Wir legen deshalb die Tabellen `posts`, `post_slides`, `post_assets` und `editorial_plans` neu an. Die bestehende Tabelle `articles` und ihre API bleiben unverändert lesbar; der neue Processor schreibt sie nicht mehr.

Das Schema ist additiv: `create_all()` legt die neuen Tabellen beim Start an, es gibt keine destruktive Migration und keine Alembic-Einführung. Alte Daten bleiben erreichbar, ein Rollback ist einfach. Wenn sich das Schema später ändert, kann Alembic nachgezogen werden.
