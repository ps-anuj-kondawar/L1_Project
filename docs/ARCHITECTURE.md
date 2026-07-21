# System Architecture & Diagrams: Lab Safety Auditor

This document provides a comprehensive view of the system architecture, data transformations, and operational workflows of the **Automated Lab Safety Auditor** (EcoFormulate Audit Tool). 

All diagrams and descriptions are mapped directly to the actual code implementation in the repository.

---

## 1. System Components Overview

The system consists of the following files and structural layers:

* **Presentation Layer**: [app.py](file:///c:/L1_Project/app.py) (Gradio UI block layout, theme-aware CSS card injection, event bindings).
* **Orchestration Layer**: [agent.py](file:///c:/L1_Project/agent.py) (Main pipeline, entity extractors, unit comparators, policy solver, Ollama LLM integration).
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
        P9 -->|18. Markdown Badges & HTML Cards| User
    end
    
    %% Styles
    classDef process fill:#dff,stroke:#088,stroke-width:1.5px;
    classDef store fill:#ffd,stroke:#880,stroke-width:1.5px;
    classDef entity fill:#fdf,stroke:#808,stroke-width:1.5px;
    
    class P1,P2,P3,P4,P5,P6,P7,P8,P9 process;
    class D1,D2,D3 store;
    class User entity;
```

### DFD Process & Store Index

1. **Processes (P1 - P9)**:
   * **P1: Entity Extractor** (Regex-based in [agent.py:L20-L87](file:///c:/L1_Project/agent.py#L20-L87)): Parses text via four patterns to output list of chemical-concentration tuples and checks hardware keys.
   * **P2: RAG Retrieval Manager** (ChromaDB query in [rag.py:L8-L14](file:///c:/L1_Project/rag.py#L8-L14)): Calls ChromaDB query matching chemical names to get the `top-1` document.
   * **P3: Limit Parser** (Regex-based in [agent.py:L90-L112](file:///c:/L1_Project/agent.py#L90-L112)): Searches RAG document chunk for `ppm TWA` and `% by volume` limits.
   * **P4: MCP Hardware Validator** (Subprocess dispatch in [agent.py:L201-L223](file:///c:/L1_Project/agent.py#L201-L223)): Communicates with FastMCP via `stdio` transport. Fallback logic queries `constants.py` directly.
   * **P5: Physical Hazard Checker** (Boiling point safety in [agent.py:L182-L197](file:///c:/L1_Project/agent.py#L182-L197)): Checks if the operating temperature exceeds the physical boiling point of any extracted solvent.
   * **P6: Global Compliance Solver** (Logic solver in [agent.py:L254-L272](file:///c:/L1_Project/agent.py#L254-L272)): Evaluates compliance status of chemicals, safety bounds of equipment, physical limits, and sets status to `APPROVED`, `REJECTED`, or `PARTIAL`.
   * **P7: LLM Summary Generator** (Ollama in [agent.py:L280-L297](file:///c:/L1_Project/agent.py#L280-L297)): Calls `llama3.2:1b` (temperature=0.0, num_predict=60) with violation notes to generate a concise, fluent summary.
   * **P8: Report Schema Validator** (Pydantic in [agent.py:L299-L304](file:///c:/L1_Project/agent.py#L299-L304)): Packs details into the `ComplianceReport` model to enforce type schemas.
   * **P9: Gradio UI Renderer** (Presentation formatter in [app.py:L82-L163](file:///c:/L1_Project/app.py#L82-L163)): Turns JSON parameters into styled HTML/CSS component widgets.

2. **Data Stores (D1 - D3)**:
   * **D1: ChromaDB Vector Store**: A directory database (`./chroma_db`) storing embedded OSHA hazard documents loaded via [ingest.py](file:///c:/L1_Project/ingest.py).
   * **D2: Physical Chemistry DB**: A static table of chemical boiling points defined in [constants.py:L20-L28](file:///c:/L1_Project/constants.py#L20-L28).
   * **D3: Hardware Limits DB**: A static mapping of equipment thermal limits in [constants.py:L13-L18](file:///c:/L1_Project/constants.py#L13-L18).

---

## 3. Workflow Diagram (Sequence & Chronology)

The Workflow Diagram shows the **chronological sequence, conditional logic gates, loops, and async interactions** that occur during a single audit execution cycle.

```mermaid
sequenceDiagram
    autonumber
    actor Chemist as User (Lab Chemist)
    participant UI as app.py (Gradio UI)
    participant Pipe as agent.py (Orchestrator)
    participant RAG as rag.py (ChromaDB Wrapper)
    participant MCP as mcp_server.py (FastMCP)
    participant LLM as Ollama (llama3.2:1b)

    Chemist->>UI: Selects/Enters Formulation & clicks "Run Audit"
    UI->>Pipe: Calls run_audit_pipeline(user_input)
    
    %% Entity Extraction
    Note over Pipe: Extracts chemical names, concentration strings,<br/>hardware vessels, and target operating temperature.
    
    %% Chemical Compliance Loop
    rect rgb(230, 245, 255)
        Note over Pipe: LOOP: For each extracted chemical
        alt Chemical is Water
            Note over Pipe: Directly marks as compliant (no RAG search)
        else Chemical is Hazardous
            Pipe->>RAG: query_regulations(chemical_name)
            RAG-->>Pipe: Returns Top-1 document chunk
            Note over Pipe: Runs regex parser on chunk:<br/>looks for 'ppm TWA' and '% by volume' limits.
            Note over Pipe: Evaluates concentration unit matches.<br/>Instantiates ChemicalFlag schema.
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
        Note over Pipe: Instantiates HardwareFlag schema.
    end
    
    %% Physical Hazard Check
    Note over Pipe: Compares target temperature against BOILING_POINTS_CELSIUS.<br/>Generates boiling_hazards descriptions.
    
    %% Decision Matrix
    Note over Pipe: Solves policy matrix:<br/>- Any chemical non-compliant or hardware unsafe? -> STATUS = REJECTED<br/>- Boiling point exceeded only? -> STATUS = PARTIAL<br/>- All checks pass? -> STATUS = APPROVED
    
    %% LLM Summary Generation
    alt Any Violation Notes Exist
        Pipe->>LLM: chat(system_prompt, user_content: violation_notes)
        LLM-->>Pipe: Returns ONE concise summary sentence (Temp=0.0, num_predict=60)
    else No Violations Found
        Pipe->>LLM: chat(system_prompt, user_content: "All checks passed")
        LLM-->>Pipe: Returns standard positive safety summary
    end
    
    %% Pydantic validation and UI output
    Note over Pipe: Validates models.ComplianceReport schema.
    Pipe-->>UI: Returns ComplianceReport model dictionary
    Note over UI: Generates green-bordered (PASS) or red-bordered (FAIL)<br/>HTML card layouts using Gradio theme CSS.
    UI-->>Chemist: Renders Markdown status, HTML cards, and raw JSON (⏱️ < 5 seconds)
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
