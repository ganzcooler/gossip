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

# --- Prompts ---
GENAI_JOURNALISTIC_ARTICLE_PROMPT = """
You are an AI assistant tasked with generating a journalistic article based on the provided content.
The article should have a clear title and a body. The tone should be engaging and suitable for a local news audience.
Do not include any reference to internal identifiers like TOP numbers in the article title or body.

Please return your response as a JSON object with the following structure:
{
  "article_title": "Your Generated Article Title",
  "article_body": "Your generated journalistic article body text here..."
}

Here is the content to transform:
---
{TOP_CONTENT}
---
"""

GENAI_TOPIC_SELECTION_PROMPT = """
You are an AI assistant. Your task is to evaluate a list of TOPs (Tagesordnungspunkte / agenda items) from a given protocol (meeting minutes) and decide for each TOP whether it is suitable for a journalistic article.
Base your decision on two main criteria:
1.  **Content Depth**: The TOP should provide enough substantial material for a compelling news story. Purely administrative points, very brief announcements, or items lacking detail are generally not suitable.
2.  **Public Interest/Engagement**: The TOP should offer opportunities to be presented in a way that is likely to engage a broader audience. This might include topics that are emotional, controversial, impactful on the community, or generally sensational.

You will be provided with input in JSON format, containing the protocol's 'title', 'datum' (date), and a list of 'tops'. Each item in the 'tops' list will have a 'top_id' (its original identifier in the protocol) and 'content' (the textual description of the TOP).

You must return a JSON object with the original 'title' and 'datum' fields from the input. Additionally, your output must include a field named 'tops_evaluation', which should be a list. This list must contain an entry for *every* TOP present in the input's 'tops' list. Each entry in 'tops_evaluation' must include the original 'top_id' and a new boolean field 'is_selected_relevant', which should be true if you deem the TOP suitable for an article according to the criteria, and false otherwise.

Here are a couple of examples:

**Example 1:**

Input:
```json
{
  "title": "Finance Committee Meeting",
  "datum": "2024-03-15",
  "tops": [
    {
      "top_id": "1.1",
      "content": "Approval of the minutes from the last meeting. The minutes were reviewed and approved without changes."
    },
    {
      "top_id": "1.2",
      "content": "Budget reallocation proposal for Q3. This involves shifting funds from the deferred park renovation project to the emergency road repair fund due to recent storm damage. Extensive discussion on the urgency and impact on other planned projects. Several local businesses voiced concerns over the park project delay."
    },
    {
      "top_id": "2.0",
      "content": "Update on software licensing renewals. Standard renewal process, no issues reported."
    }
  ]
}
```

Output:
```json
{
  "title": "Finance Committee Meeting",
  "datum": "2024-03-15",
  "tops_evaluation": [
    {
      "top_id": "1.1",
      "is_selected_relevant": false
    },
    {
      "top_id": "1.2",
      "is_selected_relevant": true
    },
    {
      "top_id": "2.0",
      "is_selected_relevant": false
    }
  ]
}
```

**Example 2:**

Input:
```json
{
  "title": "School Board Session",
  "datum": "2024-03-18",
  "tops": [
    {
      "top_id": "A",
      "content": "Presentation of the new anti-bullying campaign 'Safe Spaces Now'. Includes detailed plans for student workshops, parent information evenings, and teacher training modules. Statistics on bullying incidents from the past year were presented, showing a concerning rise. Discussion included a heartfelt testimony from a parent whose child was affected."
    },
    {
      "top_id": "B",
      "content": "Decision on the vendor for cafeteria supplies for the next school year. Three bids were reviewed, and Vendor X was selected based on cost and compliance with nutritional guidelines. Standard procurement procedure."
    }
  ]
}
```

Output:
```json
{
  "title": "School Board Session",
  "datum": "2024-03-18",
  "tops_evaluation": [
    {
      "top_id": "A",
      "is_selected_relevant": true
    },
    {
      "top_id": "B",
      "is_selected_relevant": false
    }
  ]
}
```
Now, evaluate the following input:
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
