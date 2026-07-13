> [!WARNING]
> **Historical Document:** This is the original SRS (v5.0) written before the final architectural changes. The system design evolved to solve performance bottlenecks and hallucination issues. 
> Please refer to [`DESIGN.md`](DESIGN.md) for the actual implemented architecture and decision log.

# Software Requirements Specification (SRS) & Master Blueprint
**Project:** Automated Lab Safety Auditor
**Version:** 5.0 (Historical)
**Last Updated:** 2026-07-09

---

## 1. Introduction & Scope

**Purpose:** This document is the absolute Source of Truth for the Automated Lab Safety Auditor
capstone project. Every decision below includes the *reasoning*, *tradeoffs considered*, and
the *thought process* that led to the final choice. This is written so that a newcomer can
read it and understand not just *what* was built, but *why*.

**Objective:** Build an automated compliance pipeline that processes raw chemical formulation
notes and audits them against:
1. Environmental regulations — using **Retrieval-Augmented Generation (RAG)**
2. Laboratory hardware thermal limits — via a genuine **Model Context Protocol (MCP)** server

**Example Input:**
> "Formula B: 94% Water, 6% Benzene. Heat to 120°C in a soda-lime glass beaker."

**Expected Output:** A structured JSON compliance report flagging the Benzene violation
(OSHA PEL: 1 ppm TWA) and the beaker thermal violation (max safe: 100°C), with citations.

---

## 2. Stakeholders

- **Primary Developer:** The mentee building the L1 Capstone project.
- **Mentor (Harsh):** Reviewing architectural decisions and project trajectory.
- **Course Evaluators:** Assessing demonstration of the 5 core LLM course concepts.

---

## 3. Course Concept Coverage Map

Every file in this project maps directly to a course module. This table is the proof.

| # | Course Concept | Where Demonstrated | File(s) |
|---|---|---|---|
| 1 | Tokens & Parameters | temperature=0.0 pinned, max_output_tokens=1024 explicitly set & commented | constants.py, agent.py |
| 2 | Context Windows | Only TOP_K=3 RAG chunks injected — controlled context budget | constants.py, agent.py |
| 3 | System Prompting & Guardrails | Strict compliance-officer persona + zero-guessing + parameter enforcement rules | agent.py |
| 4 | Vector DB Pipeline (Chunk?Embed?Retrieve) | Paragraph chunking, all-MiniLM-L6-v2 embedding, ChromaDB PersistentClient | ingest.py, rag.py |
| 5 | Agentic Tool Integration / MCP | Genuine MCP server + MCP client over stdio | mcp_server.py, agent.py |
| 6 | Grounded, Cited Output | Mandatory source_citation field in Pydantic schema — cannot be omitted | models.py |

---

## 4. Technology Stack — Every Decision, Its Reasoning & Tradeoffs

---

### 4.1 LLM Runtime: Ollama with qwen2.5:3b

**Decision:** Run the LLM locally using Ollama with the qwen2.5:3b model.

**Why Ollama instead of Google Gemini API or OpenAI API?**

We started this project using the Google Gemini API (gemini-2.5-flash). We moved away
from it for the following concrete reasons:

| Factor | Cloud API (Gemini/OpenAI) | Ollama (Local) |
|---|---|---|
| API Key | Required — setup friction | Not needed |
| Data Privacy | Formulation data sent to Google servers | Stays on your machine |
| Network | Latency on every call | Zero — runs in RAM |
| Cost | Token billing | Free forever |
| Demo Risk | API outage = demo fails | No external dependency |

The tradeoff we accepted: a local 3B model has less raw reasoning power than Gemini 2.5 Flash.
However, for a structured, deterministic compliance task (not open-ended reasoning),
this gap is closed entirely by setting temperature=0.0 and using a strict system prompt.

**Why qwen2.5:3b specifically, not gemma2:2b or llama3.2:3b?**

Tool calling (required for MCP) is not supported by all models equally:
- gemma2:2b — has inconsistent tool calling support in Ollama. Rejected.
- llama3.2:3b — supports tool calling, good alternative.
- qwen2.5:3b — strong tool calling + strong JSON formatting + strong instruction following.

