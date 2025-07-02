import pathlib
import sys
import fitz # PyMuPDF

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

def extract_text_from_pdf_pymupdf(pdf_filepath: pathlib.Path) -> str:
    """
    Extracts all text content from a PDF file using PyMuPDF.
    """
    full_text = ""
    try:
        doc = fitz.open(pdf_filepath)
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            full_text += page.get_text()
        doc.close()
        log.info(f"Successfully extracted text from {pdf_filepath.name} using PyMuPDF.")
        return full_text
    except Exception as e:
        log.error(f"Error extracting text from {pdf_filepath.name} using PyMuPDF: {e}", exc_info=True)
        return "" # Return empty string on error

def run_pdf_text_extraction(): # Renamed from run_pdf_extraction_and_storage
    log.info("Starting PDF text extraction process using PyMuPDF...")

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

    all_extracted_texts = {} # To store extracted texts, filename -> text
    for filepath in pdf_files:
        # Modified call to process_single_pdf, it no longer needs genai model or chroma collection
        # process_single_pdf(pdf_filepath=filepath) # This was just logging

        log.info(f"Extracting text from PDF: {filepath.name}")
        extracted_text = extract_text_from_pdf_pymupdf(filepath)
        if extracted_text:
            all_extracted_texts[filepath.name] = extracted_text
            log.info(f"Successfully extracted text from {filepath.name}. Length: {len(extracted_text)} characters.")
            # Log a snippet for verification
        else:
            log.warning(f"Failed to extract text or empty text from {filepath.name}.")

    # At this point, all_extracted_texts dictionary holds the content of all PDFs.
    # This data would then be passed to the next step (article generation).
    # For now, we'll just log completion.
    log.info(f"PDF text extraction process finished. Extracted text from {len(all_extracted_texts)} PDF files.")

    return all_extracted_texts

if __name__ == "__main__":
    print(f"Executing pdf_processor.py directly. Project root: {config.PROJECT_ROOT}")
    # Example of how to run and see output, though it won't be fully integrated yet.
    extracted_data = run_pdf_text_extraction()
    if extracted_data:
        for filename, text_content in extracted_data.items():
            print(f"\n--- Content for {filename} (first 200 chars) ---")
            print(text_content[:200])
            print("--- End of content ---")
