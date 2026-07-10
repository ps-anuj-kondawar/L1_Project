OLLAMA_MODEL = "llama3.2:1b"
LLM_TEMPERATURE = 0.0
MAX_OUTPUT_TOKENS = 1024

CHROMA_PERSIST_DIR = "./chroma_db"
CHROMA_COLLECTION_NAME = "regulatory_data"

RAG_DATA_PATH = "./data/regulatory_framework.txt"
RAG_TOP_K = 5

MCP_SERVER_SCRIPT = "mcp_server.py"

HARDWARE_LIMITS: dict[str, int] = {
    "soda-lime glass":        100,
    "borosilicate glass":     500,
    "stainless steel beaker": 600,
    "polypropylene container": 80,
}

BOILING_POINTS_CELSIUS: dict[str, float] = {
    "acetone":       56.0,
    "methanol":      65.0,
    "isopropanol":   82.0,
    "ipa":           82.0,
    "ethanol":       78.0,
    "toluene":      111.0,
    "benzene":       80.1,
}
