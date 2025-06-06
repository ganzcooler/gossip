import chromadb
import ollama

PERSIST_DIRECTORY = "chroma_db"
COLLECTION_NAME = "tops_content"
EMBEDDING_MODEL = "nomic-embed-text"

def read_from_persistent_chromadb(persist_path: str, collection_name: str):
    client = chromadb.PersistentClient(path=persist_path)
    collection = client.get_or_create_collection(collection_name)

    # Beispiel-Query
    query = "Wie ist der Status des Planfeststellungsverfahrens für den Radweg zwischen Obernjesa und Dramfeld und gab es dazu Rückmeldungen?"
    # Embedding für die Query erzeugen
    embedding = ollama.embeddings(model=EMBEDDING_MODEL, prompt=query)["embedding"]

    # Ähnlichkeitssuche (top 3)
    results = collection.query(
        query_embeddings=[embedding],
        n_results=3,
        include=["documents", "metadatas", "distances"]
    )

    # Defensive: Prüfe, ob Ergebnisse vorhanden sind
    docs = results.get("documents")
    metas = results.get("metadatas")
    dists = results.get("distances")
    if not docs or not docs[0]:
        print("Keine ähnlichen Einträge gefunden.")
        return
    for i in range(len(docs[0])):
        doc = docs[0][i]
        meta = metas[0][i] if metas and metas[0] else None
        score = dists[0][i] if dists and dists[0] else None
        print(f"\nErgebnis {i + 1}:")
        print("Inhalt:", doc)
        print("Metadaten:", meta)
        print(f"Distanz (kleiner = besser): {score:.4f}" if score is not None else "Distanz: n/a")

if __name__ == "__main__":
    read_from_persistent_chromadb(PERSIST_DIRECTORY, COLLECTION_NAME)
