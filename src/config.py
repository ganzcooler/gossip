import configparser
import pathlib
import logging
import sys
from src import prompts
from src import tags
from datetime import datetime

# Project root directory - assuming config.ini is in the parent directory of src/
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent

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


# --- Model Names ---
GENAI_ARTICLE_GENERATION_MODEL = "gemini-2.5-pro"
GENAI_IMAGE_GENERATION_MODEL = "imagen-3.0-generate-002"

# --- API Call Settings ---
API_CALL_DELAY_SECONDS = 10

# --- Article Tags ---
CATEGORY_TAGS = tags.CATEGORY_TAGS
LOCATION_TAGS = tags.LOCATION_TAGS

# --- API Key Loading ---
def load_google_api_key():
    """Loads Google API Key from config.ini located in the project root."""
    config_file_path = PROJECT_ROOT / "config.ini"
    if not config_file_path.exists():
        raise FileNotFoundError(f"Konfigurationsdatei nicht gefunden: {config_file_path}")

    config = configparser.ConfigParser()
    config.read(config_file_path)

    api_key = config.get("genai", "GOOGLE_API_KEY", fallback=None)
    if not api_key:
        raise ValueError(f"GOOGLE_API_KEY fehlt in der Konfigurationsdatei! (Pfad: {config_file_path})")
    return api_key
