# 🚀 Lab Safety Auditor: Future Enhancements Roadmap

This document outlines the planned improvements to transition the Lab Safety Auditor from a local prototype to a robust, highly-accurate, and fast assistant.

---

## 1. Multi-Tier Caching Layers (For Speed & Efficiency)
To bypass heavy computations (like LLM generation or database queries) on repeated or similar requests:

- [ ] **Deterministic RAG/OSHA Cache**
  - Cache OSHA limits and chemical physical constants (e.g., boiling points) by chemical name.
  - Implement using a lightweight database (e.g., SQLite) or in-memory dictionary.
- [ ] **Semantic Cache**
  - Store embeddings of input prompts and their finalized evaluation results.
  - On new input, check similarity. If similarity is $> 0.95$, return the cached report immediately.
- [ ] **Structured LLM Summary Cache**
  - Hash the output of the deterministic compliance checks. If the same pattern of failures/passes is detected, reuse the cached natural language summary.

---

## 2. Robust Parsing of "Story-Like" Narrative Inputs
To handle messy, conversational, or paragraph-style inputs where regex fails:

- [ ] **LLM-Based Entity Extraction**
  - Prompt a lightweight LLM to parse conversational text and return strict JSON structures containing chemical names, concentrations, hardware used, and target temperatures.
- [ ] **Hybrid Extraction Pipeline**
  - Run the deterministic regex-based extraction first.
  - Fall back to the LLM-based entity extractor only if regex fails to detect essential fields or if the input text contains complex sentence structures.

---

## 3. Data Validation & Auto-Correction
To handle incorrect, misspelled, or physically impossible input parameters:

- [ ] **Chemical Name Fuzzy Matching**
  - Use fuzzy matching (e.g., `rapidfuzz` or `difflib`) to match misspelled chemicals (like `"benzen"` or `"isopropnol"`) against the verified OSHA registry list.
- [ ] **Physical Boundary Validation**
  - Implement checks against physical limits (e.g., warn the user if they input a temperature higher than the safety/melting point of the hardware or if they provide mismatched units like `5% Toluene ppm`).

---

## 4. MCP Server for Web Searching & SDS Retrieval
To handle chemicals that are not present in the local vector database:

- [ ] **Dynamic Web Search Fallback**
  - Integrate a Web Search MCP tool (using Tavily, DuckDuckGo, or Serper).
  - When ChromaDB yields no matches for a chemical, query the search tool for safety guidelines, parse the exposure limits/boiling points, and dynamically update the local database.

---

## 5. API-Based LLM Integration (For Speed & Performance)
To drastically reduce response times compared to running local models on CPU:

- [ ] **External API Integration**
  - Replace local Ollama runs with cloud API calls (e.g., Gemini API or OpenAI API).
  - Use smaller, highly-optimized models (like Gemini 2.5 Flash) via API to get structured outputs and summaries in milliseconds.
