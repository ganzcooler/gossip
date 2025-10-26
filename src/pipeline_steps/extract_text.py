import pathlib
import fitz  # PyMuPDF
import logging

def extract_text_from_pdf(pdf_filepath: pathlib.Path, logger: logging.Logger) -> str:
    """Extracts all text content from a PDF file using PyMuPDF."""
    try:
        doc = fitz.open(pdf_filepath)
        full_text = ""
        for page in doc:
            full_text += page.get_text()
        logger.info(f"Successfully extracted text from {pdf_filepath.name} using PyMuPDF.")
        return full_text
    except Exception as e:
        logger.error(f"Error extracting text from {pdf_filepath.name} using PyMuPDF: {e}", exc_info=True)
        return ""
