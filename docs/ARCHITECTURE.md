# System Architecture & Diagrams: Lab Safety Auditor

This document provides a comprehensive view of the system architecture, data transformations, and operational workflows of the upgraded **Automated Lab Safety Auditor** (EcoFormulate Audit Tool). 

All diagrams and descriptions are mapped directly to the actual code implementation in the repository.

---

## 1. System Components Overview

The system consists of the following files and structural layers:

* **Presentation Layer**: [app.py](file:///c:/L1_Project/app.py) (Gradio UI block layout, theme-aware CSS card injection, clickable link citations, event bindings).
* **Orchestration Layer**: [agent.py](file:///c:/L1_Project/agent.py) (Main pipeline, entity extractors, unit comparators, policy solver, Tavily search client fallback).
* **Validation Layer**: [validator.py](file:///c:/L1_Project/validator.py) (RapidFuzz string similarity corrections and physical boundary limit validators).
* **Caching Layer**: [cache.py](file:///c:/L1_Project/cache.py) (Multi-Tier SQLite database caching, including prompt SHA-256 caching and summary caching).
* **LLM Client Wrapper**: [llm_client.py](file:///c:/L1_Project/llm_client.py) (Unified async SDK wrapper for Google Gemini with dynamic OpenRouter free-tier fallback).
* **Storage / Vector Database**: [rag.py](file:///c:/L1_Project/rag.py) (ChromaDB persistent client, vector semantic queries) and [ingest.py](file:///c:/L1_Project/ingest.py) (ChromaDB collection setup and ingestion of raw regulatory text).
* **External Tooling Layer**: [mcp_server.py](file:///c:/L1_Project/mcp_server.py) (FastMCP server exposing hardware thermal boundaries via JSON).
* **Data Definition & Models**: [models.py](file:///c:/L1_Project/models.py) (Pydantic v2 schemas for type-safe validation) and [constants.py](file:///c:/L1_Project/constants.py) (Boiling points, hardware threshold definitions, configuration bounds).

---

## 2. Data Flow Diagram (DFD)

A Data Flow Diagram focuses on **data transformations, boundaries, processes, and storage**. It does not represent execution sequence or conditionals.

### Level 1 DFD (Data Processes and Stores)

```mermaid
graph TD
    %% External Entities (Users)
    User([Lab Chemist]) -->|1. Formulation Text Input| P1[P1: Entity Extractor]
    
    %% Processes
    subgraph Data Extraction & Parsing
        P1 -->|2. Chemical Names & Conc| P2[P2: RAG Retrieval Manager]
        P1 -->|3. Equipment Names & Temp| P4[P4: MCP Hardware Validator]
    end
    
    subgraph Regulatory Verification
        P2 -->|4. Query Chemical Name| D1[(D1: ChromaDB Vector Store)]
        D1 -->|5. OSHA Regulatory Chunk| P3[P3: Limit Parser]
        P2 -->|5a. Search Web Fallback| D4[(D4: Tavily Search API)]
        D4 -->|5b. Web Exposure limits| P3
        P3 -->|6. Permissible Exposure Limits| P6[P6: Policy Decision Solver]
    end
    
    subgraph Hardware & Physical Safety
        P4 -->|7. Query Thermal Compatibility| D3[(D3: Hardware Limits DB)]
        D3 -->|8. Vessel Max Temperature| P4
        P4 -->|9. Hardware Safety Flags| P6
        
        P1 -->|10. Target Temperature| P5[P5: Physical Hazard Checker]
        P1 -->|11. Chemical Names| P5
        D2[(D2: Physical Chemistry DB)] -->|12. Solvent Boiling Points| P5
        P5 -->|13. Boiling Point Hazards| P6
    end
    
    subgraph Logic Aggregation & Summarization
        P6 -->|14. Violation Details Bullet Points| P7[P7: LLM Summary Generator]
        P7 -->|15. One-Sentence Summary Text| P8[P8: Report Schema Validator]
        P6 -->|16. Aggregated Flags & Global Status| P8
    end
    
    subgraph UI Render
        P8 -->|17. Validated ComplianceReport JSON| P9[P9: Gradio UI Renderer]
        P9 -->|18. Markdown Badges & Clickable HTML Cards| User
    end
    
    %% Styles
    classDef process fill:#dff,stroke:#088,stroke-width:1.5px;
    classDef store fill:#ffd,stroke:#880,stroke-width:1.5px;
    classDef entity fill:#fdf,stroke:#808,stroke-width:1.5px;
    
    class P1,P2,P3,P4,P5,P6,P7,P8,P9 process;
    class D1,D2,D3,D4 store;
    class User entity;
```

---

## 3. Workflow Diagram (Sequence & Chronology)

The Workflow Diagram shows the **chronological sequence, conditional logic gates, loops, and async interactions** that occur during a single audit execution cycle.

```mermaid
sequenceDiagram
    autonumber
    actor Chemist as User (Lab Chemist)
    participant UI as app.py (Gradio UI)
    participant Cache as cache.py (SQLite Cache)
    participant Pipe as agent.py (Orchestrator)
    participant Val as validator.py (Fuzzy Match & Check)
    participant RAG as rag.py (ChromaDB Wrapper)
    participant Web as Tavily (Web Search)
    participant MCP as mcp_server.py (FastMCP)
    participant LLM as Google Gemini / OpenRouter

    Chemist->>UI: Selects/Enters Formulation & clicks "Run Audit"
    UI->>Cache: Query exact prompt SHA-256 hash (Layer 2)
    alt Cache Hit
        Cache-->>UI: Return cached ComplianceReport JSON instantly (<0.01s)
    else Cache Miss
        UI->>Pipe: Calls run_audit_pipeline(user_input)
        
        %% Entity Extraction & Validation
        Note over Pipe: Extracts raw chemical names, concentrations,<br/>hardware vessels, and target operating temperature.
        Pipe->>Val: Correct chemical names (Fuzzy RapidFuzz) & validate boundaries
        Val-->>Pipe: Returns corrected entities, warning tags, and error alerts.
        
        %% Chemical Compliance Loop
        rect rgb(230, 245, 255)
            Note over Pipe: LOOP: For each corrected chemical
            alt Chemical is Water
                Note over Pipe: Directly marks as compliant (no RAG search)
            else Chemical is Hazardous
                Pipe->>Cache: Check SQLite OSHA limits cache (Layer 1)
                alt Layer 1 Hit
                    Cache-->>Pipe: Return cached limits database entry
                else Layer 1 Miss
                    Pipe->>RAG: query_regulations(chemical_name)
                    RAG-->>Pipe: Returns document chunk
                    Note over Pipe: Checks relevancy. If matched, parses limits.
                    alt RAG Miss / Irrelevant
                        Pipe->>Web: Fetch OSHA standards (Tavily search API fallback)
                        Web-->>Pipe: Returns search results
                        Pipe->>LLM: Extract limits using LLM reasoning
                        LLM-->>Pipe: Returns structured limits JSON
                        Pipe->>Cache: Save limits to Layer 1 Cache database
                    end
                end
            end
        end
        
        %% Hardware Compliance Loop
        rect rgb(240, 240, 240)
            Note over Pipe: LOOP: For each matched hardware vessel
            Pipe->>MCP: Call check_hardware_compatibility(vessel, temp)
            Note over MCP: Looks up threshold limits in constants.py
            alt MCP Subprocess Success
                MCP-->>Pipe: Returns compatibility JSON (is_safe, max_temp)
            else MCP Subprocess Error
                Note over Pipe: Falls back to local constants.py lookup
            end
        end
        
        %% Physical Hazard Check
        Note over Pipe: Compares target temperature against BOILING_POINTS_CELSIUS.<br/>Generates boiling_hazards descriptions.
        
        %% Decision Matrix
        Note over Pipe: Solves policy matrix:<br/>- Hardware limit violated or % volume exceeded? -> STATUS = REJECTED<br/>- ppm exposure limits violated? -> STATUS = PARTIAL<br/>- All checks pass? -> STATUS = APPROVED
        
        %% LLM Summary Generation
        Pipe->>Cache: Check Layer 3 Summary Cache
        alt Layer 3 Hit
            Cache-->>Pipe: Returns cached summary text
        else Layer 3 Miss
            Pipe->>LLM: Generate summary (Google Gemini / OpenRouter Fallback)
            LLM-->>Pipe: Returns concise safety summary
            Pipe->>Cache: Save summary to Layer 3 Cache database
        end
        
        %% UI output
        Pipe->>Cache: Cache completed ComplianceReport (Layer 2)
        Pipe-->>UI: Returns ComplianceReport model dictionary
        Note over UI: Renders dynamic metrics card, orange warnings,<br/>and converts URLs to clickable links
        UI-->>Chemist: Renders Gradio interface widgets
    end
```

---

## 4. Architectural Comparison: DFD vs. Workflow

To understand the system fully, observe how the **DFD** and **Workflow** represent different aspects of the same application:

| Feature / Aspect | Data Flow Diagram (DFD) | Workflow Diagram |
| :--- | :--- | :--- |
| **Primary Focus** | Data transformation, boundary separation, and database storage routing. | Execution chronology, call sequence, asynchronous subprocesses, and conditional logic. |
| **Logic & Decisions** | **Hidden.** Shows inputs feeding into processes; doesn't describe decision trees (like `APPROVED` vs. `REJECTED`). | **Explicit.** Shows conditional loops, fallback handlers, and branching parameters based on rules evaluation. |
| **Time Representation** | **None.** Data flows are concurrent and state-free; no sequence is implied. | **Linear/Sequential.** Represented with order numbers (1-32) and vertical timeline progression. |
| **Error / Fallback Paths** | Shows database and service nodes; does not show failure handlers (like falling back to `constants.py` when MCP fails). | Highlights the subprocess try-except block and manual database override fallback branches. |
