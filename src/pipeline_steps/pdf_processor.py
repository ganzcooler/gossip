import google.generativeai as genai
import pathlib
import json
import time
import logging
import sys
import uuid
from src.pipeline_steps import db_loader
import chromadb # For type annotation

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
log = config.get_logger(__name__, config.PDF_PROCESSING_LOG_FILENAME)

PROMPT_TEXT = """
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
              "content": "Erster Tagesordnungspunkt Inhalt, der sehr spannend ist und viele Details bietet."
            },
            {
              "top_id": "2",
              "content": "Zweiter Tagesordnungspunkt Inhalt, eher administrativ."
            }
          ]
        }
        """

# The get_top_relevance function was removed as its functionality is now integrated
# into the main PROMPT_TEXT used by process_single_pdf.

def process_single_pdf(pdf_filepath: pathlib.Path, genai_model_instance: genai.GenerativeModel, prompt: str, chroma_collection: chromadb.api.models.Collection.Collection):
    log.info(f"Attempting to process PDF: {pdf_filepath.name}")

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
            protocol_title = response_json.get('title', 'N/A')
            protocol_date = response_json.get('datum', 'N/A')
            tops_processed_count = 0
            if not isinstance(response_json.get('tops'), list):
                log.warning(f"No 'tops' list found or is not a list in response for {pdf_filepath.name}. Response: {str(response_json)[:300]}")
                return # Or handle as an error

            for top_item in response_json.get('tops', []):
                top_content = top_item.get('content')
                # 'top_id' from LLM is the original number/identifier within the protocol
                original_top_id = top_item.get('top_id')

                if not top_content or not original_top_id:
                    log.warning(f"Missing content or original_top_id for a TOP in {pdf_filepath.name}. Content: '{str(top_content)[:50]}...', Original TOP ID: {original_top_id}. Skipping this TOP.")
                    continue

                chroma_id = str(uuid.uuid4())
                metadata = {
                    "protocol_title": protocol_title,
                    "protocol_date": protocol_date,
                    "top_number": original_top_id # Store the original TOP number here
                }

                success = db_loader.add_top_to_chromadb(
                    top_id=chroma_id, # Use generated UUID for ChromaDB's unique ID
                    document=top_content,
                    metadata=metadata,
                    collection=chroma_collection
                )
                if success:
                    tops_processed_count += 1
            log.info(f"Processed and attempted to add {tops_processed_count} TOPs from {pdf_filepath.name} to ChromaDB.")
        else:
            log.error(f"No JSON response to process for {pdf_filepath.name} (either not received or parsing failed).")

    except Exception as e:
        log.error(f"Error during GenAI call or ChromaDB operations for {pdf_filepath.name}: {e}", exc_info=True)
    finally:
        log.info("Waiting for 6 seconds due to potential API rate limits...")
        time.sleep(6)


def run_pdf_extraction_and_storage():
    log.info("Starting PDF extraction and storage to ChromaDB process...")
    try:
        api_key = config.load_google_api_key()
        genai.configure(api_key=api_key)
        # Instantiate the model to be used for PDF extraction
        pdf_extraction_model = genai.GenerativeModel(config.GENAI_PDF_EXTRACTION_MODEL)
        log.info(f"GenAI model {config.GENAI_PDF_EXTRACTION_MODEL} initialized for PDF extraction.")
    except Exception as e:
        log.critical(f"CRITICAL: Error initializing GenAI (configuring or creating model): {e}", exc_info=True)
        return

    try:
        chroma_collection = db_loader.initialize_chroma_collection(
            db_path_name=config.CHROMA_DB_DIR_NAME,
            collection_name=config.CHROMA_COLLECTION_NAME,
            project_root=config.PROJECT_ROOT
        )
        log.info(f"ChromaDB collection '{config.CHROMA_COLLECTION_NAME}' initialized for PDF processing.")
    except Exception as e:
        log.critical(f"CRITICAL: Could not initialize ChromaDB for PDF processing: {e}", exc_info=True)
        return

    pdf_dir = config.PROJECT_ROOT / config.PDF_DIR_NAME
    log.info(f"Project root resolved to: {config.PROJECT_ROOT}")
    log.info(f"PDF directory set to: {pdf_dir}")

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
            genai_model_instance=pdf_extraction_model,
            prompt=PROMPT_TEXT,
            chroma_collection=chroma_collection
        )

    log.info("PDF extraction and storage to ChromaDB process finished.")

if __name__ == "__main__":
    print(f"Executing pdf_processor.py directly. Project root: {config.PROJECT_ROOT}")
    run_pdf_extraction_and_storage()
