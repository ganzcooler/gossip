import configparser
import pathlib
import logging
import sys
from src import prompts

# Project root directory - assuming config.ini is in the parent directory of src/
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent

# Re-establish prompt variables from src.prompts
GENAI_JOURNALISTIC_ARTICLE_PROMPT = prompts.GENAI_JOURNALISTIC_ARTICLE_PROMPT
GENAI_TOPIC_SELECTION_PROMPT = prompts.GENAI_TOPIC_SELECTION_PROMPT

# --- Logging Configuration ---
LOG_FORMAT = '%(asctime)s %(levelname)s %(name)s: %(message)s'
DEFAULT_LOG_LEVEL = logging.INFO

# --- Directory Names ---
# These are relative to PROJECT_ROOT
PDF_DIR_NAME = "pdf_files"
CHROMA_DB_DIR_NAME = "chroma_db"
ARTICLES_DIR_NAME = "articles"

# --- Log File Names ---
# These are relative to PROJECT_ROOT in a "logs" subdirectory
LOG_DIR_NAME = "logs" # All logs will go into a "logs" subdirectory at project root
PDF_PROCESSING_LOG_FILENAME = LOG_DIR_NAME + "/pdf-processing.log"
CHROMA_DB_UTILS_LOG_FILENAME = LOG_DIR_NAME + "/chromadb-utils.log"
CHROMA_TO_ARTICLES_LOG_FILENAME = LOG_DIR_NAME + "/chroma-to-articles.log"
RELEVANCE_DETERMINER_LOG_FILENAME = LOG_DIR_NAME + "/relevance-determiner.log"
REFERENCE_FINDER_LOG_FILENAME = LOG_DIR_NAME + "/reference-finder.log"
ARTICLE_WRITER_LOG_FILENAME = LOG_DIR_NAME + "/article-writer.log"

# --- Model Names ---
GENAI_PDF_EXTRACTION_MODEL = "gemini-2.5-flash-preview-05-20"
OLLAMA_EMBEDDING_MODEL = "nomic-embed-text"
GENAI_ARTICLE_GENERATION_MODEL = "gemini-2.5-flash-preview-05-20"

# --- API Call Settings ---
DEFAULT_API_CALL_DELAY_SECONDS = 6

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
    logger = get_logger(__name__, PDF_PROCESSING_LOG_FILENAME) # Using an existing logger for now

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
    except configparser.NoOptionError:
        logger.warning(f"'API_CALL_DELAY_SECONDS' nicht in Sektion [genai] der Konfigurationsdatei gefunden: "
                       f"{config_file_path}. Verwende Standardwert: {DEFAULT_API_CALL_DELAY_SECONDS}s.")
        return DEFAULT_API_CALL_DELAY_SECONDS
    except ValueError:
        logger.warning(f"Ungültiger Wert für 'API_CALL_DELAY_SECONDS' in {config_file_path}. "
                       f"Muss eine Ganzzahl sein. Verwende Standardwert: {DEFAULT_API_CALL_DELAY_SECONDS}s.")
        return DEFAULT_API_CALL_DELAY_SECONDS

# --- ChromaDB Configuration ---
CHROMA_COLLECTION_NAME = "tops_content"

# --- Article Generation ---
SIMILAR_DOCS_COUNT = 2

# Helper function to get a configured logger
def get_logger(name, log_file_name_with_subdir, level=DEFAULT_LOG_LEVEL, project_root_path=PROJECT_ROOT, log_format=LOG_FORMAT):
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.handlers: # Avoid adding handlers multiple times
        log_file_path = project_root_path / log_file_name_with_subdir

        # Ensure the directory for the log file exists
        log_file_path.parent.mkdir(parents=True, exist_ok=True)

        fh = logging.FileHandler(log_file_path, encoding="utf-8")
        fh.setFormatter(logging.Formatter(log_format))
        logger.addHandler(fh)

        sh = logging.StreamHandler(sys.stdout) # Log to stdout for console output
        sh.setFormatter(logging.Formatter(log_format))
        logger.addHandler(sh)

    return logger
