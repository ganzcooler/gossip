# Lokale Entwicklungsumgebung

Diese Anleitung beschreibt, wie Sie die Anwendung lokal testen können, ohne Docker-Container für die Anwendung selbst zu starten.

## Voraussetzungen

- Docker und Docker Compose installiert
- Python 3.11+ mit pip

## Schritt 1: Docker Compose starten

Starten Sie den PostgreSQL-Container und Adminer:

```bash
cd local
docker compose up -d
```

Dies startet:
- **PostgreSQL** auf Port `5432` (Datenbank: `gossip`, Benutzer: `gossip_user`, Passwort: `secure_password`)
- **Adminer** auf Port `http://localhost:8080` für Datenbankverwaltung

## Schritt 2: .env Datei konfigurieren

Kopieren Sie `.env.example` nach `.env` und passen Sie die Pfade für `articles` und `logs` an:

```env
# Datenbank
DB_HOST=localhost
DB_PORT=5432
DB_NAME=gossip
DB_USER=gossip_user
DB_PASSWORD=secure_password

# Verzeichnisse - Lokale Pfade statt Docker-Pfade
ARTICLES_DIR=./articles
LOGS_DIR=./logs

# Weitere Variablen (aus .env.example übernehmen)
SESSIONNET_URL=...
OPENAI_API_KEY=...
# ... weitere Variablen
```

**Wichtig:** Die lokalen Pfade müssen auf das tatsächliche Verzeichnis auf Ihrem Rechner zeigen.

## Schritt 3: Abhängigkeiten installieren

```bash
pip install -r requirements.txt
```

## Schritt 4: Anwendung starten

```bash
uvicorn app.main:app
```

Die Anwendung ist dann unter http://localhost:8000 verfügbar.

## Datenbankverwaltung mit Adminer

1. Öffnen Sie http://localhost:8080
2. Anmeldung:
   - System: PostgreSQL
   - Server: postgres
   - Benutzer: gossip_user
   - Passwort: secure_password
   - Datenbank: gossip

## Container stoppen

```bash
cd local
docker compose down
```

Um auch die Datenbank zu löschen:

```bash
docker compose down -v
```
