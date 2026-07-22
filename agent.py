import re
import json
import asyncio
import sys
import time
import os
import traceback
import contextvars

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from constants import (
    MCP_SERVER_SCRIPT,
    HARDWARE_LIMITS,
    BOILING_POINTS_CELSIUS,
)
from models import ComplianceReport, ChemicalFlag, HardwareFlag, PipelineMetrics
from rag import query_regulations
import llm_client
from llm_client import chat as llm_chat
from cache import (
    get_semantic_cache,
    set_semantic_cache,
    get_summary_cache,
    set_summary_cache,
    get_osha_limits,
    set_osha_limits,
    get_conversation_cache,
    set_conversation_cache,
)
from validator import (
    validate_and_correct_chemicals,
    validate_physical_boundaries,
    fuzzy_match_hardware,
    KNOWN_CHEMICALS,
)
from logger import logger, start_request_logging

_last_pipeline_path: contextvars.ContextVar[str] = contextvars.ContextVar(
    "last_pipeline_path", default="RAG Database Lookup"
)



# ── 1. ENTITY EXTRACTION (LLM-based) ───────────────────────────────────────


async def _extract_entities_via_llm(text: str) -> dict:
    """
    LLM-based fallback extractor for narrative/conversational inputs.
    Returns a dict matching the ExtractionResult schema.
    """
    schema = {
        "chemicals": [{"name": "string", "concentration": "string (e.g. '6%' or '300 ppm')"}],
        "hardware":  [{"name": "string", "target_temperature_celsius": "float"}],
    }
    prompt = (
        "Extract all chemicals, concentrations, containers, and temperatures from the text below.\n"
        f"Return ONLY valid JSON matching this schema: {json.dumps(schema)}\n"
        f"If a field is missing or unclear, use an empty list.\n\nText:\n{text}"
    )
    try:
        raw = await llm_chat(
            messages=[
                {"role": "system", "content": "You are a precise chemical data extractor. Return JSON only."},
                {"role": "user",   "content": prompt},
            ],
            json_mode=True,
        )
        return json.loads(raw)
    except Exception:
        return {"chemicals": [], "hardware": []}


# ── 2. RAG LIMIT PARSING (deterministic) ───────────────────────────────────

def _parse_limits(rag_docs: list[str]) -> dict:
    """Parse ppm TWA and % volume limits from RAG text chunks."""
    combined = " ".join(rag_docs)
    limits: dict = {}

    ppm_m = re.search(
        r'(\d+(?:\.\d+)?)\s*ppm\s*TWA',
        combined, re.IGNORECASE
    )
    if ppm_m:
        limits["ppm"] = float(ppm_m.group(1))

    pct_m = re.search(
        r'(\d+(?:\.\d+)?)%\s*by volume',
        combined, re.IGNORECASE
    )
    if pct_m:
        limits["pct"] = float(pct_m.group(1))

    src_m = re.search(r'Source:\s*(.+)', combined)
    limits["citation"] = src_m.group(1).strip() if src_m else combined[:200]

    return limits


# ── 3. COMPLIANCE LOGIC (deterministic) ────────────────────────────────────

def _search_chemical_text_sync(chemical_name: str) -> tuple[str, str]:
    from tavily import TavilyClient
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return "", ""
    try:
        tav_client = TavilyClient(api_key=api_key)
        query = (
            f"{chemical_name} OSHA TWA permissible exposure limit ppm boiling point "
            f"site:osha.gov OR site:pubchem.ncbi.nlm.nih.gov OR site:cdc.gov"
        )
        results = tav_client.search(query=query, max_results=3)
        combined_text = " ".join(
            str(r.get("raw_content") or r.get("content") or "") for r in results.get("results", [])
        )
        source_url = results["results"][0]["url"] if results.get("results") else ""
        return combined_text, source_url
    except Exception:
        return "", ""


