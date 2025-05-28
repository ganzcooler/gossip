import logging
import os
import glob
import pathlib
import json

from google import genai
from google.genai import types
from pydantic import BaseModel

# -------- Konfiguration --------
PROMPT = "Summarize this document"
INPUT_DIR = "pdf_files"
OUTPUT_DIR = "json_output"
LOG_FILE = "pdf-to-json.log"
MODEL_NAME = "gemini-2.0-flash"

# -------- Datenmodell --------
class Protokoll(BaseModel):
    top: str
    inhalt: str

# -------- Logging --------
def configure_logging(log_file_path=LOG_FILE):
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        filename=log_file_path,
        filemode='a'
    )

# -------- API-Client --------
def initialize_client():
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY fehlt!")
    return genai.Client(api_key=api_key)

# -------- PDF-Erkennung --------
def get_pdf_files(folder_path=INPUT_DIR):
    return glob.glob(os.path.join(folder_path, "*.pdf"))

# -------- Verarbeitung einer einzelnen PDF --------
def process_pdf_file(client, pdf_file, prompt=PROMPT):
    pdf_path = pathlib.Path(pdf_file)
    # JSON-Ausgabepfad zusammenstellen
    json_dir = pathlib.Path(OUTPUT_DIR)
    json_dir.mkdir(exist_ok=True)
    json_path = json_dir / (pdf_path.stem + ".json")

    # Variante B: Überspringen, wenn JSON schon existiert
    if json_path.exists():
        logging.info(f"Übersprungen (bereits da): {pdf_path.name}")
        return

    logging.info(f"Verarbeite: {pdf_path.name}")
    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=[
                types.Part.from_bytes(
                    data=pdf_path.read_bytes(),
                    mime_type='application/pdf'
                ),
                prompt
            ],
            config={
                "response_mime_type": "application/json",
                "response_schema": list[Protokoll],
            },
        )
        data = json.loads(response.text)
        with open(json_path, 'w') as f:
            json.dump(data, f, indent=2)

        logging.info(f"Gespeichert: {json_path}")
        print(f"Saved JSON output to {json_path}")
    except Exception as e:
        logging.error(f"Fehler bei {pdf_path.name}: {e}", exc_info=True)

# -------- Hauptprogramm --------
if __name__ == "__main__":
    configure_logging()
    client = initialize_client()
    pdf_files = get_pdf_files()

    for pdf_file in pdf_files:
        process_pdf_file(client, pdf_file)
