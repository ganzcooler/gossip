import os
import pathlib
import logging
import sys
from dotenv import load_dotenv
from src import prompts
from datetime import datetime

# Project root directory
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent

# Load environment variables from .env file
load_dotenv(PROJECT_ROOT / ".env")

# Get prompt variables from src.prompts
GENAI_JOURNALISTIC_ARTICLE_PROMPT = prompts.GENAI_JOURNALISTIC_ARTICLE_PROMPT

# --- Logging Configuration ---
LOG_FORMAT = '%(asctime)s %(levelname)s %(name)s: %(message)s'
DEFAULT_LOG_LEVEL = logging.INFO
LOG_DIR_NAME = "logs"

def get_log_filename():
    """Returns a log filename with a timestamp."""
    return f"pipeline-run-{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log"

# --- Directory Names ---
# These are relative to PROJECT_ROOT
PDF_DIR_NAME = "pdf_files"
ARTICLES_DIR_NAME = "articles"
IMAGES_DIR_NAME = "generated_images"
INSTA_IMAGES_DIR_NAME = "insta_images"


# --- Model Names ---
GENAI_ARTICLE_GENERATION_MODEL = "gemini-2.5-pro"
GENAI_IMAGE_PROMPT_MODEL = "gemini-2.5-flash"
GENAI_IMAGE_GENERATION_MODEL = "imagen-3.0-generate-002"

# --- API Call Settings ---
API_CALL_DELAY_SECONDS = 1

# --- API Key Loading ---
def load_google_api_key():
    """Loads the Google API Key from the .env file in the project root."""
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY not found in .env file or environment variables.")
    return api_key