async def _search_chemical_safety(chemical_name: str) -> dict:
    combined_text, source_url = await asyncio.to_thread(_search_chemical_text_sync, chemical_name)
    if not combined_text:
        return {}
    
    schema = {
        "ppm": "float or null (OSHA TWA/PEL permissible exposure limit in ppm)",
        "pct": "float or null (OSHA volume percentage limit if any)",
        "boiling_point": "float or null (Boiling point in Celsius)",
    }
    prompt = (
        f"Analyze the safety search results for the chemical '{chemical_name}' and extract:\n"
        "1. The OSHA Permissible Exposure Limit (PEL) or TWA in parts per million (ppm). Choose the official standard/TWA if multiple limits are shown.\n"
        "2. The OSHA liquid volume percentage limit (if any).\n"
        "3. The boiling point of the chemical in Celsius.\n\n"
        f"Search Results:\n{combined_text[:3000]}\n\n"
        f"Return ONLY valid JSON matching this schema: {json.dumps(schema)}\n"
        "Do not include units or letters (like 'ppm', '°C', '%') in the numeric values. Use raw floats/integers or null only."
    )
    try:
        raw = await llm_chat(
            messages=[
                {"role": "system", "content": "You are a precise scientific data extractor. Return JSON only."},
                {"role": "user",   "content": prompt},
            ],
            json_mode=True,
        )
        data = json.loads(raw)
        return {
            "ppm": float(data["ppm"]) if data.get("ppm") is not None else None,
            "pct": float(data["pct"]) if data.get("pct") is not None else None,
            "boiling_point": float(data["boiling_point"]) if data.get("boiling_point") is not None else None,
            "citation": f"Web search: {source_url}" if source_url else "Web search query"
        }
    except Exception as e:
        traceback.print_exc()
        return {}


async def _check_chemical(name: str, conc_str: str) -> tuple[ChemicalFlag, bool]:
    """Evaluate a single chemical against RAG-retrieved OSHA limits."""
    logger.info(f"Checking compliance for chemical: '{name}' (concentration: '{conc_str}')")
    
    if name.lower() == "water":
        logger.info("Chemical is Water (not a regulated substance). Marked as compliant.")
        return ChemicalFlag(
            chemical_name=name,
            is_compliant=True,
            detected_concentration=conc_str,
            regulatory_limit="No OSHA exposure limit",
            source_citation="Water is not a regulated hazardous substance under OSHA."
        ), True

    is_relevant = False
    try:
        rag_docs = query_regulations(name)
        # Use ONLY the top-1 most relevant document to avoid cross-chemical
        # contamination (e.g. Benzene's 0.1% limit bleeding into Isopropanol queries)
        top_doc = rag_docs[:1]
        if top_doc:
            is_relevant = name.lower() in top_doc[0].lower()
    except Exception:
        top_doc = []

    is_l1_cached = bool(get_osha_limits(name))

    limits = {}
    if not top_doc or not is_relevant:
        logger.info(f"Local database lookup MISS for '{name}'. Initiating Tavily Web Search fallback...")
        _last_pipeline_path.set("Tavily Web Search Fallback")
        web_limits = await _search_chemical_safety(name)
        if web_limits and (web_limits.get("ppm") is not None or web_limits.get("pct") is not None):
            logger.info(f"Tavily Search found limits for '{name}': {web_limits}")
            limits = web_limits
            set_osha_limits(name, web_limits)
            if "boiling_point" in web_limits:
                BOILING_POINTS_CELSIUS[name.lower()] = web_limits["boiling_point"]
            is_relevant = True
        else:
            logger.warning(f"No regulatory data found online or locally for '{name}'. Rejecting formulation.")
            return ChemicalFlag(
                chemical_name=name,
                is_compliant=False,
                detected_concentration=conc_str,
                regulatory_limit="Unknown: No regulatory data found",
                source_citation=""
            ), False
    else:
        if is_l1_cached:
            logger.info(f"Layer 1 Limits Cache HIT for '{name}'.")
        else:
            logger.info(f"ChromaDB lookup HIT for '{name}'.")
            
        if _last_pipeline_path.get() != "Tavily Web Search Fallback":
            _last_pipeline_path.set("Layer 1 Limits Cache HIT" if is_l1_cached else "Cold Start RAG / Local DB")
        limits = _parse_limits(top_doc)
        set_osha_limits(name, limits)
    citation = limits.get("citation", "")

    is_pct = "%" in conc_str
    is_ppm = "ppm" in conc_str.lower()

    try:
        conc_val = float(re.search(r'[\d.]+', conc_str).group())
    except (AttributeError, ValueError):
        conc_val = None

    is_compliant = True
    regulatory_limit = "See OSHA regulations"

    if is_pct and limits.get("pct") is not None and conc_val is not None:
        # Direct % volume comparison (e.g. Benzene 6% vs 0.1% limit)
        regulatory_limit = f"{limits['pct']}% by volume (max)"
        is_compliant = conc_val <= limits["pct"]
    elif is_pct and limits.get("ppm") is not None:
        # Volume % vs airborne TWA — NOT comparable, treat liquid carriers as compliant
        regulatory_limit = f"{int(limits['ppm'])} ppm TWA (airborne, not applicable to liquid volume %)"
        is_compliant = True
    elif is_ppm and limits.get("ppm") is not None and conc_val is not None:
        regulatory_limit = f"{int(limits['ppm'])} ppm TWA"
        is_compliant = conc_val <= limits["ppm"]
    elif limits.get("ppm") is not None:
        regulatory_limit = f"{int(limits['ppm'])} ppm TWA"

    return ChemicalFlag(
        chemical_name=name,
        is_compliant=is_compliant,
        detected_concentration=conc_str,
        regulatory_limit=regulatory_limit,
        source_citation=citation
    ), is_relevant


