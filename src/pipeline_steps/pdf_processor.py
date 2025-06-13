import google.generativeai as genai
# types is no longer needed for Part.from_bytes
from pydantic import BaseModel
import pathlib
import json
import time
import logging
import sys

# Ensure src directory is in sys.path for config import
project_root_for_import = pathlib.Path(__file__).resolve().parent.parent.parent
if str(project_root_for_import) not in sys.path:
    sys.path.insert(0, str(project_root_for_import))

try:
    from src import config
except ImportError as e:
    print(f"Error importing src.config: {e}")
    print(f"Current sys.path: {sys.path}")
    print(f"Attempted project_root_for_import: {project_root_for_import}")
    raise

# Initialize logger using the helper from config
log = config.get_logger(__name__, config.PDF_TO_JSON_LOG_FILENAME)

# Pydantic Models
class TOP(BaseModel):
    top_id: str
    content: str
    relevant: bool

class Protokoll(BaseModel):
    title: str
    datum: str
    tops: list[TOP]

PROMPT_TEXT = """
Du bist ein KI-Assistent.
Extrahiere die Tagesordnungspunkte mitsamt deren Inhalt aus dem PDF-Dokument und gib sie im JSON-Format zurück.
Schreibe in "top_id" die ID des Tagesordnungspunktes.
In "content" soll die Überschrift des Tagesordnungspunktes und dessen Inhalt stehen.
Für jeden Tagesordnungspunkt, bewerte ob dieser für einen journalistischen Artikel geeignet ist und füge ein Feld "relevant" (boolean true/false) hinzu. Ein Tagesordnungspunkt ist relevant, wenn er genügend Inhalt bietet und auf emotionale und aufsehenerregende Weise dargestellt werden kann.
In "datum" soll das Datum des Protokolls im Format "YYYY-MM-DD" stehen.
In "title" soll der Titel des Ausschusses oder der Sitzung stehen, z.B. "Jugendausschuss".

Hier ein Beispiel für das JSON-Format:
{
  "title": "Jugendausschuss",
  "datum": "2023-10-01",
  "tops": [
    {
      "top_id": "1",
      "content": "Erster Tagesordnungspunkt Inhalt, der sehr spannend ist und viele Details bietet.",
      "relevant": true
    },
    {
      "top_id": "2",
      "content": "Zweiter Tagesordnungspunkt Inhalt, eher administrativ.",
      "relevant": false
    }
  ]
}
"""

# The get_top_relevance function was removed as its functionality is now integrated
# into the main PROMPT_TEXT used by process_single_pdf.

def process_single_pdf(pdf_filepath: pathlib.Path,
                       json_output_dir: pathlib.Path,
                       genai_model_instance: genai.GenerativeModel, # Renamed and type changed
                       prompt: str): # Removed model_name as it's part of genai_model_instance
    log.info(f"Attempting to process PDF: {pdf_filepath.name}")
    json_filepath = json_output_dir / (pdf_filepath.stem + '.json')
    if json_filepath.exists():
        log.info(f"JSON file already exists for {pdf_filepath.name}, skipping.")
        return

    try:
        pdf_bytes = pdf_filepath.read_bytes()
        # model_name is implicit in the genai_model_instance
        response = genai_model_instance.generate_content(
            contents=[
                {"inline_data": {"mime_type": "application/pdf", "data": pdf_bytes}},
                prompt
            ],
            generation_config={
                "response_mime_type": "application/json",
            },
            request_options={"timeout": 120} # Increased timeout
        )

        response_json = None
        if response.parts:
            try:
                raw_text = response.text
                response_json = json.loads(raw_text)
                log.info(f"Successfully received and parsed JSON response for {pdf_filepath.name}")
            except json.JSONDecodeError as e:
                log.error(f"Error parsing JSON response for {pdf_filepath.name}: {e}. Response text: {raw_text[:500]}")
            except Exception as e:
                 log.error(f"Error accessing response text for {pdf_filepath.name}: {e}. Full response: {response}")
        else:
            log.error(f"No parts found in response for {pdf_filepath.name}. Full response: {response}")

        if response_json is not None:
            # The PROMPT_TEXT now instructs the LLM to include the 'relevant' field.
            # Therefore, the separate loop to determine relevance is removed.
            # We now expect response_json to already contain the 'relevant' field for each TOP.

            # Basic validation can still be useful here if desired, e.g.,
            # if not (isinstance(response_json, dict) and 'tops' in response_json and isinstance(response_json['tops'], list)):
            #    log.warning(f"Response JSON for {pdf_filepath.name} does not match expected structure (dict with a 'tops' list). JSON: {str(response_json)[:200]}")
            # else:
            #    for top_item in response_json.get('tops', []):
            #        if 'relevant' not in top_item:
            #            log.warning(f"TOP item {top_item.get('top_id', 'N/A')} in {pdf_filepath.name} is missing the 'relevant' field.")
            #            # Optionally, set a default: top_item['relevant'] = False

            # Save the response_json (now expected to contain the 'relevant' field directly from LLM)
            json_output_dir.mkdir(parents=True, exist_ok=True)
            with open(json_filepath, "w", encoding="utf-8") as f:
                json.dump(response_json, f, ensure_ascii=False, indent=2)
            log.info(f"Saved JSON to {json_filepath}")
        else:
            log.error(f"No JSON to save for {pdf_filepath.name} (either not received, parsing failed, or no parts in response).")

    except Exception as e:
        log.error(f"Error during GenAI call or file operations for {pdf_filepath.name}: {e}", exc_info=True)
    finally:
        log.info("Waiting for 6 seconds due to potential API rate limits...")
        time.sleep(6)


def run_pdf_to_json_conversion():
    log.info("Starting PDF to JSON conversion process...")
    try:
        api_key = config.load_google_api_key()
        genai.configure(api_key=api_key)
        # Instantiate the model to be used for PDF extraction
        pdf_extraction_model = genai.GenerativeModel(config.GENAI_PDF_EXTRACTION_MODEL)
        log.info(f"GenAI model {config.GENAI_PDF_EXTRACTION_MODEL} initialized for PDF extraction.")
    except Exception as e:
        log.critical(f"CRITICAL: Error initializing GenAI (configuring or creating model): {e}", exc_info=True)
        return

    pdf_dir = config.PROJECT_ROOT / config.PDF_DIR_NAME
    json_dir = config.PROJECT_ROOT / config.JSON_DIR_NAME

    log.info(f"Project root resolved to: {config.PROJECT_ROOT}")
    log.info(f"PDF directory set to: {pdf_dir}")
    log.info(f"JSON output directory set to: {json_dir}")

    if not pdf_dir.is_dir():
        log.error(f"PDF directory not found: {pdf_dir}. Please ensure it exists and contains PDF files.")
        return

    pdf_files = list(pdf_dir.glob('*.pdf'))
    if not pdf_files:
        log.warning(f"No PDF files found in {pdf_dir}")
        return

    log.info(f"Found {len(pdf_files)} PDF files to process in {pdf_dir}.")

    for filepath in pdf_files:
        process_single_pdf(
            pdf_filepath=filepath,
            json_output_dir=json_dir,
            genai_model_instance=pdf_extraction_model, # Pass the initialized model
            prompt=PROMPT_TEXT # model_name is no longer passed here
        )

    log.info("PDF to JSON conversion process finished.")

if __name__ == "__main__":
    print(f"Executing pdf_processor.py directly. Project root: {config.PROJECT_ROOT}")
    run_pdf_to_json_conversion()
