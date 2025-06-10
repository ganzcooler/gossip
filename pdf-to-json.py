from google import genai
from google.genai import types
from pydantic import BaseModel
import pathlib, json, time
import logging
import configparser
from pathlib import Path

# -------- CONFIG --------
PDF_DIRNAME = "pdf_files"
JSON_DIRNAME = "json-files"
LOG_FILENAME = "pdf-to-json.log"
MODEL_NAME = "gemini-2.5-flash-preview-05-20"
# -------------------------

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILENAME, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# Konfigurationsdatei laden
def load_api_key_from_config():
    # Inhalt config.ini
    # [genai]
    # GOOGLE_API_KEY=dein_api_schlüssel_hier
    
    config_path = Path(__file__).parent / "config.ini"
    if not config_path.exists():
        raise FileNotFoundError(f"Konfigurationsdatei nicht gefunden: {config_path}")

    config = configparser.ConfigParser()
    config.read(config_path)

    api_key = config.get("genai", "GOOGLE_API_KEY", fallback=None)
    if not api_key:
        raise ValueError("GOOGLE_API_KEY fehlt in der Konfigurationsdatei!")

    return api_key

class TOP(BaseModel):
    top_id: str
    content: str

class Protokoll(BaseModel):
    title: str
    datum: str
    tops: list[TOP]

# Suche nach der PDF-Datei im aktuellen Verzeichnis im Unterordner "pdf_files"
current_dir = pathlib.Path(__file__).parent
pdf_dir = current_dir / PDF_DIRNAME

# Suche nach allen PDF-Dateien im Unterordner
pdf_files = list(pdf_dir.glob("*.pdf"))

prompt = '''
Du bist ein KI-Assistent.
Extrahiere die Tagesordnungspunkte mitsamt deren Inhalt aus dem PDF-Dokument und gib sie im JSON-Format zurück.
Schreibe in "top_id" die ID des Tagesordnungspunktes.
In "content" soll die Überschrift des Tagesordnungspunktes und dessen Inhalt stehen.
In "datum" soll das Datum des Protokolls im Format "YYYY-MM-DD" stehen.
In "title" soll der Titel des Ausschusses oder der Sitzung stehen, z.B. "Jugendausschuss".

Hier ein Beispiel für das JSON-Format:
{
  "title": "Jugendausschuss",
  "datum": "2023-10-01",
  "tops": [
    {
      "top_id": "1",
      "content": "Erster Tagesordnungspunkt Inhalt"
    },
    {
      "top_id": "2",
      "content": "Zweiter Tagesordnungspunkt Inhalt"
    }
  ]
}
'''

for filepath in pdf_files:
    try:
        json_dir = current_dir / JSON_DIRNAME
        json_filepath = json_dir / (filepath.stem + ".json")
        if json_filepath.exists():
            log.info(f"JSON file already exists for {filepath.name}, skipping.")
            continue

        log.info(f"Processing PDF: {filepath.name}")
        try:
            client = genai.Client(api_key=load_api_key_from_config())
        except Exception as e:
            log.error(f"Fehler beim Initialisieren des genai-Clients: {e}")
            continue

        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=[
                    types.Part.from_bytes(
                        data=filepath.read_bytes(),
                        mime_type='application/pdf',
                    ),
                    prompt],
                config={
                    "response_mime_type": "application/json",
                    "response_schema": Protokoll,
                })
        except Exception as e:
            log.error(f"Fehler beim Generieren des Contents für {filepath.name}: {e}")
            continue

        if response.text is not None:
            try:
                response_json = json.loads(response.text)
                log.info(f"Successfully received response for {filepath.name}")
            except Exception as e:
                response_json = None
                log.error(f"Fehler beim Parsen der JSON-Antwort für {filepath.name}: {e}")
        else:
            response_json = None
            log.error(f"No response text received for {filepath.name}.")

        # Speichern der Antwort im JSON-Format im Unterordner "json-files"
        try:
            json_dir.mkdir(exist_ok=True)
            if response_json is not None:
                with open(json_filepath, "w", encoding="utf-8") as f:
                    json.dump(response_json, f, ensure_ascii=False, indent=2)
                log.info(f"Saved JSON to {json_filepath}")
            else:
                log.error(f"No JSON to save for {filepath.name}")
        except Exception as e:
            log.error(f"Fehler beim Speichern der JSON-Datei für {filepath.name}: {e}")
        
        # 6 Sekunden warten (API-Limits)
        time.sleep(6)
        
    except Exception as e:
        log.error(f"Unerwarteter Fehler bei der Verarbeitung von {filepath.name}: {e}")
