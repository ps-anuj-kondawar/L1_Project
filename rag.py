from chromadb import PersistentClient
from constants import CHROMA_PERSIST_DIR, CHROMA_COLLECTION_NAME, RAG_TOP_K

_client = PersistentClient(path=CHROMA_PERSIST_DIR)
_collection = _client.get_collection(name=CHROMA_COLLECTION_NAME)


def query_regulations(chemical_name: str) -> list[str]:
    results = _collection.query(
        query_texts=[chemical_name],
        n_results=RAG_TOP_K
    )
    return results["documents"][0]
