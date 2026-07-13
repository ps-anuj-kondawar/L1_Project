> [!WARNING]
> **Historical Document:** This is the original implementation plan (v2.0). The system architecture was significantly refactored during development to solve performance and hallucination bottlenecks. 
> Please refer to [`DESIGN.md`](DESIGN.md) for the actual implemented architecture, decision log, and why this plan was changed.

# Implementation Plan: Automated Lab Safety Auditor
**Version:** 2.0 (Historical)
**Last Updated:** 2026-07-09

---

## Overview

This plan is the step-by-step engineering blueprint for building the project.
Every file, every value, every algorithm, and every integration is defined here
so that implementation can be done without ambiguity.

---

## Run Order (Read This First)

    Step 0:  pip install -r requirements.txt          <- install all dependencies
    Step 1:  python ingest.py                          <- ONE TIME ONLY. Builds vector DB on disk.
    Step 2:  streamlit run app.py                      <- Start the app every time.

---

## Final File Structure

    L1_Project/
    |
    |-- requirements.txt              <- pinned dependencies
    |-- constants.py                  <- all config values (Single Source of Truth)
    |-- models.py                     <- Pydantic output schemas
    |
    |-- ingest.py                     <- one-time RAG data ingestion script
    |-- rag.py                        <- ChromaDB query logic
    |
    |-- mcp_server.py                 <- independent MCP server process
    |-- agent.py                      <- LLM orchestration + MCP client
    |
    |-- app.py                        <- Streamlit frontend
    |
    `-- data/
        `-- regulatory_framework.txt  <- raw OSHA-style regulatory text

---

## File 1: requirements.txt

Purpose: Pin every dependency so the project builds identically on any machine.

    chromadb==0.5.3
    pydantic==2.7.1
    streamlit==1.35.0
    ollama==0.2.1
    mcp==1.0.0
    sentence-transformers==2.7.0

Why each version:
- chromadb 0.5.3  : Last stable version before 0.6.x breaking API changes.
- pydantic 2.7.1  : v2 is current standard, rewritten in Rust, ~50x faster than v1.
- streamlit 1.35.0: Stable release, no breaking changes expected.
- ollama 0.2.1    : Official Python client with stable sync and async support.
- mcp 1.0.0       : First stable major release of Anthropic MCP SDK.
- sentence-transformers 2.7.0: Required internally by ChromaDB default embedding function.

---

## File 2: constants.py

Purpose: Every magic value in the project lives here. One change here = change everywhere.
No other file should contain hardcoded model names, paths, or numeric parameters.

    # ── LLM Configuration ──────────────────────────────────────────────────────
    OLLAMA_MODEL      = "qwen2.5:3b"
    LLM_TEMPERATURE   = 0.0    # PINNED. Eliminates creative hallucinations. Compliance needs determinism.
    MAX_OUTPUT_TOKENS = 1024   # Caps token usage. Forces structured JSON output, not prose.

    # ── ChromaDB Configuration ──────────────────────────────────────────────────
    CHROMA_PERSIST_DIR     = "./chroma_db"       # Folder where vectors are saved to disk.
    CHROMA_COLLECTION_NAME = "regulatory_data"   # Name of the ChromaDB collection.

    # ── RAG Configuration ───────────────────────────────────────────────────────
    RAG_DATA_PATH    = "./data/regulatory_framework.txt"
    RAG_TOP_K        = 3   # Retrieve top 3 most relevant chunks per chemical query.
                           # 3 is the sweet spot: enough context, not wasteful.

    # ── MCP Configuration ───────────────────────────────────────────────────────
    MCP_SERVER_SCRIPT = "mcp_server.py"

Why RAG_TOP_K = 3:
    The LLM context window is finite. Injecting 10 chunks wastes space with marginally
    relevant text. Injecting 1 risks missing the right chunk if chunking is imperfect.
    3 is the established baseline for small, focused RAG systems.

---

## File 3: models.py

Purpose: Define the strict Pydantic v2 output schemas. These are the contracts the LLM
must satisfy. If the output does not match, Pydantic raises a validation error.