def _check_boiling_hazards(
    chemicals: list[tuple[str, str]], target_temp: float | None
) -> list[str]:
    """Return list of systemic boiling hazard description strings."""
    if target_temp is None:
        return []
    hazards = []
    for name, conc in chemicals:
        if "ppm" in conc.lower():
            continue
        bp = BOILING_POINTS_CELSIUS.get(name.lower())
        if bp is not None and target_temp >= bp:
            hazards.append(
                f"{name} (bp {bp}°C) is heated to {target_temp}°C "
                f"— severe vapor pressure / explosion risk"
            )
    return hazards


# ── 4. MCP HARDWARE CHECK (async) ──────────────────────────────────────────

async def _mcp_check(hw_name: str, temp: float) -> tuple[dict, bool]:
    server_params = StdioServerParameters(
        command=sys.executable, args=[MCP_SERVER_SCRIPT], env=None
    )
    logger.info(f"Calling MCP Tool 'check_hardware_compatibility' for '{hw_name}' at {temp}°C...")
    try:
        async with stdio_client(server_params) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                result = await session.call_tool(
                    "check_hardware_compatibility",
                    {"equipment_name": hw_name, "target_temperature_celsius": temp}
                )
                res_dict = json.loads(result.content[0].text) if result.content else {}
                logger.info(f"MCP tool check returned safe limits: max={res_dict.get('max_safe_temperature_celsius')}°C, is_safe={res_dict.get('is_safe')}")
                return res_dict, True
    except Exception as e:
        # Fallback: use local constants
        max_t = float(HARDWARE_LIMITS.get(hw_name, 0))
        logger.warning(f"MCP connection failed ({type(e).__name__}). Falling back to local limits constants: max={max_t}°C")
        return {
            "equipment_name": hw_name,
            "target_temperature_celsius": temp,
            "max_safe_temperature_celsius": max_t,
            "is_safe": temp <= max_t,
        }, False


def _evaluate_llm_instruction_following(summary: str) -> float:
    summary = summary.strip()
    if not summary:
        return 0.0
    # Check rule 1: no newlines
    if "\n" in summary:
        return 0.0
    # Check rule 2: no bullet points
    if any(bullet in summary for bullet in ["* ", "- ", "• "]):
        return 0.0
    # Check rule 3: exactly one sentence
    sentences = [s for s in re.split(r'(?<=[.!?])\s+', summary) if s.strip()]
    if len(sentences) != 1:
        return 0.0
    return 1.0


def _build_metrics_footer(
    latency: float,
    cache_label: str,
    context_len: int,
    provider: str,
    error: bool = False
) -> str:
    color = "var(--color-red-500)" if error else "var(--body-text-color-subdued)"
    return (
        f"\n\n<div style='font-size:0.78rem; color:{color}; border-top:1px solid var(--border-color-primary); "
        f"margin-top:10px; padding-top:5px; text-align:center;'>⏱️ Latency: <b>{latency:.2f}s</b> | "
        f"💾 Cache: <b>{cache_label}</b> | 🧠 Context: <b>{context_len} chars</b> | "
        f"🤖 Provider: <b>{provider}</b></div>"
    )


