# ⚗️ Automated Lab Safety Auditor

An intelligent, OSHA-compliant chemical formulation auditing system built on a hybrid **RAG + MCP + LLM + Pydantic** pipeline. Submit any lab formulation note in natural language and receive a structured compliance report in under 10 seconds — fully local, fully offline.

## Quick Start

```bash
# 1. Install dependencies
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt

# 2. Pull the local LLM
ollama pull llama3.2:1b

# 3. Ingest regulatory data into ChromaDB (one time)
python ingest.py

# 4. Launch the Gradio UI
python app.py
# → Open http://127.0.0.1:7860
```

## Documentation

| Document | Description |
|----------|-------------|
| [`docs/README.md`](docs/README.md) | Full architecture, configuration, pipeline flow, and setup guide |
| [`docs/DESIGN.md`](docs/DESIGN.md) | Complete implementation history — every decision, iteration, bug, and the reasoning behind the final design |

## How It Works

```
Free-form Lab Note
      │
      ▼ Regex extraction (chemicals + hardware)
      │
      ├──▶ ChromaDB (RAG): OSHA regulatory text per chemical
      │
      ├──▶ FastMCP Server: max safe temperature per equipment
      │
      ▼ Python compliance engine
      │    ├── % vol vs % vol limit (e.g. Benzene > 0.1% → REJECTED)
      │    ├── ppm vs ppm TWA limit
      │    ├── Liquid % vs airborne ppm: NOT compared → COMPLIANT
      │    └── Boiling point systemic hazard check → PARTIAL
      │
      ▼ LLM (60 tokens): one-sentence natural language summary
      │
      ▼ ComplianceReport (Pydantic)  →  Gradio UI
```

## Verdicts

| Status | Meaning |
|--------|---------|
| `✅ APPROVED` | All checks pass, no systemic hazards |
| `⚠️ PARTIAL` | Checks pass but systemic hazard detected (e.g. boiling point exceeded) |
| `❌ REJECTED` | Hard OSHA violation or hardware thermal limit exceeded |

## System Requirements

- Python 3.11+
- [Ollama](https://ollama.ai) (local LLM runtime)
- 8+ GB RAM (32 GB recommended for `llama3.2:3b` and above)
- No GPU required — runs entirely on CPU
