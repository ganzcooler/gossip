# 01: Runway cleanup: local hooks and legacy removal

**What to build:** Das Repo ist bereit für die neue Pipeline: GitHub Actions ist entfernt, lokale `pre-commit`-Hooks sind aktiv, und die alte One-Call-Artikel-/Caption-/Bild-/Instagram-Pipeline samt Tests ist gelöscht. Protokoll-Fetcher, Duplicate Detector, Scheduler, OpenRouter-Client-Grundlage, `Protocol` und der lesbare Legacy-Artikel-Pfad bleiben erhalten. Nach dem Ticket laufen Lint und die Standardtests lokal grün.

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] Es gibt keine GitHub-Actions-Konfiguration mehr.
- [x] Das `pre-commit`-Framework ist eingerichtet: `ruff check` bei Commit, `pytest -m "not manual"` vor Push.
- [x] Die alten One-Call-Module und ihre Tests sind entfernt; keine Imports oder Routen verweisen mehr darauf.
- [x] Protokoll-Fetcher, Duplicate Detector, Scheduler, OpenRouter-Client-Grundlage, `Protocol` und der Legacy-Artikel-Read-Endpoint funktionieren weiter.
- [x] `ruff check` und `pytest -m "not manual"` laufen lokal grün.

## Comments

Resolved via merge of `ticket/01-runway-cleanup` into `feat/stateless-post-pipeline` as `defeb9b` ("merge: ticket 01 runway cleanup"), with no conflicts. Local hooks installed for pre-commit and pre-push. Gate results in the integration checkout: `ruff check .` passed, `pytest -m "not manual"` passed with 149 tests.
