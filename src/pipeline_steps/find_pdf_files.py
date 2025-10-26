import logging
from typing import List
import pathlib
from src import config

def find_pdf_files(logger: logging.Logger) -> List[pathlib.Path]:
    """Finds all PDF files in the configured PDF directory."""
    pdf_dir = config.PROJECT_ROOT / config.PDF_DIR_NAME
    if not pdf_dir.is_dir():
        logger.error(f"PDF directory not found: {pdf_dir}")
        return []

    pdf_files = list(pdf_dir.glob('*.pdf'))
    if not pdf_files:
        logger.warning(f"No PDF files found in {pdf_dir}")
        return []
    
    logger.info(f"Found {len(pdf_files)} PDF file(s) to process.")
    return pdf_files
