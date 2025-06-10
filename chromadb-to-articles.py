import os
import glob
import json
import logging
import configparser
from pathlib import Path

from google import genai
import ollama
import chromadb

# -------- Konfiguration --------
JSON_INPUT_DIR = "json_output"
CHROMA_PERSIST_DIR = "chroma_db"
ARTICLE_OUTPUT_DIR = "articles"
LOG_FILE = "chroma_article.log"
EMBEDDING_MODEL = "nomic-embed-text"
COLLECTION_NAME = "tops_content"
MODEL_NAME = "gemini-2.5-flash-preview-05-20"
SIMILAR_DOCS_COUNT = 2 

# -------- Logging --------
def configure_logging(log_file_path=LOG_FILE):
    """Konfiguriert das Logging für die Anwendung."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        filename=log_file_path,
        filemode='a'
    )

# -------- Google GenAI Client --------
def initialize_genai_client():
    """Initialisiert und gibt den Google GenAI Client zurück, basierend auf einer lokalen Konfigurationsdatei."""
    # Inhalt config.ini
    # [genai]
    # GOOGLE_API_KEY=dein_api_schlüssel_hier
    
    try:
        config_path = Path(__file__).parent / "config.ini"
        if not config_path.exists():
            raise FileNotFoundError(f"Konfigurationsdatei nicht gefunden: {config_path}")

        config = configparser.ConfigParser()
        config.read(config_path)

        api_key = config.get("genai", "GOOGLE_API_KEY", fallback=None)
        if not api_key:
            raise ValueError("GOOGLE_API_KEY fehlt in der Konfigurationsdatei!")

        return genai.Client(api_key=api_key)
    except Exception as e:
        logging.error(f"Fehler beim Initialisieren des GenAI-Clients: {e}", exc_info=True)
        raise

# -------- ChromaDB Client Initialisierung --------
def initialize_chroma_collection():
    """Initialisiert den ChromaDB Client und gibt die Collection zurück."""
    try:
        client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
        collection = client.get_or_create_collection(COLLECTION_NAME)
        return collection
    except Exception as e:
        logging.error(f"Fehler beim Initialisieren von ChromaDB: {e}", exc_info=True)
        raise

# -------- Hilfsfunktionen --------
def get_json_files(folder_path=JSON_INPUT_DIR):
    """Sucht und gibt alle JSON-Dateien in einem Ordner zurück."""
    os.makedirs(folder_path, exist_ok=True)
    return glob.glob(os.path.join(folder_path, "*.json"))

def load_records(json_file_path):
    """Lädt Datensätze aus einer JSON-Datei."""
    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Fehler beim Laden der JSON-Datei {json_file_path}: {e}", exc_info=True)
        return []

def build_prompt(source_file: str, new_entries: list[dict], older_texts: list[str]) -> str:
    """Erstellt den Prompt für die Gemini-API."""
    prompt_parts = [f"Basierend auf dem folgenden Protokoll aus '{source_file}' sollen mehrere journalistische Artikel erstellt werden.\n"]

    for idx, entry in enumerate(new_entries, 1):
        prompt_parts.append(f"### Neuer Eintrag {idx}:\nTOP: {entry['top']}\n{entry['inhalt']}\n")

    if older_texts:
        prompt_parts.append("Es wurden ältere, thematisch ähnliche Artikel aus anderen Quellen gefunden, die zur Inspiration verwendet werden können, aber nicht müssen:\n")
        for idx, text in enumerate(older_texts, 1):
            prompt_parts.append(f"--- Älterer Artikel {idx} ---\n{text}\n")

    prompt_parts.append(
        "\nBitte analysiere die neuen Einträge und wähle die relevantesten oder interessantesten Themen (TOPs) für die Leserschaft aus. Verfasse anschließend mehrere journalistische Artikel, jeweils zu einem Thema. Die Artikel sollen informativ, klar und gut strukturiert sein."
    )
    return "\n".join(prompt_parts)

# -------- Hauptverarbeitung --------
def generate_articles():
    """Hauptfunktion zur Generierung von Artikeln."""
    configure_logging()
    logging.info("Starte Artikelgenerierung aus ChromaDB...")

    try:
        genai_client = initialize_genai_client()
        chroma_collection = initialize_chroma_collection()
        os.makedirs(ARTICLE_OUTPUT_DIR, exist_ok=True)
        json_files = get_json_files(JSON_INPUT_DIR)
    except Exception as e:
        logging.critical(f"Kritischer Initialisierungsfehler, Skript wird beendet: {e}", exc_info=True)
        return

    for json_path in json_files:
        source = Path(json_path).name
        # Den Zieldateipfad für die Markdown-Datei erstellen
        md_path = Path(ARTICLE_OUTPUT_DIR) / f"{Path(source).stem}.md"
        
        # PRÜFUNG: Existiert der Artikel bereits?
        if md_path.exists():
            logging.info(f"Artikel {md_path} existiert bereits. Überspringe Verarbeitung von {source}.")
            print(f"Übersprungen (existiert bereits): {md_path}")
            continue

        logging.info(f"Bearbeite Quelldatei: {source}")
        
        try:
            records = load_records(json_path)
            if not records:
                logging.warning(f"Keine Datensätze in {source} gefunden. Überspringe Datei.")
                continue
                
            new_entries = []
            older_texts = []

            for rec in records:
                top = rec.get('top', '')
                inhalt = rec.get('inhalt', '')
                combined_text = f"{top}\n\n{inhalt}".strip()
                new_entries.append({"top": top, "inhalt": inhalt})

                if not combined_text:
                    continue

                try:
                    # Embedding für den aktuellen Eintrag erzeugen
                    embedding = ollama.embeddings(model=EMBEDDING_MODEL, prompt=combined_text)["embedding"]

                    # Ähnliche Dokumente aus ChromaDB abfragen
                    results = chroma_collection.query(
                        query_embeddings=[embedding],
                        n_results=SIMILAR_DOCS_COUNT,
                        include=["documents", "metadatas"]
                    )
                    
                    # Verarbeite die Ergebnisse
                    docs = results.get("documents")
                    metas = results.get("metadatas")
                    if docs and docs[0]:
                        for i in range(len(docs[0])):
                            doc_content = docs[0][i]
                            doc_meta = metas[0][i] if metas and metas[0] else {}
                            # LOGIK-ÄNDERUNG: Füge nur Texte hinzu, die NICHT aus derselben Quelldatei stammen.
                            if doc_meta.get("source_file") != source:
                                older_texts.append(doc_content)

                except Exception as e:
                    logging.error(f"Fehler bei der Ähnlichkeitssuche für Eintrag in {source}: {e}", exc_info=True)
            
            # Duplikate entfernen, Reihenfolge beibehalten
            older_texts = list(dict.fromkeys(older_texts))

            if not new_entries:
                logging.info(f"Keine neuen Einträge für {source} vorhanden. Überspringe Generierung.")
                continue

            prompt = build_prompt(source, new_entries, older_texts)
            logging.info(f"Generiere Prompt für {source} mit {len(new_entries)} neuen Einträgen und {len(older_texts)} Referenztexten.")

            try:
                # Anfrage an die Gemini API senden
                response = genai_client.models.generate_content(
                    model=MODEL_NAME,
                    contents=prompt
                )
                article = response.text
            except Exception as e:
                logging.error(f"Fehler bei der Anfrage an die Gemini-API für {source}: {e}", exc_info=True)
                continue

            try:
                # Artikel in eine Markdown-Datei schreiben
                with open(md_path, 'w', encoding='utf-8') as f:
                    f.write(f"# Artikel für {source}\n\n")
                    f.write(article if article is not None else "")
                logging.info(f"Artikel erfolgreich gespeichert: {md_path}")
                print(f"Artikel erstellt: {md_path}")
            except Exception as e:
                logging.error(f"Fehler beim Schreiben der Artikeldatei {md_path}: {e}", exc_info=True)

        except Exception as e:
            logging.error(f"Ein unerwarteter Fehler ist bei der Verarbeitung von {source} aufgetreten: {e}", exc_info=True)

if __name__ == "__main__":
    generate_articles()
