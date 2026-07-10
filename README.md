# Automated Lab Safety Auditor

An AI-powered compliance analysis tool that audits chemical formulation notes against OSHA regulatory limits using a full production-grade pipeline: **RAG → MCP → LLM → Pydantic Validation**.

---

## Quick Start

```bash
# Step 0: Install dependencies
pip install -r requirements.txt

# Step 1: Build the vector database (ONE TIME ONLY)
python ingest.py

# Step 2: Launch the app (every time)
streamlit run app.py
```

---

## Architecture

```
User Input (Streamlit)
        │
        ▼
┌─────────────────────────────────────┐
│  agent.py — run_audit_pipeline()    │
│                                     │
│  Phase 1: RAG (ChromaDB)            │
│  Phase 2: MCP (hardware server)     │
│  Phase 3: LLM (Ollama qwen2.5:3b)   │
│  Phase 4: Pydantic Validation       │
└─────────────────────────────────────┘
        │
        ▼
Streamlit UI — Structured Report
```

## Pipeline Concepts

| Component | Concept Demonstrated |
|---|---|
| `constants.py` | Tokens & Parameters (temperature=0.0, max_tokens=1024) |
| `rag.py` + `ingest.py` | Vector DB Pipeline (Chunk → Embed → Store → Retrieve) |
| `agent.py` system prompt | System Prompting + Guardrails |
| `mcp_server.py` + MCP client in `agent.py` | Agentic Tool Use / MCP |
| `models.py` `source_citation` field | Grounded, Cited Deliverables |
| `RAG_TOP_K = 3` | Context Window Management |

## Test Case

Input:
```
Formula B: 94% Water, 6% Benzene. Heat the mixture to 120°C in a soda-lime glass beaker.
```

Expected output: `REJECTED`
- Benzene at 6% vastly exceeds the 0.1% max / 1 ppm TWA OSHA limit
- Soda-lime glass max safe temp is 100°C, target is 120°C → unsafe

## File Structure

```
L1_Project/
├── requirements.txt          ← pinned dependencies
├── constants.py              ← Single Source of Truth for all config
├── models.py                 ← Pydantic v2 output schemas
├── ingest.py                 ← One-time RAG data ingestion
├── rag.py                    ← ChromaDB query module
├── mcp_server.py             ← MCP server (hardware thermal limits)
├── agent.py                  ← LLM orchestration engine
├── app.py                    ← Streamlit UI
├── data/
│   └── regulatory_framework.txt   ← OSHA-style regulatory text (5 chemicals)
└── docs/
    ├── SRS.md                ← System Requirements Specification
    ├── implementation_plan.md ← Full engineering blueprint
    └── idea.md               ← Original project proposal
```

## Dependencies

| Library | Version | Role |
|---|---|---|
| chromadb | 0.5.3 | Vector database for RAG |
| pydantic | 2.7.1 | Output schema validation |
| streamlit | 1.35.0 | Web UI |
| ollama | 0.2.1 | Local LLM inference |
| mcp | 1.0.0 | Model Context Protocol SDK |
| sentence-transformers | 2.7.0 | Embedding model (all-MiniLM-L6-v2) |
