# Plan: Legacy Pipeline entfernen + API-Trigger

## Zusammenfassung

Entfernung der `src/` Legacy-Pipeline und Ersetzung durch API-Endpunkte zum manuellen Triggern.

## Analyse: Was wird aus `src/` genutzt?

### Von `app/` aktiv genutzt:
| Datei | Nutzung in |
|-------|------------|
| `src/pipeline_steps/generate_articles.py` | `app/services/pipeline_adapter.py:14` |
| `src/pipeline_steps/generate_image_prompt.py` | `app/services/pipeline_adapter.py:15` |
| `src/pipeline_steps/generate_image.py` | `app/services/pipeline_adapter.py:16` |
| `src/pipeline_steps/generate_insta_caption.py` | `app/services/pipeline_adapter.py:17` |
| `src/insta_images.py` | `app/services/pipeline_adapter.py:190` |
| `src/models.py` | `app/services/pipeline_adapter.py:18` |
| `src/prompts.py` | Indirekt via generate_* Funktionen |
| `src/config.py` | Indirekt via generate_* Funktionen |
| `src/tags.py` | Via `src/insta_images.py` |

### Nicht mehr benötigt (Legacy-only):
- `main.py` - Entry point für Legacy-Pipeline
- `src/pipeline.py` - Hauptpipeline-Logik
- `src/pipeline_steps/find_pdf_files.py` - PDF-Suche (wird nicht mehr genutzt)
- `src/pipeline_steps/extract_text.py` - Text-Extraktion (wird nicht mehr genutzt)
- `src/pipeline_steps/check_existing_articles.py` - Duplikat-Check (wird nicht mehr genutzt)
- `src/pipeline_steps/save_article.py` - Speichern (wird nicht mehr genutzt)
- `src/pipeline_steps/save_image.py` - Speichern (wird nicht mehr genutzt)
- `src/pipeline_steps/setup_logger.py` - Logger (wird nicht mehr genutzt)
- `src/utils.py` - Hilfsfunktionen (wird nicht mehr genutzt)

## Geplante Änderungen

### 1. Neue Dateien erstellen

#### `app/core/`
Neues Package für zentrale Konfiguration und Modelle:
- `app/core/config.py` - Zusammenführung von `app/config.py` + relevante Teile aus `src/config.py`
- `app/core/models.py` - Pydantic-Modelle aus `src/models.py` (SingleArticle, etc.)
- `app/core/prompts.py` - Prompts aus `src/prompts.py`
- `app/core/tags.py` - Tags aus `src/tags.py`

#### `app/services/`
- `app/services/article_generator.py` - Verschieben von `src/pipeline_steps/generate_articles.py`
- `app/services/image_generator.py` - Verschieben von `src/pipeline_steps/generate_image.py` + `generate_image_prompt.py`
- `app/services/insta_generator.py` - Verschieben von `src/pipeline_steps/generate_insta_caption.py` + `src/insta_images.py`

#### `app/api/routes.py` erweitern
Neue Endpunkte:
- `POST /api/pipeline/fetch` - Protokolle von SessionNet abrufen
- `POST /api/pipeline/process` - Unverarbeitete Protokolle verarbeiten
- `POST /api/pipeline/run` - Beides (fetch + process) nacheinander
- `GET /api/pipeline/status` - Aktuellen Pipeline-Status abfragen

### 2. Zu löschende Dateien/Verzeichnisse
- `main.py`
- `src/` (komplett)
- `start.bat` (optional, falls nur für Legacy)

### 3. Zu aktualisierende Dateien
- `app/config.py` - Auf `app/core/config.py` umstellen
- `app/services/pipeline_adapter.py` - Imports anpassen
- `app/services/protocol_processor.py` - Imports anpassen
- `app/services/protocol_fetcher.py` - Imports anpassen
- `requirements.txt` - Falls nötig prüfen
- `AGENTS.md` - Dokumentation aktualisieren

## API-Endpunkte Spezifikation

### `POST /api/pipeline/fetch`
Trigger: Protokolle von SessionNet abrufen
Response:
```json
{
  "status": "success",
  "protocols_found": 5,
  "message": "5 new protocols fetched"
}
```

### `POST /api/pipeline/process`
Trigger: Unverarbeitete Protokolle verarbeiten
Response:
```json
{
  "status": "success",
  "processed": 3,
  "message": "3 protocols processed"
}
```

### `POST /api/pipeline/run`
Trigger: Fetch + Process nacheinander
Response:
```json
{
  "status": "success",
  "fetch_result": {"protocols_found": 5},
  "process_result": {"processed": 3}
}
```

### `GET /api/pipeline/status`
Status abfragen
Response:
```json
{
  "unprocessed_protocols": 2,
  "total_protocols": 42,
  "total_articles": 15
}
```

## Migrations-Schritte

1. **Neue Struktur erstellen**
   - `app/core/` Package mit Config, Models, Prompts, Tags
   - Services aus `src/` nach `app/services/` verschieben

2. **Imports aktualisieren**
   - Alle `from src...` Imports auf neue Pfade umstellen

3. **API-Endpunkte implementieren**
   - Neue Routes in `app/api/routes.py` hinzufügen

4. **Legacy-Code entfernen**
   - `main.py` löschen
   - `src/` Verzeichnis löschen

5. **Testen**
   - Docker-Compose Build testen
   - API-Endpunkte manuell testen

## Offene Fragen

1. Soll der Scheduler weiterhin automatisch laufen oder komplett durch manuelle API-Calls ersetzt werden?
2. Soll es einen Authentifizierungs-Mechanismus für die API-Endpunkte geben?
3. Soll `start.bat` erhalten bleiben oder kann es entfernt werden?