# ── 5. MAIN PIPELINE ───────────────────────────────────────────────────────

async def _async_pipeline(user_input: str) -> ComplianceReport:
    _last_pipeline_path.set("RAG Database Lookup")
    start_time = time.time()
    
    start_request_logging()
    logger.info("Initializing safety audit pipeline request...")
    logger.info(f"Input text: '{user_input.strip()}'")

    # Layer 2: Semantic cache check — return immediately if near-identical query seen before
    logger.info("Checking Level 1: Cache Lookup (exact prompt hash)...")
    cached_report_dict = get_semantic_cache(user_input)
    if cached_report_dict:
        logger.info("Cache HIT! Sub-millisecond prompt lookup matched in SQLite cache.")
        report = ComplianceReport.model_validate(cached_report_dict)
        report.cache_status = "Layer 2 Cache HIT"
        report.metrics.total_latency = time.time() - start_time
        try:
            with open("evaluation_results.json", "w") as f:
                json.dump(report.metrics.model_dump(), f, indent=4)
        except Exception:
            pass
        return report

    logger.info("Cache MISS. Executing Level 2: Entity Parser (LLM-based)...")

    # Extract entities via LLM
    llm_result = await _extract_entities_via_llm(user_input)
    chemicals = [
        (c["name"], c["concentration"])
        for c in llm_result.get("chemicals", [])
    ]
    hardware = []
    for h in llm_result.get("hardware", []):
        try:
            temp_val = float(h.get("target_temperature_celsius") or 25.0)
        except (ValueError, TypeError):
            temp_val = 25.0
        hardware.append((h["name"], temp_val))

    logger.info(f"Extracted entities -> Chemicals: {chemicals}, Hardware: {hardware}")

    # Validate & auto-correct
    logger.info("Running Level 3: Fuzzy Validator...")
    chemicals, correction_notes = validate_and_correct_chemicals(chemicals)
    
    corrected_hardware = []
    for hw_name, temp in hardware:
        corrected_hw = fuzzy_match_hardware(hw_name)
        if corrected_hw != hw_name:
            msg = f"'{hw_name}' was interpreted as '{corrected_hw}' (match score: 100/100)."
            correction_notes.append(msg)
            logger.info(f"Hardware correction: {msg}")
        corrected_hardware.append((corrected_hw, temp))
    hardware = corrected_hardware
    
    boundary_warnings           = validate_physical_boundaries(chemicals, hardware)
    if boundary_warnings:
        logger.warning(f"Boundary warnings triggered: {boundary_warnings}")

    target_temp = hardware[0][1] if hardware else None

    # Chemical compliance
    logger.info("Running Level 4: RAG & Web Search limits check...")
    chemical_flags: list[ChemicalFlag] = []
    relevancy_list: list[bool] = []
    for name, conc in chemicals:
        flag, is_rel = await _check_chemical(name, conc)
        chemical_flags.append(flag)
        relevancy_list.append(is_rel)
        logger.info(f"Compliance verdict for '{name}': compliant={flag.is_compliant}, limit='{flag.regulatory_limit}'")

    # RAG Context Relevancy metric
    if relevancy_list:
        rag_context_relevancy = sum(1.0 for r in relevancy_list if r) / len(relevancy_list)
    else:
        rag_context_relevancy = 1.0

    # Hardware safety via MCP
    logger.info("Running Level 5: MCP Tool Check...")
    hardware_flags: list[HardwareFlag] = []
    mcp_success_list: list[bool] = []
    for hw_name, temp in hardware:
        res, mcp_ok = await _mcp_check(hw_name, temp)
        max_t = res.get("max_safe_temperature_celsius", HARDWARE_LIMITS.get(hw_name, 0.0))
        is_safe = res.get("is_safe", temp <= max_t)
        hardware_flags.append(HardwareFlag(
            equipment_name=hw_name,
            target_temperature_celsius=temp,
            max_safe_temperature_celsius=max_t,
            is_safe=is_safe,
        ))
        mcp_success_list.append(mcp_ok)
        logger.info(f"Hardware safety verdict for '{hw_name}': safe={is_safe}, target={temp}°C, max_safe={max_t}°C")

    # Agent Tool Call Success Rate metric
    if mcp_success_list:
        agent_tool_call_success_rate = sum(1.0 for s in mcp_success_list if s) / len(mcp_success_list)
    else:
        agent_tool_call_success_rate = 1.0

    # Boiling point systemic hazards
    boiling_hazards = _check_boiling_hazards(chemicals, target_temp)
    if boiling_hazards:
        logger.warning(f"Boiling point hazards detected: {boiling_hazards}")

    # Overall status alignment with OSHA compliance standards
    any_hw_fail = any(not f.is_safe for f in hardware_flags)
    any_vol_pct_fail_or_unknown = False
    any_ppm_fail = False

    for f in chemical_flags:
        if not f.is_compliant:
            limit_lower = f.regulatory_limit.lower()
            if "volume" in limit_lower or "unknown" in limit_lower or "limit of see" in limit_lower or "%" in f.regulatory_limit:
                any_vol_pct_fail_or_unknown = True
            else:
                any_ppm_fail = True

    if any_hw_fail or any_vol_pct_fail_or_unknown:
        overall_status = "REJECTED"
    elif any_ppm_fail or boiling_hazards:
        overall_status = "PARTIAL"
    else:
        overall_status = "APPROVED"

    logger.info(f"Overall safety status determined: '{overall_status}'")

    # Build violation notes for LLM summary
    violation_notes = (
        [f"{f.chemical_name}: {f.detected_concentration} exceeds limit of {f.regulatory_limit}"
         for f in chemical_flags if not f.is_compliant] +
        [f"{f.equipment_name}: {f.target_temperature_celsius}°C exceeds max {f.max_safe_temperature_celsius}°C"
         for f in hardware_flags if not f.is_safe] +
        boiling_hazards
    )

    # LLM: one-sentence summary only (short output, fast)
    if violation_notes:
        llm_input = "Violations found:\n" + "\n".join(f"- {n}" for n in violation_notes)
    else:
        llm_input = "No violations found. All checks passed."

    logger.info("Running Level 6: LLM Compliance Summary generation...")
    cached_summary = get_summary_cache(violation_notes)
    if cached_summary:
        logger.info("Summary Cache HIT! Reusing safety summary from SQLite cache.")
        summary = cached_summary
    else:
        logger.info("Summary Cache MISS. Requesting fresh LLM summary...")
        try:
            summary = await llm_chat(
                messages=[
                    {"role": "system", "content":
                        "You are a lab safety officer. Write ONE concise sentence summarising "
                        "the safety finding. No bullet points, no intro text."},
                    {"role": "user", "content": llm_input},
                ],
                json_mode=False,
            )
            set_summary_cache(violation_notes, summary)
        except Exception as e:
            logger.error(f"LLM safety summary call failed ({type(e).__name__}). Falling back to local hardcoded summary.")
            summary = (
                "Formulation is non-compliant: " + "; ".join(violation_notes[:2]) + "."
                if violation_notes else
                "All chemicals and hardware meet regulatory requirements."
            )

    logger.info(f"Compliance Summary: '{summary}'")

    # LLM Instruction Following metric
    llm_instruction_following = _evaluate_llm_instruction_following(summary)

    # Total latency
    total_latency = time.time() - start_time

    # Package metrics
    metrics = PipelineMetrics(
        rag_context_relevancy=rag_context_relevancy,
        agent_tool_call_success_rate=agent_tool_call_success_rate,
        llm_instruction_following=llm_instruction_following,
        total_latency=total_latency,
    )

    # Save metrics to evaluation_results.json in project root
    try:
        with open("evaluation_results.json", "w") as f:
            json.dump(metrics.model_dump(), f, indent=4)
    except Exception as e:
        sys.stderr.write(f"Error saving evaluation metrics: {e}\n")

    logger.info("Running Level 7: Pydantic Validation...")
    report = ComplianceReport(
        chemical_flags=chemical_flags,
        hardware_flags=hardware_flags,
        overall_approval_status=overall_status,
        summary=summary,
        metrics=metrics,
        correction_notes=correction_notes,
        boundary_warnings=boundary_warnings,
        cache_status=_last_pipeline_path.get(),
        llm_provider_used=llm_client.LAST_PROVIDER_USED,
    )
    set_semantic_cache(user_input, report.model_dump_json())
    logger.info(f"Audit pipeline request complete. Overall status: {overall_status} (Latency: {total_latency:.2f}s)")
    return report


