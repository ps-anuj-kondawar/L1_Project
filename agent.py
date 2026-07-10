import re
import json
import asyncio
import sys
import ollama

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from constants import (
    OLLAMA_MODEL,
    MCP_SERVER_SCRIPT,
    HARDWARE_LIMITS,
    BOILING_POINTS_CELSIUS,
)
from models import ComplianceReport, ChemicalFlag, HardwareFlag
from rag import query_regulations


# ── 1. ENTITY EXTRACTION (deterministic, regex-based) ──────────────────────

def _extract_chemicals(text: str) -> list[tuple[str, str]]:
    """Return list of (chemical_name, concentration_string) from free text."""
    found: list[tuple[str, str]] = []
    seen: set[str] = set()

    def _add(name: str, conc: str) -> None:
        key = name.strip().lower()
        skip = {"the", "by", "in", "and", "of", "at", "from", "a", "an",
                "target", "mixture", "formulation", "operating", "containment",
                "process", "conditions", "notes", "unit", "formula"}
        if key and key not in skip and key not in seen:
            seen.add(key)
            found.append((name.strip(), conc.strip()))

    # Pattern A: "<number>% <Word>" — e.g. "6% Benzene", "70% Isopropanol"
    for m in re.finditer(
        r'(\d+(?:\.\d+)?)\s*(%)\s+([A-Za-z][A-Za-z\-]+)',
        text
    ):
        _add(m.group(3), m.group(1) + m.group(2))

    # Pattern B: "<number> ppm <Word>" — e.g. "300 ppm Toluene"
    for m in re.finditer(
        r'(\d+(?:\.\d+)?)\s*(ppm)\s+([A-Za-z][A-Za-z\-]+)',
        text, re.IGNORECASE
    ):
        _add(m.group(3), m.group(1) + " " + m.group(2))

    # Pattern C: "<Word>: <number>% by volume" — e.g. "Acetone: 50% by volume"
    for m in re.finditer(
        r'([A-Za-z][A-Za-z\-]+)\s*:\s*(\d+(?:\.\d+)?)\s*(%)\s*(?:by volume)?',
        text, re.IGNORECASE
    ):
        _add(m.group(1), m.group(2) + m.group(3))

    # Pattern D: "<Word>: <number> ppm" — e.g. "Benzene: 600 ppm"
    for m in re.finditer(
        r'([A-Za-z][A-Za-z\-]+)\s*:\s*(\d+(?:\.\d+)?)\s*(ppm)',
        text, re.IGNORECASE
    ):
        _add(m.group(1), m.group(2) + " " + m.group(3))

    return found


def _extract_hardware(text: str) -> list[tuple[str, float]]:
    """Return list of (hw_key, target_temp_C) from free text."""
    lower = text.lower()

    # Match temperature — e.g. "120C", "85C", "22°C", "120 celsius"
    # c(?!\w) avoids matching "celsius" twice; no word boundary needed before C
    temp_match = re.search(
        r'(\d+(?:\.\d+)?)\s*(?:°[Cc]|[Cc](?!\w)|[Cc]elsius)',
        text, re.IGNORECASE
    )
    if not temp_match:
        return []
    target_temp = float(temp_match.group(1))

    return [
        (hw_name, target_temp)
        for hw_name in HARDWARE_LIMITS
        if hw_name in lower
    ]


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

def _check_chemical(name: str, conc_str: str) -> ChemicalFlag:
    """Evaluate a single chemical against RAG-retrieved OSHA limits."""
    if name.lower() == "water":
        return ChemicalFlag(
            chemical_name=name,
            is_compliant=True,
            detected_concentration=conc_str,
            regulatory_limit="No OSHA exposure limit",
            source_citation="Water is not a regulated hazardous substance under OSHA."
        )

    try:
        rag_docs = query_regulations(name)
        # Use ONLY the top-1 most relevant document to avoid cross-chemical
        # contamination (e.g. Benzene's 0.1% limit bleeding into Isopropanol queries)
        top_doc = rag_docs[:1]
    except Exception:
        top_doc = []

    if not top_doc:
        return ChemicalFlag(
            chemical_name=name,
            is_compliant=True,
            detected_concentration=conc_str,
            regulatory_limit="Unknown: No regulatory data found",
            source_citation=""
        )

    limits = _parse_limits(top_doc)
    citation = limits.get("citation", "")

    is_pct = "%" in conc_str
    is_ppm = "ppm" in conc_str.lower()

    try:
        conc_val = float(re.search(r'[\d.]+', conc_str).group())
    except (AttributeError, ValueError):
        conc_val = None

    is_compliant = True
    regulatory_limit = "See OSHA regulations"

    if is_pct and "pct" in limits and conc_val is not None:
        # Direct % volume comparison (e.g. Benzene 6% vs 0.1% limit)
        regulatory_limit = f"{limits['pct']}% by volume (max)"
        is_compliant = conc_val <= limits["pct"]
    elif is_pct and "ppm" in limits:
        # Volume % vs airborne TWA — NOT comparable, treat liquid carriers as compliant
        regulatory_limit = f"{int(limits['ppm'])} ppm TWA (airborne, not applicable to liquid volume %)"
        is_compliant = True
    elif is_ppm and "ppm" in limits and conc_val is not None:
        regulatory_limit = f"{int(limits['ppm'])} ppm TWA"
        is_compliant = conc_val <= limits["ppm"]
    elif "ppm" in limits:
        regulatory_limit = f"{int(limits['ppm'])} ppm TWA"

    return ChemicalFlag(
        chemical_name=name,
        is_compliant=is_compliant,
        detected_concentration=conc_str,
        regulatory_limit=regulatory_limit,
        source_citation=citation
    )