qwen2.5:3b is the safest choice for a project where tool calling is a hard requirement.
The 3b size runs comfortably on any laptop with 8GB RAM, on CPU alone.

---

### 4.2 Vector Database: ChromaDB PersistentClient

**Decision:** ChromaDB with PersistentClient (data saved to disk at ./chroma_db/).

**Why ChromaDB instead of FAISS?**

Both are local vector databases. The difference is developer experience:
- FAISS requires you to manually handle numpy arrays, serialize/deserialize indexes to files,
  and manage embedding separately. It is lower-level.
- ChromaDB wraps all of that: it has collections, a built-in embedding function,
  and a clean query() API. Less boilerplate = less chance of bugs in a demo.

Tradeoff accepted: ChromaDB installs ~100MB of dependencies vs FAISS being lighter.
Acceptable for this project.

**Why PersistentClient instead of the original EphemeralClient (in-memory)?**

The original plan used in-memory (ephemeral) ChromaDB. This means: every time app.py
starts, it re-reads regulatory_framework.txt, re-chunks it, and re-embeds every chunk.
This adds 5-15 seconds of startup time and recomputes work that does not change.

PersistentClient runs ingest.py ONCE. It saves the embedded vectors to disk.
Every subsequent app.py launch loads them instantly from disk — zero recomputation.

This is the architecturally correct pattern: build the index once, query it many times.
It also cleanly separates the "build" phase from the "query" phase, which is a real
data engineering concept worth demonstrating.

---

### 4.3 Embedding Model: ChromaDB Default (all-MiniLM-L6-v2)

**Decision:** Use ChromaDB's built-in default embedding function, which uses the
all-MiniLM-L6-v2 model from the sentence-transformers library.

**Why this model?**
- 80MB download, runs entirely on CPU — no GPU needed.
- 384-dimensional embeddings — sufficient for short regulatory text paragraphs.
- Downloaded automatically by ChromaDB on first use. No manual setup.
- After the first download, it runs 100% offline.

**Why not use Ollama's nomic-embed-text embedding model?**
- nomic-embed-text would keep everything inside Ollama (one tool for LLM + embeddings).
  That is cleaner architecturally.
- However, it requires a separate "ollama pull nomic-embed-text" command, adds complexity
  to ingest.py, and changes the ChromaDB embedding function setup.
- The tradeoff favours simplicity. all-MiniLM-L6-v2 is the default and works correctly.

**Why this matters for course evaluation:**
The "Embed" step in the "Chunk ? Embed ? Retrieve" pipeline is not magic.
all-MiniLM-L6-v2 is the specific model converting text into vectors.
Being able to name it and explain it shows you understand the pipeline, not just that
you copied code that happened to work.

---

### 4.4 Tool Integration: Genuine MCP (Model Context Protocol)

**Decision:** Build a real MCP server (mcp_server.py) using the official mcp Python SDK,
with the agent (agent.py) acting as a genuine MCP client over stdio.

**What is the difference between MCP and simple function calling?**

- Simple Tool Calling: The LLM calls a Python function that is imported directly into
  the same agent.py process. The function and the LLM share memory, share the process,
  and the LLM just calls the function by name.

- Genuine MCP: The LLM connects to a completely independent Python process
  (mcp_server.py) running in the background. It communicates over stdio using the
  MCP protocol (a structured JSON-based message format). The tool lives in a separate
  process with its own memory and lifecycle.

**Why does this distinction matter?**
MCP is the emerging industry standard for AI tool integration, created by Anthropic and
now adopted by OpenAI, Google, and others. It is designed to be language-agnostic and
server-agnostic. A genuine MCP implementation demonstrates that you understand agentic
architecture at a systems level, not just that you wrapped a Python function.

**Why stdio transport instead of HTTP transport?**
MCP supports two transports: stdio (subprocess) and HTTP (network server).
- stdio — MCP server runs as a subprocess, communicates via stdin/stdout. Simpler.
  No port conflicts. No server lifecycle management. Perfect for local demos.
- HTTP — MCP server runs as a web server. Needed for remote/multi-client scenarios.
Tradeoff accepted: stdio is local-only, but that is exactly our use case.

---

### 4.5 Output Validation: Pydantic v2