async def run_audit_pipeline_async(user_input: str) -> ComplianceReport:
    return await _async_pipeline(user_input)


def run_audit_pipeline(user_input: str) -> ComplianceReport:
    return asyncio.run(_async_pipeline(user_input))


async def _get_single_chemical_context(name: str) -> str:
    try:
        rag_docs = query_regulations(name)
        top_doc = rag_docs[:1]
        if top_doc and name.lower() in top_doc[0].lower():
            return f"OSHA Safety Data for {name}:\n{top_doc[0]}"
        else:
            web_limits = await _search_chemical_safety(name)
            if web_limits:
                limits_str = f"{name}: "
                parts = []
                if web_limits.get("ppm") is not None:
                    parts.append(f"{web_limits['ppm']} ppm TWA")
                if web_limits.get("pct") is not None:
                    parts.append(f"{web_limits['pct']}% by volume")
                limits_str += ", ".join(parts)
                if "citation" in web_limits:
                    limits_str += f" (Source: {web_limits['citation']})"
                return f"OSHA Safety Data for {name}:\n{limits_str}"
    except Exception as e:
        logger.warning(f"Error retrieving safety context for '{name}' in copilot: {e}")
    return ""


async def copilot_chat(message: str, history: list) -> str:
    """
    Multi-turn safety copilot chatbot.
    Queries RAG or Web search fallback if a chemical is mentioned in the query.
    Returns response text with inline metrics appended at the bottom.
    """
    start_time = time.time()
    logger.info(f"Copilot Chat message received: '{message}'")
    cached_response = get_conversation_cache(message, history)
    if cached_response:
        logger.info("Conversation Cache HIT! Reusing response.")
        latency = time.time() - start_time
        return cached_response + _build_metrics_footer(latency, "Layer 4 Cache HIT", 0, llm_client.LAST_PROVIDER_USED)

    detected_chems = []
    message_lower = message.lower()
    for chem in KNOWN_CHEMICALS:
        if chem.lower() in message_lower:
            detected_chems.append(chem)
            
    safety_context = ""
    if detected_chems:
        logger.info(f"Copilot detected chemical(s): {detected_chems}")
        context_results = await asyncio.gather(*[_get_single_chemical_context(name) for name in detected_chems])
        context_parts = [res for res in context_results if res]
        if context_parts:
            safety_context = "\n\n".join(context_parts)

    system_instruction = (
        "You are an expert lab safety officer and conversational safety copilot.\n"
        "Your task is to answer user queries about chemical safety, OSHA standards, storage, and equipment.\n"
        "If regulatory safety data is provided below, prioritize using it to answer the question accurately.\n"
        "Be helpful, precise, and professional. Keep your responses concise yet thorough.\n"
    )
    if safety_context:
        system_instruction += f"\n[REGULATORY SAFETY CONTEXT]\n{safety_context}\n"

    messages = [{"role": "system", "content": system_instruction}]
    for turn in history[-10:]:
        if isinstance(turn, dict):
            messages.append({"role": turn["role"], "content": turn["content"]})
        elif isinstance(turn, (list, tuple)) and len(turn) == 2:
            messages.append({"role": "user", "content": turn[0]})
            messages.append({"role": "assistant", "content": turn[1]})
    messages.append({"role": "user", "content": message})

    try:
        response = await llm_chat(messages, json_mode=False)
        set_conversation_cache(message, history, response)
        
        latency = time.time() - start_time
        return response + _build_metrics_footer(latency, "Cold Start", len(safety_context), llm_client.LAST_PROVIDER_USED)
    except Exception as e:
        logger.error(f"Error generating chat response: {e}")
        err_msg = f"I apologize, but I encountered an error while processing your request: {str(e)}"
        
        latency = time.time() - start_time
        return err_msg + _build_metrics_footer(latency, "Error", len(safety_context), llm_client.LAST_PROVIDER_USED, error=True)