Schema design:

    ChemicalFlag
    ├── chemical_name           : str   — the chemical found in the input
    ├── is_compliant            : bool  — True if within regulatory limits
    ├── detected_concentration  : str   — as stated in user input (e.g. "6%")
    ├── regulatory_limit        : str   — from RAG (e.g. "1 ppm TWA") or "Unknown"
    └── source_citation         : str   — MANDATORY. Exact chunk text from ChromaDB.
                                         Cannot be empty. Forces grounded output.

    HardwareFlag
    ├── equipment_name                : str   — container type from user input
    ├── target_temperature_celsius    : float — temperature from user input
    ├── max_safe_temperature_celsius  : float — from MCP server hardware data
    └── is_safe                       : bool  — True if target <= max_safe

    ComplianceReport
    ├── chemical_flags            : list[ChemicalFlag]   — one entry per chemical
    ├── hardware_flags            : list[HardwareFlag]   — one entry per container mentioned
    ├── overall_approval_status   : str                  — "APPROVED" | "REJECTED" | "PARTIAL"
    └── summary                   : str                  — one sentence explanation

Why source_citation is mandatory:
    This is the "Grounded, Cited Deliverables" course concept made concrete.
    By making it a required Pydantic field with no default value, the model physically
    cannot produce output without it. It must retrieve, not hallucinate.

---

## File 4: data/regulatory_framework.txt

Purpose: The raw text data source for the RAG system. Structured as one paragraph per
chemical so that each paragraph chunks cleanly into one semantically complete unit.

Content structure (5 chemicals):

    Benzene
    Benzene (C6H6) is classified as a Group 1 human carcinogen by OSHA.
    Permissible Exposure Limit (PEL): 1 ppm TWA (8-hour time-weighted average).
    Short-Term Exposure Limit (STEL): 5 ppm over 15 minutes.
    Use in open formulation systems is heavily restricted. Maximum allowable
    concentration in open-system laboratory formulations is 0.1% by volume.
    Source: OSHA 29 CFR 1910.1028.

    (blank line — paragraph separator for chunking)

    Acetone
    Acetone (C3H6O) is a flammable solvent classified as a skin and eye irritant.
    Permissible Exposure Limit (PEL): 1000 ppm TWA.
    Acetone is not classified as a carcinogen. Flash point is -20 degrees C.
    Requires adequate ventilation in laboratory settings. Storage must be away
    from ignition sources.
    Source: OSHA 29 CFR 1910.1000 Table Z-1.

    (blank line)

    Toluene
    Toluene (C7H8) is a flammable aromatic solvent and a reproductive hazard.
    Permissible Exposure Limit (PEL): 200 ppm TWA.
    Short-Term Exposure Limit (STEL): 300 ppm ceiling.
    Prolonged exposure may cause central nervous system effects.
    Pregnant workers must avoid exposure.
    Source: OSHA 29 CFR 1910.1000 Table Z-2.

    (blank line)

    Methanol
    Methanol (CH3OH) is a highly toxic alcohol. It is metabolised to formaldehyde
    and formic acid in the human body, causing severe neurological damage.
    Permissible Exposure Limit (PEL): 200 ppm TWA.
    Skin absorption is a significant secondary exposure route — gloves are mandatory.
    Source: OSHA 29 CFR 1910.1000 Table Z-1.

    (blank line)

    Isopropanol
    Isopropanol (C3H8O), also known as IPA, is a common laboratory solvent.
    Permissible Exposure Limit (PEL): 400 ppm TWA.
    Short-Term Exposure Limit (STEL): 500 ppm.
    Low toxicity compared to methanol. Eye and skin irritant at high concentrations.
    Source: OSHA 29 CFR 1910.1000 Table Z-1.

Format rule: Each chemical block is separated by exactly ONE blank line (\n\n).
This is the paragraph separator used by the chunking algorithm in ingest.py.

---

## File 5: ingest.py

Purpose: One-time ETL script. Reads the text file, chunks it, embeds it, and saves
the vectors to disk via ChromaDB PersistentClient.

Run: python ingest.py   (only once, or when regulatory_framework.txt is updated)