**Decision:** Pydantic v2 for strict JSON schema enforcement on the final output.

**Why Pydantic?**
Without Pydantic, the LLM can return any JSON it wants. Fields can be missing, types can
be wrong, and citations can be absent. Pydantic makes the schema the law: either the
output matches the schema, or an exception is raised. This eliminates an entire class of
bugs — malformed output — at the architecture level.

The mandatory source_citation field is the key guardrail. The model cannot produce a
compliance report without citing where the data came from. This directly demonstrates the
"Grounded, Cited Deliverables" course concept.

**Why Pydantic v2 and not v1?**
Pydantic v2 was released in 2023 and is the current standard. v1 is in maintenance-only
mode. v2 is ~50x faster than v1 (rewritten in Rust under the hood) and has a cleaner API.
There is no reason to use v1 for a new project.

---

### 4.6 Frontend: Streamlit

**Decision:** Streamlit for the user interface.

**Why Streamlit instead of Flask, FastAPI, or plain HTML?**
Streamlit is pure Python. You write Python, you get a web UI. No HTML, no CSS, no
JavaScript. For a data pipeline demo targeting engineers and evaluators (not end users),
Streamlit is the industry standard.

Tradeoff acknowledged: Streamlit is single-threaded and not suitable for production web
apps with multiple concurrent users. For this project — a demo tool — that limitation is
completely irrelevant.

---

## 5. Code Organisation Decisions

---

### 5.1 constants.py — Single Source of Truth for All Config Values

**Decision:** Every magic number and configurable string lives in constants.py.

**Why?**
Imagine temperature=0.0 is written directly inside agent.py. Now you want to test with
temperature=0.1. You open agent.py, search for the value, change it, test, then change
it back. This is error-prone and slow.

With constants.py, you change one line in one file. Every other file imports from it.
This is the Single Source of Truth principle — the same idea behind having one SRS
document instead of scattered notes.

It also makes your decisions visible. An evaluator can open constants.py and immediately
understand every tunable parameter in the system.

    OLLAMA_MODEL       = "qwen2.5:3b"
    LLM_TEMPERATURE    = 0.0      # Pinned for determinism. Eliminates creative hallucinations.
    MAX_OUTPUT_TOKENS  = 1024     # Caps token spend. Forces concise, structured output.
    CHROMA_PERSIST_DIR = "./chroma_db"
    RAG_DATA_PATH      = "./data/regulatory_framework.txt"
    RAG_TOP_K_RESULTS  = 3        # Number of regulatory chunks retrieved per chemical query.

**Why MAX_OUTPUT_TOKENS = 1024?**
This directly demonstrates the "Tokens & Parameters" course concept. Setting it to 1024
is enough for a structured JSON report. Without this cap, the model could generate thousands
of tokens of prose. The cap enforces that the output is the structured report, not an essay.

**Why RAG_TOP_K_RESULTS = 3?**
This is the "Context Window" concept in action. We retrieve the top 3 most relevant
regulatory chunks and inject them into the context window. Retrieving too many (e.g., 10)
wastes context space with less-relevant text. Retrieving too few (1) risks missing the
right chunk. 3 is the standard starting point for small RAG systems.

---

### 5.2 ingest.py — The One-Time RAG Setup Script

**Decision:** ingest.py is a standalone script run once before app.py.

**Why separate instead of putting ingestion inside app.py?**
Ingestion (read file ? chunk ? embed ? store) is an ETL operation: Extract, Transform, Load.
It does not belong in the application runtime. The correct pattern is:
1. Build the index once (ingest.py) — slow, done once
2. Query the index many times (rag.py called from agent.py) — fast, done on every request

This separation directly maps to the "Chunk ? Embed ? Store" phase of the Vector DB
pipeline course module.

---

## 6. Data Coverage

---

### 6.1 RAG Data — data/regulatory_framework.txt

**Decision:** Cover 5 chemicals with OSHA-style PEL limits.

| Chemical | Key Limit |
|---|---|
| Benzene | 1 ppm TWA (human carcinogen) |
| Acetone | 1000 ppm TWA |
| Toluene | 200 ppm TWA |
| Methanol | 200 ppm TWA (also skin absorption hazard) |
| Isopropanol | 400 ppm TWA |

