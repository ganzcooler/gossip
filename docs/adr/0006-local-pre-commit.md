# Lokale Pre-Commit-Hooks statt GitHub Actions

Es gibt keine GitHub-CI. `.github/workflows/ci.yml` wird entfernt. Stattdessen prüft ein lokaler Pre-Commit-Hook `ruff check` bei jedem Commit und die Testsuite `pytest -m "not manual"` vor dem Push.

Der Grund: Die Pipeline enthält lange LLM- und Bildläufe, die sich in GitHub Actions nicht sinnvoll und kostengünstig testen lassen. Die schnellen Prüfungen gehören an den Entwickler-Rechner; die Entscheidung, wann der volle Lauf stattfindet, bleibt lokal.
