> [!WARNING]
> **Historical Document:** This is the original project brief. The architecture evolved significantly during development to address performance and hallucination issues. 
> Please see [`docs/DESIGN.md`](DESIGN.md) for the complete implementation history and the final architecture, and [`docs/README.md`](README.md) for the current setup guide.

---

# Project Brief: EcoFormulate Audit Tool (Chemical Domain RAG & Agent Pipeline)

## 1. Executive Summary & Rationale

* **Role:** AI Data Engineer (Chemical Domain).
* **Objective:** Build a high-impact, production-grade project to conclude a foundational LLM/RAG/Agents course.
* **The Problem:** Chemical formulation development is heavily bottlenecked by manual safety, hardware compatibility, and environmental regulatory compliance checks.
* **The Decision Matrix (Why this project?):**
* **Moving Beyond Chatbots:** Avoided a standard multi-turn conversational UI loop. Mentors value automated, linear data-engineering workflows (Messy Input → AI Processing → Schema-Validated Output) over fragile chat spaces.
* **Local Hardware Optimization:** Designed specifically to run smoothly, deterministicly, and instantly on a standard local machine without heavy computing requirements or infrastructure costs.
* **Architectural Choice (RAG vs. Fine-Tuning):** RAG was explicitly selected over Fine-Tuning. Chemical and environmental regulations change dynamically, requiring 100% absolute factual verification and strict source citations. Fine-tuning cannot prevent hallucinations or guarantee verbatim legal text retention.



---

## 2. Course Syllabus Alignment (100% Concept Mapping)

Every module from the curriculum directly maps to an engineering choice in this codebase:

* **Tokens, Context Windows, & Parameters:** Configured explicitly to maintain budget, speed, and determinism. `temperature` is pinned to `0.0` to eliminate creative hallucinations. `max_output_tokens` is tightly controlled.
* **System Prompting & Guardrails:** Implements strict guardrails. The system prompt forces the model to act as a rigorous compliance officer. It explicitly commands the model to output `"No regulatory data found"` if a chemical is absent from the context, eliminating data invention.
* **Vector DB Pipelines (Chunk → Embed → Retrieve):** Utilizes an in-memory, zero-setup vector database (`ChromaDB` or `FAISS`) to store localized compliance data (e.g., local environmental limits, prohibited solvent rules). Demonstrates custom chunking strategies (chunking legally by structural paragraphs rather than character counts).
* **Agentic Tool Integration (Model Context Protocol / Tool Calling):** Connects the LLM safely to local code execution via standard function calling. The model extracts operational parameters (e.g., target temperature and container material) and routes them to a local deterministic calculation script to verify hardware safety boundaries.
* **Grounded, Cited Deliverables:** The final output requires mandatory document provenance mapping, tying every flag directly back to its specific database source chunk and raw file origin.

---

## 3. Data Architecture & Input/Output Pipeline

```
[Raw User Input Text] (Messy Lab Note / Proposed Formula)
         │
         ▼
 1. [Token & Parameter Controller] (Applies low temperature for strict data rules)
         │
         ▼
 2. [Context Guardrail Prompt] (Ensures the AI only judges based on known rules)
         │
         ▼
 3. [Vector DB RAG Retrieval] (Pulls regulatory limits for Acetone/Benzene locally)
         │
         ▼
 4. [MCP / Tool Integration] (Calls a tool to check if 95°C exceeds the beaker's limit)
         │
         ▼
 5. [Grounded Output Generation] (Outputs a structured JSON report with strict citations)

```

### Mock Datasets Needed (Keep it under 15 rows for local performance):

1. **Local RAG Document (`regulatory_framework.txt`):** A small local text file detailing environmental boundaries (e.g., *"Benzene is a restricted human carcinogen. Maximum allowable compound formulation concentration in open systems is 0.1%."*).
2. **Lab Tool Hardware Matrix:** A local database or internal dictionary representing laboratory equipment constraints (e.g., `Standard Glass Beaker` max safe operational thermal tolerance is `80°C`).

### Operational Flow (The 5-Step Logic Loop):

1. **Ingestion:** The user submits a raw text string representing a new lab formula recipe (e.g., *"Formula Variant B: 94% Water, 6% Benzene. Heat mixture to 95°C in a standard glass beaker."*).
2. **Extraction & Search:** The pipeline identifies chemical entities within the text, hits the local vector database, and pulls down relevant regulatory chunks via a semantic similarity search.
3. **Tool Execution:** The engine detects operational thresholds within the raw text (`95°C` and `standard glass beaker`). It triggers an external tool function to calculate hardware safety. The tool flags the event because `95°C` exceeds the `80°C` limit.
4. **Structured Consolidation:** The LLM aggregates the compliance data from the RAG search and the hardware safety output from the tool.
5. **Output Serialization:** The pipeline outputs a strict, schema-validated JSON format (using Pydantic wrappers) containing:
* `chemical_compliance_flags`: Lists the Benzene threshold violation with exact citation strings from `regulatory_framework.txt`.
* `hardware_compatibility_flags`: Lists the beaker's thermal failure point.
* `approval_status`: A clean binary pass/fail flag.



---

## 4. Instructions for the Agentic IDE

> "Hey Agent, read this entire layout document carefully. Use this structural blueprint to construct a linear, single-file Python script executing this compliance automation pipeline. Implement Pydantic for the final data mapping schema, utilize ChromaDB running an Ephemeral/In-Memory client for the vector storage engine, and use the Google GenAI SDK (`gemini-2.5-flash`) for the core orchestration layer. Keep the code heavily commented so every component, tool execution, and prompt configuration can be explicitly defended to human technical mentors."