def _check_boiling_hazards(
    chemicals: list[tuple[str, str]], target_temp: float | None
) -> list[str]:
    """Return list of systemic boiling hazard description strings."""
    if target_temp is None:
        return []
    hazards = []
    for name, _ in chemicals:
        bp = BOILING_POINTS_CELSIUS.get(name.lower())
        if bp is not None and target_temp > bp:
            hazards.append(
                f"{name} (bp {bp}°C) is heated to {target_temp}°C "
                f"— severe vapor pressure / explosion risk"
            )
    return hazards


# ── 4. MCP HARDWARE CHECK (async) ──────────────────────────────────────────

async def _mcp_check(hw_name: str, temp: float) -> dict:
    server_params = StdioServerParameters(
        command=sys.executable, args=[MCP_SERVER_SCRIPT], env=None
    )
    try:
        async with stdio_client(server_params) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                result = await session.call_tool(
                    "check_hardware_compatibility",
                    {"equipment_name": hw_name, "target_temperature_celsius": temp}
                )
                return json.loads(result.content[0].text) if result.content else {}
    except Exception:
        # Fallback: use local constants
        max_t = float(HARDWARE_LIMITS.get(hw_name, 0))
        return {
            "equipment_name": hw_name,
            "target_temperature_celsius": temp,
            "max_safe_temperature_celsius": max_t,
            "is_safe": temp <= max_t,
        }


# ── 5. MAIN PIPELINE ───────────────────────────────────────────────────────

async def _async_pipeline(user_input: str) -> ComplianceReport:
    # Extract entities
    chemicals = _extract_chemicals(user_input)
    hardware  = _extract_hardware(user_input)
    target_temp = hardware[0][1] if hardware else None

    # Chemical compliance
    chemical_flags: list[ChemicalFlag] = [
        _check_chemical(name, conc) for name, conc in chemicals
    ]

    # Hardware safety via MCP
    hardware_flags: list[HardwareFlag] = []
    for hw_name, temp in hardware:
        res = await _mcp_check(hw_name, temp)
        max_t = res.get("max_safe_temperature_celsius", HARDWARE_LIMITS.get(hw_name, 0.0))
        is_safe = res.get("is_safe", temp <= max_t)
        hardware_flags.append(HardwareFlag(
            equipment_name=hw_name,
            target_temperature_celsius=temp,
            max_safe_temperature_celsius=max_t,
            is_safe=is_safe,
        ))

    # Boiling point systemic hazards
    boiling_hazards = _check_boiling_hazards(chemicals, target_temp)

    # Overall status
    any_chem_fail = any(not f.is_compliant for f in chemical_flags)
    any_hw_fail   = any(not f.is_safe     for f in hardware_flags)

    if any_chem_fail or any_hw_fail:
        overall_status = "REJECTED"
    elif boiling_hazards:
        overall_status = "PARTIAL"
    else:
        overall_status = "APPROVED"

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

    try:
        resp = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[
                {"role": "system", "content":
                    "You are a lab safety officer. Write ONE concise sentence summarising "
                    "the safety finding. No bullet points, no intro text."},
                {"role": "user", "content": llm_input},
            ],
            options={"temperature": 0.0, "num_predict": 60},
        )
        summary = resp.message.content.strip()
    except Exception:
        summary = (
            "Formulation is non-compliant: " + "; ".join(violation_notes[:2]) + "."
            if violation_notes else
            "All chemicals and hardware meet regulatory requirements."
        )

    return ComplianceReport(
        chemical_flags=chemical_flags,
        hardware_flags=hardware_flags,
        overall_approval_status=overall_status,
        summary=summary,
    )


def run_audit_pipeline(user_input: str) -> ComplianceReport:
    return asyncio.run(_async_pipeline(user_input))
