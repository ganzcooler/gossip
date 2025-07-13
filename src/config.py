import configparser
import pathlib
import logging
import sys
from src import prompts
from src import tags

# Project root directory - assuming config.ini is in the parent directory of src/
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent

# Get prompt variables from src.prompts
GENAI_JOURNALISTIC_ARTICLE_PROMPT = prompts.GENAI_JOURNALISTIC_ARTICLE_PROMPT

# --- Logging Configuration ---
LOG_FORMAT = '%(asctime)s %(levelname)s %(name)s: %(message)s'
DEFAULT_LOG_LEVEL = logging.INFO

# --- Directory Names ---
# These are relative to PROJECT_ROOT
PDF_DIR_NAME = "pdf_files"
ARTICLES_DIR_NAME = "articles"
IMAGES_DIR_NAME = "generated_images"
LOG_DIR_NAME = "logs"

# --- Model Names ---
GENAI_ARTICLE_GENERATION_MODEL = "gemini-1.5-flash"
GENAI_IMAGE_GENERATION_MODEL = "imagen-3-flash-001" # As per request for "Image 4" - using latest available

# --- API Call Settings ---
DEFAULT_API_CALL_DELAY_SECONDS = 6

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

def load_api_call_delay():
    """
    Loads API_CALL_DELAY_SECONDS from the [genai] section of config.ini.
    Returns DEFAULT_API_CALL_DELAY_SECONDS if not found or invalid.
    """
    config_file_path = PROJECT_ROOT / "config.ini"

    # A simple logger for this function, in case the main logger isn't set up yet.
    logger = logging.getLogger(__name__)

    if not config_file_path.exists():
        logger.warning(f"Konfigurationsdatei nicht gefunden: {config_file_path}. "
                       f"Verwende Standard-API-Aufrufverzögerung: {DEFAULT_API_CALL_DELAY_SECONDS}s.")
        return DEFAULT_API_CALL_DELAY_SECONDS

    config = configparser.ConfigParser()
    config.read(config_file_path)

    try:
        delay_str = config.get("genai", "API_CALL_DELAY_SECONDS")
        delay_int = int(delay_str)
        return delay_int
    except (configparser.NoOptionError, ValueError):
        logger.warning(f"'API_CALL_DELAY_SECONDS' nicht gefunden oder ungültig in {config_file_path}. "
                       f"Verwende Standardwert: {DEFAULT_API_CALL_DELAY_SECONDS}s.")
        return DEFAULT_API_CALL_DELAY_SECONDS