**Why 5, not just Benzene?**
The original plan only had Benzene. If an evaluator types "Acetone" and the system says
"Unknown", that is technically correct per Rule 1 — but it looks like the RAG is broken.
5 chemicals gives meaningful interaction space while staying well within the "under 15 rows"
guideline from the original brief.

---

### 6.2 MCP Server Data — Hardware Thermal Limits in mcp_server.py

**Decision:** Cover 4 container types.

| Container | Max Safe Temp | Why Include |
|---|---|---|
| Soda-lime glass | 100 degrees C | Standard cheap lab glassware — most common |
| Borosilicate glass (Pyrex) | 500 degrees C | Scientific grade — shows contrast with soda-lime |
| Stainless steel beaker | 600 degrees C | Metal — demonstrates non-glass option |
| Polypropylene container | 80 degrees C | Plastic — lowest tolerance, easy to violate |

**Why 4?**
Same reasoning as chemicals. It demonstrates that the MCP server holds a real, structured
data source — not a single hardcoded value. The contrast between polypropylene (80°C) and
borosilicate (500°C) makes for a compelling and educational demo.

---

## 7. System Rules & Logic Boundaries

These are non-negotiable guardrails enforced in the system prompt inside agent.py.

- **Rule 1 — Zero-Shot Guessing Prevention:** If a chemical is not found in ChromaDB,
  the LLM must output "Unknown: No regulatory data found". It must never guess or
  hallucinate a limit.

- **Rule 2 — Strict Tool Parameter Enforcement:** The LLM cannot infer a missing
  temperature from context. If the temperature is ambiguous, it must halt and ask the user.

- **Rule 3 — Semantic Chunking:** Regulatory text is chunked by logical paragraph, not by
  character count. Reason: a single OSHA entry for one chemical is one complete unit of
  meaning. Splitting it mid-sentence (character chunking) would break the semantic unit
  and degrade retrieval quality.

- **Rule 4 — Temperature Lock:** temperature=0.0 always. This is a compliance system.
  Creativity is a bug here, not a feature.

- **Rule 5 — Token Budget:** max_output_tokens=1024 always. The output is a structured
  JSON report. This cap enforces conciseness and controls token usage.

---

## 8. Final File Manifest

    L1_Project/
    |
    |-- constants.py              <- All config values. Single source of truth.
    |-- models.py                 <- Pydantic schemas (ComplianceReport, ChemicalFlag, HardwareFlag)
    |
    |-- ingest.py                 <- Run ONCE before app.py. Chunks, embeds, stores RAG data.
    |-- rag.py                    <- Loads persisted ChromaDB. Exposes query_regulations().
    |
    |-- mcp_server.py             <- Independent MCP Server process. Holds hardware limits.
    |-- agent.py                  <- Ollama LLM + MCP Client. Orchestrates the full pipeline.
    |
    |-- app.py                    <- Streamlit UI entry point.
    |
    `-- data/
        `-- regulatory_framework.txt   <- 5 chemicals, OSHA-style PEL limits, paragraph-structured.

**Run Order:**

    Step 1 (once):    python ingest.py        <- builds the ChromaDB vector index on disk
    Step 2 (always):  streamlit run app.py    <- launches the UI

---

## 9. Pinned Dependency Versions

Every version is pinned. Unpinned dependencies break when libraries release updates.

| Library | Pinned Version | Reason for This Version |
|---|---|---|
| chromadb | 0.5.3 | Stable PersistentClient API. 0.6.x introduced breaking changes to the collection API. |
| pydantic | 2.7.1 | v2 is current standard. ~50x faster than v1. v1 is deprecated. |
| streamlit | 1.35.0 | Most recent stable release at time of writing. |
| ollama | 0.2.1 | Official Python client. 0.2.x branch has stable async support. |
| mcp | 1.0.0 | First stable major release of the official Anthropic MCP Python SDK. |
| sentence-transformers | 2.7.0 | Required by ChromaDB default embedding function. Stable with all-MiniLM-L6-v2. |

**Install command:**

    pip install chromadb==0.5.3 pydantic==2.7.1 streamlit==1.35.0 ollama==0.2.1 mcp==1.0.0 sentence-transformers==2.7.0