Algorithm — step by step:

    STEP 1: Import
        from chromadb import PersistentClient
        from constants import CHROMA_PERSIST_DIR, CHROMA_COLLECTION_NAME, RAG_DATA_PATH

    STEP 2: Read the file
        with open(RAG_DATA_PATH, "r") as f:
            raw_text = f.read()

    STEP 3: Chunk by paragraph (Semantic Chunking Algorithm)
        chunks = [chunk.strip() for chunk in raw_text.split("\n\n") if chunk.strip()]
        # split("\n\n") splits on blank lines — each block is one chemical's data
        # .strip() removes leading/trailing whitespace
        # "if chunk.strip()" filters out any fully empty blocks

    STEP 4: Generate chunk IDs
        ids = [f"chunk_{i}" for i in range(len(chunks))]
        # Simple sequential IDs. ChromaDB requires unique IDs per document.

    STEP 5: Initialize ChromaDB PersistentClient
        client = PersistentClient(path=CHROMA_PERSIST_DIR)
        # This creates (or loads) the ./chroma_db/ folder on disk.
        # All subsequent app.py runs will load from this folder — no re-embedding needed.

    STEP 6: Create or get collection
        collection = client.get_or_create_collection(name=CHROMA_COLLECTION_NAME)
        # get_or_create_collection: safe to run multiple times.
        # If the collection already exists, it returns it. If not, creates it.
        # ChromaDB uses its default embedding function (all-MiniLM-L6-v2) automatically.

    STEP 7: Add documents
        collection.add(documents=chunks, ids=ids)
        # ChromaDB internally calls all-MiniLM-L6-v2 to embed each chunk.
        # The resulting 384-dimensional vectors are saved to ./chroma_db/ on disk.

    STEP 8: Confirm
        print(f"Ingested {len(chunks)} chunks into ChromaDB collection '{CHROMA_COLLECTION_NAME}'")

Why this chunking algorithm (paragraph split) and not character count split?
    Character count (e.g. split every 500 chars) cuts text mid-sentence. A Benzene entry
    split at character 450 would result in one chunk with partial data and another chunk
    starting mid-rule. Semantic retrieval would return incomplete, misleading context.
    Paragraph splitting keeps each chemical's complete regulatory entry as one atomic unit.

Embedding model detail:
    ChromaDB's default embedding function automatically downloads and uses
    all-MiniLM-L6-v2 (sentence-transformers library) on the first ingest.py run.
    After the first download (~80MB), it runs 100% offline.
    Output: 384-dimensional float vectors per chunk.

---

## File 6: rag.py

Purpose: Loads the persisted ChromaDB collection and exposes a clean query function
used by agent.py during every pipeline run.

Structure:

    STEP 1: Import
        from chromadb import PersistentClient
        from constants import CHROMA_PERSIST_DIR, CHROMA_COLLECTION_NAME, RAG_TOP_K

    STEP 2: Load the persisted client and collection at module load time
        _client     = PersistentClient(path=CHROMA_PERSIST_DIR)
        _collection = _client.get_collection(name=CHROMA_COLLECTION_NAME)
        # Loaded once when rag.py is imported. Fast — reads from disk, no re-embedding.

    STEP 3: Expose query function
        def query_regulations(chemical_name: str) -> list[str]:
            """
            Queries the ChromaDB collection for regulatory chunks relevant to the chemical.
            Returns a list of up to RAG_TOP_K matching text chunks.
            Returns an empty list if no relevant chunks are found.
            """
            results = _collection.query(
                query_texts=[chemical_name],
                n_results=RAG_TOP_K
            )
            return results["documents"][0]   # list of matching chunk strings

How the query works internally (Retrieval Algorithm):
    1. ChromaDB embeds the query string "Benzene" using all-MiniLM-L6-v2 → 384-dim vector.
    2. It computes cosine similarity between the query vector and all stored chunk vectors.
    3. It returns the top RAG_TOP_K chunks with highest cosine similarity scores.
    4. Agent uses these chunks as context for the LLM. If the list is empty, the agent
       flags that chemical as "Unknown: No regulatory data found" (Rule 1).

---

## File 7: mcp_server.py

Purpose: An independent Python process exposing the hardware safety check tool over
the MCP protocol via stdio transport. It holds the hardware thermal limits data.

