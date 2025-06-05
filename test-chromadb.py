import chromadb
import os

PERSIST_DIRECTORY = "./chroma_db"
COLLECTION_NAME = "langchain"

def read_from_persistent_chromadb(persist_path: str, collection_name: str):
    client = chromadb.PersistentClient(path=persist_path)
    collection = client.get_collection(name=collection_name)

    results_get = collection.get(
        include=["documents", "metadatas", "embeddings"]
    )

    example_query_texts = ["ein relevantes Thema", "eine andere Suchanfrage"]
    results_query = collection.query(
        query_texts=example_query_texts,
        n_results=2,
        include=["documents", "metadatas", "distances"]
    )

if __name__ == "__main__":
    read_from_persistent_chromadb(PERSIST_DIRECTORY, COLLECTION_NAME)
