# ⚗️ Automated Lab Safety Auditor

An intelligent, OSHA-compliant chemical formulation auditing system built on a hybrid **RAG + MCP + LLM + Pydantic** pipeline. Submit any lab formulation note in natural language and receive a structured compliance report in under 10 seconds — fully local, fully offline.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Pipeline Flow](#pipeline-flow)
- [Project Structure](#project-structure)
- [Configuration](#configuration)
- [Setup & Running](#setup--running)
- [Test Cases](#test-cases)
- [Documentation History](#documentation-history)

---

## Overview

The Lab Safety Auditor evaluates chemical formulation notes against OSHA regulatory limits and hardware safety thresholds. It produces a structured report with three possible verdicts:

| Status | Meaning |
|--------|---------|
| `✅ APPROVED` | All chemical concentrations and hardware temperatures are within safe limits. No systemic hazards detected. |
| `⚠️ PARTIAL` | Individual chemicals and hardware pass, but a systemic/environmental hazard exists (e.g., solvent heated above its boiling point). |
| `❌ REJECTED` | A hard OSHA violation (e.g., Benzene > 0.1% by volume) or hardware thermal limit exceeded. |

---

## Architecture

The system follows a **4-layer hybrid pipeline** architecture:

```
User Input (Free-form text)
        │
        ▼
┌─────────────────────────────┐
│  1. Regex Entity Extraction │  ← deterministic, <0.01s
│  Chemicals + Concentrations │
│  Hardware + Temperatures    │
└──────────────┬──────────────┘
               │
       ┌───────┴───────┐
       ▼               ▼
┌─────────────┐   ┌──────────────┐
│ 2. RAG      │   │ 3. MCP Tool  │
│ ChromaDB    │   │ HW Thermal   │
│ OSHA lookup │   │ Safety Check │
│ per chemical│   │ per equipment│
└──────┬──────┘   └──────┬───────┘
       │                 │
       └────────┬────────┘
                ▼
┌──────────────────────────────────┐
│  4. Python Compliance Engine     │  ← deterministic rules
│  - ppm vs ppm comparison         │
│  - % volume vs % volume limit    │
│  - Volume% vs ppm: NOT compared  │
│  - Boiling point systemic check  │
└──────────────────────────────────┘
                │
                ▼
┌──────────────────────────────────┐
│  5. LLM Summary (llama3.2:1b)   │  ← 60 tokens only, ~3-5s
│  One-sentence safety finding     │
└──────────────────────────────────┘
                │
                ▼
        ComplianceReport (Pydantic)
```

**Key design choice**: The LLM is used **only** for the final natural-language summary. All evaluation logic (compliance checks, status determination) is done deterministically in Python, powered by RAG-retrieved OSHA data and MCP-verified hardware limits. This achieves sub-10-second response times on CPU-only hardware.

---

## Pipeline Flow

### Step 1 — Regex Entity Extraction
`agent.py :: _extract_chemicals()` and `_extract_hardware()`

Four regex patterns detect chemicals and concentrations in any free-form text format:
- `6% Benzene` (number+unit+name)
- `300 ppm Toluene` (number+unit+name)
- `Acetone: 50% by volume` (name:number+unit)
- `Benzene: 600 ppm` (name:number+unit)

Hardware is matched case-insensitively against the `HARDWARE_LIMITS` dictionary. Operating temperature is parsed from patterns like `120C`, `85°C`, `22 celsius`.

### Step 2 — RAG Chemical Lookup
`rag.py :: query_regulations()` → ChromaDB

For each extracted chemical, the system queries ChromaDB for the single most relevant OSHA regulatory chunk. The top-1 result is used exclusively to prevent cross-chemical contamination (e.g., Benzene's 0.1% volume limit must not be applied to Isopropanol queries).

Regulatory limits are then parsed from the retrieved text using regex:
- `(\d+)\s*ppm\s*TWA` → airborne ppm limit
- `(\d+(?:\.\d+)?)%\s*by volume` → liquid volume limit

### Step 3 — MCP Hardware Check
`mcp_server.py` (FastMCP server via stdio transport)

The `check_hardware_compatibility` tool receives the equipment name and target temperature and returns `is_safe`, `max_safe_temperature_celsius`. The agent calls this tool over a subprocess stdio connection. If the MCP call fails, a safe local fallback uses the same `HARDWARE_LIMITS` dictionary.

### Step 4 — Compliance Engine
`agent.py :: _check_chemical()` and `_check_boiling_hazards()`

The compliance engine applies the following rules:

**Chemical Compliance:**
- If a chemical has a `% by volume` OSHA limit AND the detected concentration is in `%`: compare directly.
- If a chemical only has a `ppm TWA` limit AND the detected concentration is in `%`: mark **COMPLIANT** — liquid volume percentages are not comparable to airborne vapor limits.
- If concentration is in `ppm` AND limit is in `ppm`: compare directly.

**Systemic Hazard Detection:**
- The `BOILING_POINTS_CELSIUS` dictionary is checked for every chemical present.
- If the target operating temperature exceeds any chemical's boiling point, a systemic vapor pressure hazard is reported.
- This triggers a `PARTIAL` status even if individual checks pass.

**Status Logic:**
- `REJECTED` if any chemical OR hardware fails its check.
- `PARTIAL` if all checks pass but boiling point hazards detected.
- `APPROVED` only if all checks clear.

### Step 5 — LLM Summary
`agent.py :: _async_pipeline()`

Violations are passed to `llama3.2:1b` as a bullet list. The model is instructed to produce a **single sentence** summary (limited to 60 tokens). This is the only LLM call in the pipeline. Keeping output extremely short is what makes the system fast on CPU-only hardware.

---

## Project Structure

```
L1_Project/
├── app.py               # Gradio UI — input form, result cards, audit runner
├── agent.py             # Core pipeline — extraction, RAG, MCP, compliance, LLM
├── constants.py         # All configurable values (model, limits, boiling points, paths)
├── models.py            # Pydantic schemas — ComplianceReport, ChemicalFlag, HardwareFlag
├── rag.py               # ChromaDB query wrapper
├── ingest.py            # One-time script to embed regulatory_framework.txt into ChromaDB
├── mcp_server.py        # FastMCP server exposing check_hardware_compatibility tool
├── test_formulations.py # Automated test harness for all scenarios
├── data/
│   └── regulatory_framework.txt   # Source OSHA regulatory text (Benzene, Acetone, etc.)
├── chroma_db/           # Persisted ChromaDB vector store (git-ignored)
├── docs/
│   └── DESIGN.md        # Full implementation history and decision log
└── requirements.txt
```

---

## Configuration

All tunable parameters live in [`constants.py`](constants.py):

| Constant | Default | Description |
|----------|---------|-------------|
| `OLLAMA_MODEL` | `llama3.2:1b` | Local Ollama model used for summary generation |
| `LLM_TEMPERATURE` | `0.0` | Deterministic LLM output |
| `MAX_OUTPUT_TOKENS` | `1024` | Max tokens (overridden per call in agent) |
| `CHROMA_PERSIST_DIR` | `./chroma_db` | ChromaDB storage path |
| `CHROMA_COLLECTION_NAME` | `regulatory_data` | ChromaDB collection name |
| `RAG_DATA_PATH` | `./data/regulatory_framework.txt` | Source regulatory document |
| `RAG_TOP_K` | `5` | Documents returned per RAG query (only top-1 used for parsing) |
| `MCP_SERVER_SCRIPT` | `mcp_server.py` | Path to the FastMCP server script |
| `HARDWARE_LIMITS` | dict | Equipment names → max safe temperatures (°C) |
| `BOILING_POINTS_CELSIUS` | dict | Chemical names → boiling points (°C) for systemic hazard detection |

**To add a new chemical**: Add OSHA regulatory text to `data/regulatory_framework.txt` and re-run `ingest.py`.

**To add new hardware**: Add an entry to `HARDWARE_LIMITS` in `constants.py` — it will be automatically picked up by both the regex extractor and the MCP server.

**To upgrade the LLM**: Change `OLLAMA_MODEL` to any model available in your local Ollama installation (e.g., `llama3.1:8b` for GPU systems).

---

## Setup & Running

### Prerequisites
- Python 3.11+
- [Ollama](https://ollama.ai) installed and running
- `llama3.2:1b` model pulled: `ollama pull llama3.2:1b`

### Installation

```bash
# 1. Create a virtual environment and install dependencies
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt

# 2. Pull the local LLM
ollama pull llama3.2:1b
```

### Ingest Regulatory Data (one time)

```bash
python ingest.py
```

### Launch the UI

```bash
python app.py
```

Open `http://127.0.0.1:7860` in your browser.

### Run Tests

```bash
python test_formulations.py
```

---

## Test Cases

The system is validated against three canonical scenarios:

| Case | Input | Expected | Reason |
|------|-------|----------|--------|
| **REJECTED** | 6% Benzene at 120°C in soda-lime glass | `REJECTED` | Benzene > 0.1% vol limit; glass max is 100°C |
| **APPROVED** | 70% Isopropanol at 22°C in polypropylene | `APPROVED` | Volume % not comparable to ppm TWA; container and temp safe |
| **PARTIAL** | 50% Acetone + 50% Methanol at 85°C in borosilicate | `PARTIAL` | Hardware safe, but Acetone bp=56°C and Methanol bp=65°C both exceeded |

All three pass in **3–8 seconds** on an Intel i7-10810U (CPU-only, 32 GB RAM).

---

## Documentation History

| Document | Description |
|----------|-------------|
| [`docs/DESIGN.md`](docs/DESIGN.md) | Complete implementation history — every decision, iteration, bug, and the reasoning behind the final design |