Structure:

    STEP 1: Import
        from mcp.server.fastmcp import FastMCP

    STEP 2: Create MCP server instance
        mcp = FastMCP("lab-hardware-server")

    STEP 3: Define the hardware limits data store
        HARDWARE_LIMITS = {
            "soda-lime glass":       100,   # degrees C — standard cheap lab glass
            "borosilicate glass":    500,   # degrees C — scientific grade (Pyrex)
            "stainless steel beaker": 600,  # degrees C — metal container
            "polypropylene container": 80,  # degrees C — plastic, lowest tolerance
        }

    STEP 4: Define and expose the tool
        @mcp.tool()
        def check_hardware_compatibility(
            equipment_name: str,
            target_temperature_celsius: float
        ) -> dict:
            """
            Checks if the target temperature is within safe limits for the given equipment.
            Returns a dict with equipment details and a boolean is_safe flag.
            Raises ValueError if the equipment is not recognized.
            """
            key = equipment_name.lower().strip()

            if key not in HARDWARE_LIMITS:
                return {
                    "error": f"Unknown equipment: '{equipment_name}'. Cannot verify thermal safety.",
                    "known_equipment": list(HARDWARE_LIMITS.keys())
                }

            max_temp = HARDWARE_LIMITS[key]
            is_safe  = target_temperature_celsius <= max_temp

            return {
                "equipment_name":               equipment_name,
                "target_temperature_celsius":    target_temperature_celsius,
                "max_safe_temperature_celsius":  max_temp,
                "is_safe":                       is_safe
            }

    STEP 5: Run the server via stdio transport
        if __name__ == "__main__":
            mcp.run(transport="stdio")

Why stdio transport:
    stdio means agent.py launches mcp_server.py as a subprocess and communicates
    with it via standard input/output streams. This requires no ports, no network
    configuration, and no server lifecycle management. The subprocess is automatically
    cleaned up when agent.py exits.

Why the .lower().strip() normalisation on equipment_name:
    User input is messy. "Soda-Lime Glass" and "soda-lime glass" and "soda-lime glass "
    should all match. Normalising to lowercase + strip handles this without regex.

---

## File 8: agent.py

Purpose: The core orchestration engine. Connects to Ollama (LLM) and mcp_server.py
(MCP client). Runs the full pipeline: RAG → MCP → Consolidation → Pydantic output.

This is the most complex file. Read carefully.

### 8.1 System Prompt

The system prompt is injected as the first message in every LLM conversation.
It defines persona, rules, and output contract.

    SYSTEM_PROMPT = """
    You are a rigorous laboratory safety compliance officer.
    Your task is to analyse a raw chemical formulation note and produce a compliance report.

    You have access to:
    1. Regulatory context chunks retrieved from the OSHA regulatory database (provided below).
    2. A tool called check_hardware_compatibility to verify thermal safety of lab equipment.

    RULES — these are absolute and non-negotiable:
    Rule 1: If a chemical does not appear in the provided regulatory context, you MUST set
            its regulatory_limit to "Unknown: No regulatory data found". NEVER guess a limit.
    Rule 2: If the temperature or equipment type is not clearly stated in the user input,
            you MUST respond asking the user to clarify. Do NOT assume any value.
    Rule 3: You MUST call the check_hardware_compatibility tool for every piece of
            equipment mentioned. Do not estimate hardware safety without the tool.
    Rule 4: Your final output MUST be a single valid JSON object matching this schema
            exactly. No additional text, no markdown fences, no explanation:
            {
              "chemical_flags": [...],
              "hardware_flags": [...],
              "overall_approval_status": "APPROVED" or "REJECTED" or "PARTIAL",
              "summary": "one sentence"
            }
    """

