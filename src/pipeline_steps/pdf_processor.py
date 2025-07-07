import pathlib
import sys
import fitz # PyMuPDF

# Ensure src directory is in sys.path for config import
project_root_for_import = pathlib.Path(__file__).resolve().parent.parent.parent
if str(project_root_for_import) not in sys.path:
    sys.path.insert(0, str(project_root_for_import))

try:
    from src import config
    from src.config import EXTRACTED_TEXTS_DIR_NAME # Import the new directory name
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

def run_pdf_text_extraction():
    log.info("Starting PDF text extraction process using PyMuPDF...")

    pdf_dir = config.PROJECT_ROOT / config.PDF_DIR_NAME
    log.info(f"Project root resolved to: {config.PROJECT_ROOT}")
    log.info(f"PDF directory set to: {pdf_dir}")

    # Define and create the directory for extracted texts
    extracted_texts_dir = config.PROJECT_ROOT / EXTRACTED_TEXTS_DIR_NAME
    try:
        extracted_texts_dir.mkdir(parents=True, exist_ok=True)
        log.info(f"Ensured directory for extracted texts exists: {extracted_texts_dir}")
    except OSError as e:
        log.error(f"Error creating directory for extracted texts {extracted_texts_dir}: {e}", exc_info=True)
        return # Cannot proceed if this directory cannot be created

    if not pdf_dir.is_dir():
        log.error(f"PDF directory not found: {pdf_dir}. Please ensure it exists and contains PDF files.")
        return

    pdf_files = list(pdf_dir.glob('*.pdf'))
    if not pdf_files:
        log.warning(f"No PDF files found in {pdf_dir}")
        return

    log.info(f"Found {len(pdf_files)} PDF files to process in {pdf_dir}.")

    processed_files_count = 0
    skipped_files_count = 0

    for filepath in pdf_files:
        extracted_text_filename = filepath.stem + ".txt"
        extracted_text_filepath = extracted_texts_dir / extracted_text_filename

        if extracted_text_filepath.exists():
            log.info(f"Skipping PDF '{filepath.name}': Extracted text file already exists at '{extracted_text_filepath}'.")
            skipped_files_count += 1
            continue

        log.info(f"Extracting text from PDF: {filepath.name}")
        extracted_text = extract_text_from_pdf_pymupdf(filepath)

        if extracted_text:
            try:
                with open(extracted_text_filepath, "w", encoding="utf-8") as f:
                    f.write(extracted_text)
                log.info(f"Successfully extracted text from '{filepath.name}' and saved to '{extracted_text_filepath}'. Length: {len(extracted_text)} characters.")
                processed_files_count += 1
            except IOError as e:
                log.error(f"Error writing extracted text for '{filepath.name}' to '{extracted_text_filepath}': {e}", exc_info=True)
        else:
            log.warning(f"Failed to extract text or empty text from {filepath.name}. No text file created.")

    log.info(f"PDF text extraction process finished. "
             f"Successfully processed and saved text for {processed_files_count} PDF files. "
             f"Skipped {skipped_files_count} PDF files (text file already existed).")

if __name__ == "__main__":
    print(f"Executing pdf_processor.py directly. Project root: {config.PROJECT_ROOT}")
    run_pdf_text_extraction()
    print(f"PDF processing finished. Check the '{EXTRACTED_TEXTS_DIR_NAME}' directory for output files.")
