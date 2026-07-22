from chromadb import PersistentClient
from constants import CHROMA_PERSIST_DIR, CHROMA_COLLECTION_NAME, RAG_TOP_K
from cache import get_osha_limits

_client = PersistentClient(path=CHROMA_PERSIST_DIR)
_collection = _client.get_collection(name=CHROMA_COLLECTION_NAME)


def query_regulations(chemical_name: str) -> list[str]:
    cached = get_osha_limits(chemical_name)
    if cached:
        parts = []
        if "ppm" in cached:
            parts.append(f"{cached['ppm']} ppm TWA")
        if "pct" in cached:
            parts.append(f"{cached['pct']}% by volume")
        parts.append(f"Source: {cached.get('citation', 'SQLite cache')}")
        return [f"{chemical_name}: " + ", ".join(parts)]

    results = _collection.query(
        query_texts=[chemical_name],
        n_results=RAG_TOP_K
    )
    return results["documents"][0]
