import os
import glob
import json
import logging
from pathlib import Path
from collections import defaultdict

from google import genai
from langchain.embeddings import OllamaEmbeddings
from langchain.vectorstores import Chroma

# -------- Konfiguration --------
JSON_INPUT_DIR = "json_output"
CHROMA_PERSIST_DIR = "chroma_db"
ARTICLE_OUTPUT_DIR = "articles"
LOG_FILE = "chroma_article.log"
EMBEDDING_MODEL = "nomic-embed-text"
SIMILARITY_THRESHOLD = 0.8
MODEL_NAME = "gemini-2.0-flash"

# -------- Logging --------
def configure_logging(log_file_path=LOG_FILE):
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        filename=log_file_path,
        filemode='a'
    )

# -------- Google GenAI Client --------
def initialize_genai_client():
    try:
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError("GOOGLE_API_KEY fehlt!")
        return genai.Client(api_key=api_key)
    except Exception as e:
        logging.error(f"Fehler beim Initialisieren des GenAI-Clients: {e}", exc_info=True)
        raise

# -------- Embedding- und Vektordatenbank-Initialisierung --------
def initialize_embedding():
    try:
        return OllamaEmbeddings(model=EMBEDDING_MODEL)
    except Exception as e:
        logging.error(f"Fehler beim Initialisieren der Embeddings: {e}", exc_info=True)
        raise

def initialize_chroma(embedding_func):
    try:
        return Chroma(
            embedding_function=embedding_func,
            persist_directory=CHROMA_PERSIST_DIR
        )
    except Exception as e:
        logging.error(f"Fehler beim Initialisieren von ChromaDB: {e}", exc_info=True)
        raise

# -------- Hilfsfunktionen --------
def get_json_files(folder_path=JSON_INPUT_DIR):
    os.makedirs(folder_path, exist_ok=True)
    return glob.glob(os.path.join(folder_path, "*.json"))

def load_records(json_file_path):
    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Fehler beim Laden der JSON-Datei {json_file_path}: {e}", exc_info=True)
        return []

def build_prompt(source_file: str, new_entries: list[dict], older_texts: list[str]) -> str:
    prompt_parts = []
    prompt_parts.append(f"Basierend auf dem folgenden Protokoll aus '{source_file}' sollen mehrere journalistische Artikel erstellt werden.\n")

    for idx, entry in enumerate(new_entries, 1):
        prompt_parts.append(f"### Neuer Eintrag {idx}:\nTOP: {entry['top']}\n{entry['inhalt']}\n")

    if older_texts:
        prompt_parts.append("Es wurden ältere, ähnliche Artikel gefunden, die zur Inspiration verwendet werden können, aber nicht müssen:\n")
        for idx, text in enumerate(older_texts, 1):
            prompt_parts.append(f"--- Älterer Artikel {idx} ---\n{text}\n")

    prompt_parts.append(
        "\nBitte analysiere die neuen Einträge und wähle die relevantesten oder interessantesten Themen (TOPs) für die Leserschaft aus. Verfasse anschließend mehrere journalistische Artikel, jeweils zu einem Thema. Die Artikel sollen informativ, klar und gut strukturiert sein."
    )

    return "\n".join(prompt_parts)

# -------- Hauptverarbeitung --------
def generate_articles():
    configure_logging()
    logging.info("Starte Artikelgenerierung aus ChromaDB...")

    try:
        genai_client = initialize_genai_client()
        embedding_func = initialize_embedding()
        vectordb = initialize_chroma(embedding_func)
        os.makedirs(ARTICLE_OUTPUT_DIR, exist_ok=True)
        json_files = get_json_files(JSON_INPUT_DIR)
    except Exception as e:
        logging.error(f"Initialisierungsfehler: {e}", exc_info=True)
        return

    for json_path in json_files:
        source = Path(json_path).name
        logging.info(f"Bearbeite Source-File: {source}")

        try:
            records = load_records(json_path)
            new_entries = []
            older_texts = []

            for rec in records:
                top = rec.get('top', '')
                inhalt = rec.get('inhalt', '')
                combined = f"{top}\n\n{inhalt}".strip()
                new_entries.append({"top": top, "inhalt": inhalt})

                try:
                    results = vectordb.similarity_search_with_score(combined, k=10)
                    for doc, score in results:
                        if score >= SIMILARITY_THRESHOLD and doc.metadata.get("source_file") == source:
                            older_texts.append(doc.page_content)
                except Exception as e:
                    logging.error(f"Fehler bei Similarity Search für Eintrag in {source}: {e}", exc_info=True)

            older_texts = list(dict.fromkeys(older_texts))

            prompt = build_prompt(source, new_entries, older_texts)
            logging.info(f"Generiere Prompt für {source}")

            try:
                response = genai_client.models.generate_content(
                    model=MODEL_NAME,
                    contents=prompt
                )
                article = response.text
            except Exception as e:
                logging.error(f"Fehler bei der Anfrage an Gemini für {source}: {e}", exc_info=True)
                continue

            try:
                md_path = Path(ARTICLE_OUTPUT_DIR) / f"{Path(source).stem}.md"
                with open(md_path, 'w', encoding='utf-8') as f:
                    f.write(f"# Artikel für {source}\n\n")
                    f.write(article)
                logging.info(f"Artikel gespeichert: {md_path}")
                print(f"Erstellt: {md_path}")
            except Exception as e:
                logging.error(f"Fehler beim Schreiben der Datei {md_path}: {e}", exc_info=True)

        except Exception as e:
            logging.error(f"Fehler bei der Verarbeitung von {source}: {e}", exc_info=True)

if __name__ == "__main__":
    generate_articles()