### 8.2 Full Pipeline Algorithm

    INPUT: user_input (str) — the raw lab formulation note from Streamlit

    PHASE 1 — RAG RETRIEVAL
    ────────────────────────
    a) Extract chemical names from user_input.
       (Simple approach: pass user_input to LLM with a short extraction prompt,
        OR use a keyword list to identify chemicals — keep it simple for MVP.)

    b) For each chemical identified:
           chunks = rag.query_regulations(chemical_name)
           Store as: rag_context[chemical_name] = chunks

    c) Build the RAG context string to inject into the LLM:
           For each chemical and its chunks, format as:
           "--- Regulatory Data for Benzene ---\n<chunk1>\n<chunk2>\n..."

    PHASE 2 — MCP CONNECTION
    ─────────────────────────
    a) Launch mcp_server.py as a subprocess using the MCP StdioClient:
           async with stdio_client(server_params) as (read_stream, write_stream):
               async with ClientSession(read_stream, write_stream) as session:
                   await session.initialize()
                   tools = await session.list_tools()

    b) Convert MCP tool definitions to Ollama-compatible tool format:
           Each MCP tool has: name, description, inputSchema
           Ollama expects: {"type": "function", "function": {name, description, parameters}}

    PHASE 3 — LLM CALL WITH TOOL LOOP
    ────────────────────────────────────
    a) Build the initial message list:
           messages = [
               {"role": "system", "content": SYSTEM_PROMPT + "\n\n" + rag_context_string},
               {"role": "user",   "content": user_input}
           ]

    b) Call Ollama with tool definitions:
           response = ollama.chat(
               model    = OLLAMA_MODEL,         # "qwen2.5:3b" from constants.py
               messages = messages,
               tools    = ollama_tools,          # converted from MCP tools
               options  = {
                   "temperature":    LLM_TEMPERATURE,    # 0.0
                   "num_predict":    MAX_OUTPUT_TOKENS,   # 1024
               }
           )

    c) Tool call execution loop:
           WHILE response contains tool_calls:
               For each tool_call in response.message.tool_calls:
                   - Get tool name and arguments from the call
                   - Execute via MCP session: result = await session.call_tool(name, args)
                   - Append the assistant message (with tool_call) to messages
                   - Append the tool result message to messages
               Call Ollama again with updated messages → get new response
           END WHILE

    d) The loop ends when Ollama returns a message with no tool_calls.
       That message content is the final JSON report string.

    PHASE 4 — PYDANTIC VALIDATION
    ──────────────────────────────
    a) Parse the final response content as JSON:
           import json
           raw_json = json.loads(response.message.content)

    b) Validate against ComplianceReport schema:
           report = ComplianceReport(**raw_json)
           # If validation fails, Pydantic raises ValidationError with clear field errors.

    c) Return the validated ComplianceReport object to app.py

    OUTPUT: ComplianceReport (validated Pydantic model)

### 8.3 Public Interface

    def run_audit_pipeline(user_input: str) -> ComplianceReport:
        """
        Entry point called by app.py.
        Runs the full RAG → MCP → LLM → Pydantic pipeline.
        Returns a validated ComplianceReport.
        """
        import asyncio
        return asyncio.run(_async_pipeline(user_input))

    async def _async_pipeline(user_input: str) -> ComplianceReport:
        # Internal async implementation of the full pipeline above.
        ...

Why async?
    The MCP client API is async (uses Python asyncio). Wrapping it in asyncio.run()
    in the public function keeps app.py (Streamlit, synchronous) simple — it just calls
    run_audit_pipeline() as a normal function.

---

## File 9: app.py

Purpose: The Streamlit frontend. Collects user input and displays the compliance report.

Structure:

    STEP 1: Page config
        st.set_page_config(
            page_title = "Lab Safety Auditor",
            page_icon  = "⚗️",
            layout     = "wide"
        )

    STEP 2: Title and description
        st.title("⚗️ Automated Lab Safety Auditor")
        st.markdown("Enter a raw chemical formulation note below...")

    STEP 3: Input area
        user_input = st.text_area(
            label       = "Formulation Note",
            placeholder = "e.g. 94% Water, 6% Benzene. Heat to 120°C in a soda-lime glass beaker.",
            height      = 150
        )

    STEP 4: Submit button and pipeline call
        if st.button("Run Audit"):
            if not user_input.strip():
                st.warning("Please enter a formulation note.")
            else:
                with st.spinner("Auditing..."):
                    from agent import run_audit_pipeline
                    report = run_audit_pipeline(user_input)

    STEP 5: Display results
        st.subheader("Compliance Report")

        # Overall status with colour coding
        status_colour = "green" if report.overall_approval_status == "APPROVED" else "red"
        st.markdown(f"**Status:** :{status_colour}[{report.overall_approval_status}]")
        st.write(report.summary)

        # Chemical flags table
        st.subheader("Chemical Compliance")
        for flag in report.chemical_flags:
            icon = "✅" if flag.is_compliant else "❌"
            st.markdown(f"{icon} **{flag.chemical_name}**")
            st.write(f"Detected: {flag.detected_concentration}")
            st.write(f"Limit: {flag.regulatory_limit}")
            st.caption(f"Source: {flag.source_citation}")

        # Hardware flags
        st.subheader("Hardware Safety")
        for flag in report.hardware_flags:
            icon = "✅" if flag.is_safe else "❌"
            st.markdown(f"{icon} **{flag.equipment_name}**")
            st.write(f"Target: {flag.target_temperature_celsius}°C | Max Safe: {flag.max_safe_temperature_celsius}°C")

        # Raw JSON expander (useful for demo / evaluation)
        with st.expander("View Raw JSON Report"):
            st.json(report.model_dump())

