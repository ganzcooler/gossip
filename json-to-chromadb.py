import os
import glob
import json
import logging
from pathlib import Path

from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma

# -------- Konfiguration --------
JSON_INPUT_DIR = "json-files"
CHROMA_PERSIST_DIR = "chroma_db"
LOG_FILE = "chroma_store.log"
EMBEDDING_MODEL = "nomic-embed-text"
COLLECTION_NAME = "tops_content"

# -------- Logging --------
def configure_logging(log_file_path=LOG_FILE):
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        filename=log_file_path,
        filemode='a'
    )

# -------- Embedding- und Vektordatenbank-Initialisierung --------
def initialize_embedding():
    return OllamaEmbeddings(model=EMBEDDING_MODEL)

def initialize_chroma(embedding_func):
    return Chroma(
        embedding_function=embedding_func,
        persist_directory=CHROMA_PERSIST_DIR,
        collection_name=COLLECTION_NAME
    )

# -------- JSON-Verarbeitung --------
def get_json_files(folder_path=JSON_INPUT_DIR):
    os.makedirs(folder_path, exist_ok=True)
    return glob.glob(os.path.join(folder_path, "*.json"))

def load_records(json_file_path):
    with open(json_file_path, 'r', encoding='utf-8') as f:
        return json.load(f)

# -------- Hauptverarbeitung --------
def store_json_in_chroma():
    configure_logging()
    logging.info("Starte Speicherung in ChromaDB...")

    # Embeddings-Client und Vektordatenbank initialisieren
    embedding_func = initialize_embedding()
    vectordb = initialize_chroma(embedding_func)

    # JSON-Dateien einlesen
    json_files = get_json_files(JSON_INPUT_DIR)
    total_added = 0

    for json_path in json_files:
        logging.info(f"Verarbeite JSON-Datei: {json_path}")
        try:
            data = load_records(json_path)
            texts = []
            metadatas = []

            # Anpassung an das neue JSON-Format
            title = data.get('title', '')
            datum = data.get('datum', '')
            tops = data.get('tops', [])
            for top in tops:
                top_id = top.get('top_id', '')
                content = top.get('content', '')
                texts.append(f"{content}".strip())
                metadatas.append({
                    'title': title,
                    'datum': datum,
                    'top_id': top_id,
                    'source_file': os.path.basename(json_path)
                })

            if texts:
                vectordb.add_texts(texts=texts, metadatas=metadatas)
                added = len(texts)
                total_added += added
                logging.info(f"Hinzugefügt {added} Einträge aus {json_path}")
            else:
                logging.info(f"Keine Einträge in {json_path} gefunden.")

        except Exception as e:
            logging.error(f"Fehler beim Verarbeiten von {json_path}: {e}", exc_info=True)

    logging.info(f"Speicherung abgeschlossen. Insgesamt hinzugefügt: {total_added} Einträge.")

if __name__ == "__main__":
    store_json_in_chroma()
