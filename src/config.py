import configparser
import pathlib
import logging
import sys

# Project root directory - assuming config.ini is in the parent directory of src/
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent

# --- Logging Configuration ---
LOG_FORMAT = '%(asctime)s %(levelname)s %(name)s: %(message)s'
DEFAULT_LOG_LEVEL = logging.INFO

# --- Directory Names ---
# These are relative to PROJECT_ROOT
PDF_DIR_NAME = "pdf_files"
JSON_DIR_NAME = "json-files"
FILTERED_JSON_DIR_NAME = "filtered_json_files"
CHROMA_DB_DIR_NAME = "chroma_db"
ARTICLES_DIR_NAME = "articles"

# --- Log File Names ---
# These are relative to PROJECT_ROOT in a "logs" subdirectory
LOG_DIR_NAME = "logs" # All logs will go into a "logs" subdirectory at project root
PDF_TO_JSON_LOG_FILENAME = LOG_DIR_NAME + "/pdf-to-json.log"
JSON_TO_CHROMA_LOG_FILENAME = LOG_DIR_NAME + "/json-to-chroma.log"
CHROMA_TO_ARTICLES_LOG_FILENAME = LOG_DIR_NAME + "/chroma-to-articles.log"

# --- Model Names ---
GENAI_PDF_EXTRACTION_MODEL = "gemini-2.5-flash-preview-05-20"
OLLAMA_EMBEDDING_MODEL = "nomic-embed-text"
GENAI_ARTICLE_GENERATION_MODEL = "gemini-2.5-flash-preview-05-20"

# --- Prompts ---
GENAI_TOPIC_SELECTION_PROMPT = """
You are an AI assistant tasked with selecting agenda items (TOPs) suitable for creating journalistic articles.
From the provided list of TOPs, select only those that:
1. Provide enough substantial material for a compelling news story.
2. Offer opportunities to be presented in an emotional or sensational way, likely to engage a broader audience.

Respond with a JSON object that mirrors the structure of the input protocol, but only includes the TOPs you have selected.
The JSON output should look like this:
{
  "title": "Original Title from Input",
  "datum": "Original Date from Input",
  "tops": [
    {
      "top_id": "Selected TOP ID 1",
      "content": "Content of Selected TOP ID 1"
    },
    {
      "top_id": "Selected TOP ID 2",
      "content": "Content of Selected TOP ID 2"
    }
    // ... more selected TOPs
  ]
}
If no TOPs meet the criteria, return an empty "tops" list.
Do not include TOPs that are purely administrative, very brief, or lack broader public interest according to the criteria.
"""

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