---

## Data Flow Diagram

    User Input (Streamlit text area)
             │
             ▼
    ┌─────────────────────────────────────────────────────────┐
    │  agent.py — run_audit_pipeline()                        │
    │                                                         │
    │  PHASE 1: RAG                                           │
    │  ┌──────────────────────────────────────────────────┐   │
    │  │ rag.query_regulations("Benzene")                 │   │
    │  │       └─→ ChromaDB query (cosine similarity)     │   │
    │  │       └─→ returns top 3 text chunks from disk    │   │
    │  └──────────────────────────────────────────────────┘   │
    │           │                                             │
    │           ▼                                             │
    │  PHASE 2: MCP                                           │
    │  ┌──────────────────────────────────────────────────┐   │
    │  │ MCP Client → stdio → mcp_server.py subprocess   │   │
    │  │ Calls: check_hardware_compatibility(             │   │
    │  │            "soda-lime glass", 120.0)             │   │
    │  │ Returns: {is_safe: False, max_safe: 100}         │   │
    │  └──────────────────────────────────────────────────┘   │
    │           │                                             │
    │           ▼                                             │
    │  PHASE 3: LLM (Ollama qwen2.5:3b)                       │
    │  ┌──────────────────────────────────────────────────┐   │
    │  │ Input:  system_prompt + rag_context + user_input │   │
    │  │ Params: temperature=0.0, max_tokens=1024         │   │
    │  │ Output: raw JSON string                          │   │
    │  └──────────────────────────────────────────────────┘   │
    │           │                                             │
    │           ▼                                             │
    │  PHASE 4: Pydantic Validation                           │
    │  ┌──────────────────────────────────────────────────┐   │
    │  │ ComplianceReport(**raw_json) → validated object  │   │
    │  └──────────────────────────────────────────────────┘   │
    └─────────────────────────────────────────────────────────┘
             │
             ▼
    Streamlit UI displays structured report

---

## Test Case for Manual Verification

After building, run the app and submit this exact input:

    "Formula B: 94% Water, 6% Benzene. Heat the mixture to 120°C in a soda-lime glass beaker."

Expected output:

    overall_approval_status: "REJECTED"

    chemical_flags:
      - chemical_name: "Benzene"
        is_compliant:  False
        detected_concentration: "6%"
        regulatory_limit: "1 ppm TWA"
        source_citation: <text from regulatory_framework.txt Benzene paragraph>

    hardware_flags:
      - equipment_name: "soda-lime glass"
        target_temperature_celsius: 120.0
        max_safe_temperature_celsius: 100.0
        is_safe: False

If this output is produced correctly, all 6 course concepts are working end-to-end.

---

## Course Concept Checklist (Final Verification)

    [ ] Tokens & Parameters   : constants.py has LLM_TEMPERATURE=0.0 and MAX_OUTPUT_TOKENS=1024
                                 Both are explicitly passed to ollama.chat() in agent.py and commented.

    [ ] Context Windows       : constants.py has RAG_TOP_K=3.
                                 Only 3 chunks are injected into context. Commented in agent.py.

    [ ] System Prompting      : SYSTEM_PROMPT in agent.py defines persona + 4 guardrail rules.

    [ ] Guardrails            : Rule 1 (no guessing), Rule 2 (no assuming parameters) enforced
                                 in system prompt and Pydantic mandatory fields.

    [ ] Vector DB Pipeline    : ingest.py = Chunk + Embed + Store.
                                 rag.py = Retrieve. Embedding model named: all-MiniLM-L6-v2.

    [ ] Agentic Tool / MCP    : mcp_server.py = genuine MCP server.
                                 agent.py = genuine MCP client over stdio.

    [ ] Grounded Citations     : source_citation is a mandatory Pydantic field. Cannot be null.
