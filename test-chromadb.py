from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma

PERSIST_DIRECTORY = "chroma_db"
COLLECTION_NAME = "tops_content"
EMBEDDING_MODEL = "nomic-embed-text"

def read_from_persistent_chromadb(persist_path: str, collection_name: str):
    embedding_func = OllamaEmbeddings(model=EMBEDDING_MODEL)

    chroma_db = Chroma(
        embedding_function=embedding_func,
        persist_directory=persist_path,
        collection_name=collection_name
        )
    
    results = chroma_db.similarity_search_with_score(
        query="Die Inbetriebnahme der Kindertagesstätte wäre gut zu wissen. Wann kann dies passieren? Was ist mit den Fertigstellungsarbeiten, sind diese gehindert?",
        k=3
    )

    for i, (doc, score) in enumerate(results):
        print(f"\nErgebnis {i + 1}:")
        print("Inhalt:", doc.page_content)
        print("Metadaten:", doc.metadata)
        print(f"Ähnlichkeitsscore (kleiner = besser): {score:.4f}")

if __name__ == "__main__":
    read_from_persistent_chromadb(PERSIST_DIRECTORY, COLLECTION_NAME)
