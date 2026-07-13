# Implementation Design & Decision Log

This document records the complete history of architectural decisions, iterations, bugs encountered, and the reasoning behind every major change made to the Lab Safety Auditor. It is intended to explain **why** the final implementation looks the way it does.

---

## Table of Contents

1. [Initial Implementation — Streamlit + Hardcoded Python](#1-initial-implementation--streamlit--hardcoded-python)
2. [UI Migration — Streamlit → Gradio](#2-ui-migration--streamlit--gradio)
3. [First Refactor — LLM-Only Dynamic Architecture](#3-first-refactor--llm-only-dynamic-architecture)
4. [Second Refactor — Hybrid Architecture (Final)](#4-second-refactor--hybrid-architecture-final)
5. [Bug Fixes During Hybrid Development](#5-bug-fixes-during-hybrid-development)
6. [Model Selection — Speed vs. Accuracy](#6-model-selection--speed-vs-accuracy)
7. [Final Architecture Summary](#7-final-architecture-summary)

---

## 1. Initial Implementation — Streamlit + Hardcoded Python

### What Was Built

The first version of the system was a Streamlit application with the following pipeline:

1. **Entity extraction using hardcoded regex + hardcoded chemical lists**
   - A `known_chems` list contained `["benzene", "acetone", "toluene", "methanol", "isopropanol", "ipa", "water", "ethanol"]`
   - Regex scanned the input for numbers followed by `%` or `ppm`, then proximity-matched to the nearest chemical name from the list
2. **Compliance checking using a hardcoded `REGULATORY_DATA` dictionary**
   - The Python file directly defined all OSHA limits: `{"Benzene": {"max_value_ppm": 1.0, "max_value_pct": 0.1, ...}, ...}`
3. **Hardware checking via the MCP FastMCP server**
4. **LLM (Qwen via Ollama) for the final structured `ComplianceReport` JSON**

### Problems Identified

- **Hardcoded chemical list**: Adding a new chemical required modifying source code, not data.
- **Hardcoded OSHA limits**: The `REGULATORY_DATA` dict was a maintenance liability — regulatory limits change, and the system had no way to pull live data.
- **Streamlit dropdown bug**: Users could edit the text inside the "Example Preset" dropdown (it was not `filterable=False`), making the UI confusing.
- **Speed**: Using a Qwen model for full JSON generation was slow (~30–60 seconds per request).
- **RAG not being used for compliance**: ChromaDB was ingested but the regulatory data was hardcoded in Python, making the RAG retrieval essentially decorative.

---

## 2. UI Migration — Streamlit → Gradio

### Why We Switched

The user observed that:
1. Streamlit's selection boxes were editable, which was confusing.
2. Streamlit's component model caused double-rendering artifacts.
3. Gradio was preferred as a lighter-weight, more direct option.

### Initial Gradio Issues

**Double-styling conflict**: When custom CSS was added and Gradio's default theme was applied simultaneously, text colors clashed (light-themed text became invisible on Gradio's dark-mode default).

**Root cause**: In Gradio 6.0+, the `theme` parameter must be passed to `gr.Blocks(launch=...)`, not to the `Blocks()` constructor. An incorrect placement meant the custom CSS competed with Gradio's default theme CSS.

**Fix 1**: Custom CSS used Gradio's native CSS variables (`var(--background-fill-secondary)`, `var(--body-text-color)`) instead of hardcoded hex values. This ensures compatibility with both light and dark modes.

**Fix 2**: After the user decided they preferred Gradio's default styling entirely, the custom CSS block was stripped and `theme=gr.themes.Base()` was removed from `launch()`, delegating all visual decisions to Gradio's native defaults.

**Output Display**: The first Gradio iteration used raw HTML `<div>` cards with hardcoded hex colors (e.g., `color:#1A202C`), which became invisible in dark mode. These were replaced with `gr.Dataframe()` for structured output, and later with theme-aware HTML cards using CSS variables.

---

## 3. First Refactor — LLM-Only Dynamic Architecture

### Goal

Make the system fully dynamic — no hardcoded chemical lists, no hardcoded OSHA limits. Let the LLM handle everything including entity extraction and compliance evaluation.

### What Was Built

A two-call async pipeline:

1. **LLM Call 1 — Extraction**: The LLM read the user's formulation and output a structured JSON (`ExtractionResult`) with chemical names, concentrations, hardware names, and temperatures.
2. **RAG + MCP Context Gathering**: For each extracted entity, query ChromaDB and call the MCP server.
3. **LLM Call 2 — Evaluation**: The LLM was given the original input, all retrieved OSHA text, and all MCP hardware limits, and asked to produce the final `ComplianceReport` Pydantic JSON.

### Problems Identified

#### Problem 1 — Speed (two LLM calls on CPU)

On the test system (Intel i7-10810U, integrated GPU, 32 GB RAM), each LLM call took 30–60 seconds. With two calls, total latency reached **85–103 seconds** — completely unacceptable for a demo.

| Attempt | Architecture | Avg Latency |
|---------|-------------|-------------|
| 2-call async (`llama3.2:3b`) | Extraction + Evaluation | 85–103s |
| 1-call async (`llama3.2:1b`) | Combined Extraction + Evaluation | 58–61s |

Even the single-call approach was too slow because the output JSON was ~400–700 tokens long, which at ~10 tokens/second on a low-power CPU took 40–70 seconds.

#### Problem 2 — Hallucinations on Small Models

The `llama3.2:1b` model could not reliably follow the complex Pydantic JSON schema while also evaluating compliance logic. Errors included:

- **Inventing chemicals**: Test Case 2 (Isopropanol only) produced a report listing Benzene as a chemical that failed.
- **Wrong status**: Even when violations were described in the summary, the `overall_approval_status` field was set incorrectly (e.g., describing a Benzene violation but setting status to `APPROVED`).
- **Schema non-compliance**: Occasionally the LLM would output incomplete or malformed JSON, causing `model_validate_json` to raise an exception.

#### Problem 3 — RAG Cross-Contamination

With `RAG_TOP_K=5` in a 5-chemical ChromaDB, querying for "Isopropanol" returned all 5 documents. When `_parse_limits()` joined all documents and searched for `% by volume`, it found Benzene's `0.1% by volume` limit and applied it to Isopropanol — incorrectly marking `70% Isopropanol` as non-compliant.

---

## 4. Second Refactor — Hybrid Architecture (Final)

### Design Philosophy

The key insight was: **the LLM is expensive; use it only where it cannot be replaced.**

Compliance evaluation is fundamentally a **rule lookup + comparison** task. Python is infinitely better at deterministic comparisons than an LLM. The LLM's unique value is in **natural language generation** — writing a fluent one-sentence summary.

### What Changed

#### Entity Extraction → Regex (removed LLM Call 1)

Replaced the LLM extraction step with four deterministic regex patterns in `_extract_chemicals()`:

- **Pattern A**: `<number>% <Word>` — handles `6% Benzene`, `70% Isopropanol`
- **Pattern B**: `<number> ppm <Word>` — handles `300 ppm Toluene`
- **Pattern C**: `<Word>: <number>% by volume` — handles `Acetone: 50% by volume`
- **Pattern D**: `<Word>: <number> ppm` — handles `Benzene: 600 ppm`

Hardware extraction became a simple case-insensitive substring match of the input against the `HARDWARE_LIMITS` dictionary keys.

**Why regex instead of LLM**: Regex extracts entities in microseconds with zero hallucination risk. For the formulation patterns common in lab notes, these four patterns cover all realistic inputs.

#### Regulatory Limits → RAG + Python Regex Parsing (removed hardcoded dict)

The `REGULATORY_DATA` dictionary was deleted from `constants.py`. Instead:

1. For each extracted chemical, `query_regulations(name)` fetches the top-1 ChromaDB document.
2. Two regex patterns parse the retrieved text:
   - `(\d+(?:\.\d+)?)\s*ppm\s*TWA` → airborne vapor limit
   - `(\d+(?:\.\d+)?)%\s*by volume` → liquid volume limit

**Why top-1 only**: Using the top-K documents caused cross-chemical contamination. The top-1 result for a given chemical name is almost always the correct chemical's document.

#### Compliance Comparison — Volume% vs ppm TWA

A critical edge case was discovered during testing: safe carrier solvents like Isopropanol (70% vol) were being compared to their airborne `ppm TWA` limits — a category error.

The fix is a three-branch comparison logic:
1. **`% detected` + `% by volume` limit in RAG**: compare directly → Benzene 6% vs 0.1% = FAIL
2. **`% detected` + only `ppm TWA` limit in RAG**: these are incomparable units → mark COMPLIANT (liquid vol % is not an airborne exposure concentration)
3. **`ppm detected` + `ppm TWA` limit**: compare directly → Toluene 300 ppm vs 200 ppm TWA = FAIL

#### Systemic Hazard Detection — Boiling Points

The LLM was supposed to detect systemic hazards (e.g., heating Acetone to 85°C when it boils at 56°C), but it failed consistently with the 1b model.

This was replaced with a deterministic check using a new `BOILING_POINTS_CELSIUS` dictionary in `constants.py`:

```python
BOILING_POINTS_CELSIUS = {
    "acetone": 56.0, "methanol": 65.0, "isopropanol": 82.0,
    "ethanol": 78.0, "toluene": 111.0, "benzene": 80.1, ...
}
```

The `_check_boiling_hazards()` function simply compares the operating temperature against each chemical's boiling point. If exceeded, a `PARTIAL` status is triggered. This is **not hardcoding business logic** — it is encoding physical chemistry constants that never change.

#### LLM Call Reduced to Summary Only

The final LLM call is strictly limited to generating one natural language sentence summarizing the violations. Parameters:
- `num_predict: 60` — forces short output
- `temperature: 0.0` — deterministic
- System prompt enforces: "Write ONE concise sentence. No bullet points."

This single short LLM call takes **3–5 seconds** on the test system.

---

## 5. Bug Fixes During Hybrid Development

### Bug 1 — Temperature Regex Missed Compact Notation

**Problem**: The original hardware extraction regex used `\bc\b` to match the Celsius abbreviation `C`. However, `\b` requires a word boundary, and in `120C` the character before `C` is `0` — a word character — so no word boundary exists before `C`. The regex returned no matches, causing 0 hardware flags in all tests.

**Fix**: Changed `\bc\b` to `[Cc](?!\w)` — this uses a negative lookahead instead of word boundary: match `C` as long as it is not followed by another word character. This correctly matches `120C`, `85C`, `22°C`.

### Bug 2 — RAG Documents Mixed When RAG_TOP_K=5

**Problem**: With `RAG_TOP_K=5` in a 5-chemical database, every query returned all 5 documents. The `_parse_limits()` function joined all docs into one string and found the first `% by volume` match — which was always from the Benzene document. This incorrectly applied Benzene's `0.1%` limit to all chemicals.

**Fix**: Changed `_check_chemical()` to use `rag_docs[:1]` — only the single most semantically relevant document is parsed per chemical.

---

## 6. Model Selection — Speed vs. Accuracy

### System Profile

| Hardware | Spec |
|----------|------|
| CPU | Intel Core i7-10810U @ 1.10GHz (6 cores) |
| GPU | Integrated Intel UHD Graphics (no VRAM) |
| RAM | 32 GB |

All inference runs on CPU only. This constrains throughput to approximately 10–15 tokens/second.

### Model Evaluation

| Model | Tokens/sec (CPU) | 400-token output | Suitable? |
|-------|-----------------|------------------|-----------|
| `llama3.2:1b` | ~15 t/s | ~27s | ✅ Only for short outputs |
| `llama3.2:3b` | ~5 t/s | ~80s | ❌ Too slow |
| `llama3.1:8b` | ~2 t/s | ~200s | ❌ Way too slow |

### Why `llama3.2:1b` Was Retained

After the hybrid architecture reduced LLM output to just 60 tokens, the total LLM time became:
- 60 tokens ÷ 15 t/s = **~4 seconds**

This is fast enough. The 1b model generates fluent single sentences reliably. The complex JSON reasoning that exposed its hallucination weaknesses was entirely moved out of the LLM into deterministic Python.

The `llama3.2:3b` model was downloaded and trialed:
- It was 3× more accurate for complex JSON generation
- It was also 3× slower (85–103s end-to-end vs 3–8s with the hybrid approach)
- For the demo requirement of 10–20 seconds, the speed gain of the hybrid + 1b architecture won

---

## 7. Final Architecture Summary

### Files and Responsibilities

| File | Role | Dynamic or Hardcoded? |
|------|------|-----------------------|
| `agent.py` | Pipeline orchestration, extraction, compliance, MCP call | Fully dynamic |
| `constants.py` | All configuration and data constants | Intentional constants (physical chemistry, infra config) |
| `models.py` | Pydantic schemas for type-safe data transfer | Structure |
| `rag.py` | ChromaDB query wrapper | Dynamic |
| `mcp_server.py` | FastMCP hardware safety tool | Reads from `constants.HARDWARE_LIMITS` |
| `ingest.py` | One-time ChromaDB embedding script | Static |
| `app.py` | Gradio UI | Presentation |

### What Is "Hardcoded" and Why It Is Acceptable

| Item | Location | Why It's a Constant, Not a Bug |
|------|----------|-------------------------------|
| `HARDWARE_LIMITS` | `constants.py` | This IS the hardware database. It is the single source of truth for both the MCP server and the fallback logic. To add new equipment, add one line here. |
| `BOILING_POINTS_CELSIUS` | `constants.py` | Physical chemistry constants. Acetone's boiling point does not change. These are not business rules. |
| Regex extraction patterns | `agent.py` | Cover all realistic formulation note styles. New patterns can be added without changing any other file. |

### What Is Genuinely Dynamic

- **Which chemicals** are evaluated: determined by regex parsing of the user's input — no chemical list is checked.
- **OSHA limits**: fetched from ChromaDB at runtime. Adding a new chemical means adding text to `regulatory_framework.txt` and running `ingest.py`.
- **Hardware limits**: fetched via the MCP server, which reads from `constants.HARDWARE_LIMITS`.
- **LLM model**: controlled by `constants.OLLAMA_MODEL` — change one line to upgrade.

### Performance Benchmarks (Final Architecture)

| Test Case | Status | Time |
|-----------|--------|------|
| Benzene 6% + Soda-lime @ 120°C | `REJECTED` | 7.73s |
| Isopropanol 70% + Polypropylene @ 22°C | `APPROVED` | 2.88s |
| Acetone 50% + Methanol 50% @ 85°C | `PARTIAL` | 5.26s |

All tests pass. All times are within the 10-20 second demo target.
