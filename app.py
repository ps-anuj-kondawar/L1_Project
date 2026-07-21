import gradio as gr
import json
import time
import traceback
from agent import run_audit_pipeline
from constants import OLLAMA_MODEL

example_inputs = {
    "Custom Input (Type below)": "",
    "Test Case: REJECTED (Benzene + unsafe glass)":
        "Formula B: 94% Water, 6% Benzene. Heat the mixture to 120°C in a soda-lime glass beaker.",
    "Test Case: APPROVED (safe solvents)":
        "Mix 70% Isopropanol and 30% Water. Store in a polypropylene container at 25°C.",
    "Test Case: PARTIAL (mixed results)":
        "Formulation: 500 ppm Toluene, 800 ppm Acetone. Heated to 90°C in a polypropylene container.",
}

# Theme-aware CSS using Gradio's native variables
css = """
.card {
    background: var(--background-fill-secondary);
    border: 1px solid var(--border-color-primary);
    border-radius: 8px;
    padding: 1.2rem 1.5rem;
    margin-bottom: 1rem;
    box-shadow: var(--shadow-drop);
}
.card-pass {
    border-left: 4px solid var(--color-green-500);
}
.card-fail {
    border-left: 4px solid var(--color-red-500);
}
.card-title {
    font-size: 1.1rem;
    font-weight: 600;
    color: var(--body-text-color);
    margin-bottom: 0.5rem;
}
.card-label {
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--body-text-color-subdued);
    margin-bottom: 0.1rem;
    margin-top: 0.5rem;
}
.card-value {
    font-size: 0.95rem;
    color: var(--body-text-color);
}
.citation-box {
    background: var(--background-fill-primary);
    border: 1px solid var(--border-color-primary);
    border-radius: 8px;
    padding: 0.7rem 1rem;
    font-size: 0.82rem;
    color: var(--body-text-color-subdued);
    font-style: italic;
    margin-top: 0.8rem;
}
.metrics-card {
    background: var(--background-fill-secondary);
    border: 1px solid var(--border-color-primary);
    border-radius: 8px;
    padding: 1.2rem 1.5rem;
    margin-bottom: 1rem;
    box-shadow: var(--shadow-drop);
    display: flex;
    flex-direction: column;
    gap: 0.8rem;
}
.metric-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-bottom: 0.6rem;
    border-bottom: 1px solid var(--border-color-secondary);
}
.metric-row:last-child {
    border-bottom: none;
    padding-bottom: 0;
}
.metric-name {
    font-size: 0.95rem;
    font-weight: 500;
    color: var(--body-text-color);
}
.metric-badge {
    padding: 0.25rem 0.6rem;
    border-radius: 6px;
    font-size: 0.8rem;
    font-weight: 600;
    font-family: monospace;
}
.badge-green {
    background: rgba(34, 197, 94, 0.15);
    color: rgb(34, 197, 94);
}
.badge-blue {
    background: rgba(59, 130, 246, 0.15);
    color: rgb(59, 130, 246);
}
.badge-orange {
    background: rgba(249, 115, 22, 0.15);
    color: rgb(249, 115, 22);
}
.badge-red {
    background: rgba(239, 68, 68, 0.15);
    color: rgb(239, 68, 68);
}
"""

def on_select_preset(selected):
    return example_inputs[selected]

def run_audit(user_input):
    if not user_input or not user_input.strip():
        return (
            "## ⚠️ ERROR\n**No input provided**",
            "Please enter a formulation note before running the audit.",
            "<p style='color:var(--body-text-color-subdued);'>No audit results loaded.</p>",
            "<p style='color:var(--body-text-color-subdued);'>No audit results loaded.</p>",
            "<p style='color:var(--body-text-color-subdued);'>No audit results loaded.</p>",
            {}
        )
    try:
        start_time = time.time()
        report = run_audit_pipeline(user_input)
        elapsed_time = time.time() - start_time

        # Status badge HTML
        status = report.overall_approval_status.upper()
        if status == "APPROVED":
            status_md = f"## ✅ {status}"
        elif status == "REJECTED":
            status_md = f"## ❌ {status}"
        else:
            status_md = f"## ⚠️ {status}"

        report_summary = f"{status_md}\n**⏱️ Audit completed in {elapsed_time:.2f}s** using {OLLAMA_MODEL}"
        summary_desc = report.summary

        # Chemical Flags HTML Cards
        chem_html = ""
        if report.chemical_flags:
            for flag in report.chemical_flags:
                card_class = "card-pass" if flag.is_compliant else "card-fail"
                icon = "✅" if flag.is_compliant else "❌"
                compliance_label = "COMPLIANT" if flag.is_compliant else "NON-COMPLIANT"
                compliance_color = "var(--color-green-500)" if flag.is_compliant else "var(--color-red-500)"
                
                cite_content = flag.source_citation
                if len(cite_content) > 300:
                    cite_content = cite_content[:300] + "..."

                chem_html += f"""
                <div class="card {card_class}">
                    <div class="card-title">{icon} {flag.chemical_name}
                        <span style="font-size:0.75rem; font-weight:600; color:{compliance_color}; margin-left:0.8rem; text-transform:uppercase; letter-spacing:0.06em;">{compliance_label}</span>
                    </div>
                    <div>
                        <div class="card-label">Detected Concentration</div>
                        <div class="card-value">{flag.detected_concentration}</div>
                        <div class="card-label">Regulatory Limit (OSHA)</div>
                        <div class="card-value">{flag.regulatory_limit}</div>
                    </div>
                    <div class="citation-box">📖 Source Citation: {cite_content}</div>
                </div>
                """
        else:
            chem_html = "<p style='color:var(--body-text-color-subdued);'>No chemicals were identified in the formulation note.</p>"

        # Hardware Flags HTML Cards
        hw_html = ""
        if report.hardware_flags:
            for flag in report.hardware_flags:
                card_class = "card-pass" if flag.is_safe else "card-fail"
                icon = "✅" if flag.is_safe else "❌"
                safety_label = "SAFE" if flag.is_safe else "UNSAFE"
                safety_color = "var(--color-green-500)" if flag.is_safe else "var(--color-red-500)"

                hw_html += f"""
                <div class="card {card_class}">
                    <div class="card-title">{icon} {flag.equipment_name}
                        <span style="font-size:0.75rem; font-weight:600; color:{safety_color}; margin-left:0.8rem; text-transform:uppercase; letter-spacing:0.06em;">{safety_label}</span>
                    </div>
                    <div style="display:flex; gap:2rem;">
                        <div>
                            <div class="card-label">Target Temperature</div>
                            <div class="card-value" style="font-size:1.1rem;">{flag.target_temperature_celsius}°C</div>
                        </div>
                        <div>
                            <div class="card-label">Max Safe Temperature</div>
                            <div class="card-value" style="font-size:1.1rem;">{flag.max_safe_temperature_celsius}°C</div>
                        </div>
                    </div>
                </div>
                """
        else:
            hw_html = "<p style='color:var(--body-text-color-subdued);'>No lab equipment was identified in the formulation note.</p>"

        # Read metrics from evaluation_results.json in project root
        try:
            with open("evaluation_results.json", "r") as f:
                metrics_data = json.load(f)
            rag_pct = metrics_data.get("rag_context_relevancy", 1.0) * 100
            agent_pct = metrics_data.get("agent_tool_call_success_rate", 1.0) * 100
            llm_pct = metrics_data.get("llm_instruction_following", 1.0) * 100
            latency = metrics_data.get("total_latency", elapsed_time)
        except Exception:
            # Fallback to report.metrics
            metrics = report.metrics
            rag_pct = metrics.rag_context_relevancy * 100
            agent_pct = metrics.agent_tool_call_success_rate * 100
            llm_pct = metrics.llm_instruction_following * 100
            latency = metrics.total_latency

        rag_badge_class = "badge-green" if rag_pct >= 90 else ("badge-orange" if rag_pct >= 50 else "badge-red")
        agent_badge_class = "badge-green" if agent_pct >= 90 else ("badge-orange" if agent_pct >= 50 else "badge-red")
        
        llm_badge_class = "badge-green" if llm_pct == 100 else "badge-red"
        llm_status = "PASSED" if llm_pct == 100 else "FAILED"
        
        latency_badge_class = "badge-blue" if latency < 5.0 else ("badge-orange" if latency < 10.0 else "badge-red")

        metrics_html = f"""
        <div class="metrics-card">
            <div class="metric-row">
                <div class="metric-name">RAG Context Relevancy</div>
                <div class="metric-value">
                    <span class="metric-badge {rag_badge_class}">{rag_pct:.0f}%</span>
                </div>
            </div>
            <div class="metric-row">
                <div class="metric-name">Agent Tool Call Success Rate</div>
                <div class="metric-value">
                    <span class="metric-badge {agent_badge_class}">{agent_pct:.0f}%</span>
                </div>
            </div>
            <div class="metric-row">
                <div class="metric-name">LLM Instruction Following</div>
                <div class="metric-value">
                    <span class="metric-badge {llm_badge_class}">{llm_status}</span>
                </div>
            </div>
            <div class="metric-row">
                <div class="metric-name">Round Trip Time</div>
                <div class="metric-value">
                    <span class="metric-badge {latency_badge_class}">{latency:.2f}s</span>
                </div>
            </div>
        </div>
        """

        return report_summary, summary_desc, chem_html, hw_html, metrics_html, report.model_dump()
    except Exception as e:
        err_msg = f"❌ Pipeline Error: {type(e).__name__}: {str(e)}"
        tb = f"```\n{traceback.format_exc()}\n```"
        return (
            "## ⚠️ ERROR\n**Audit execution failed**",
            f"{err_msg}\n{tb}",
            "<p style='color:var(--color-red-500);'>Error occurred during execution.</p>",
            "<p style='color:var(--color-red-500);'>Error occurred during execution.</p>",
            "<p style='color:var(--color-red-500);'>Error occurred during execution.</p>",
            {}
        )


with gr.Blocks(title="Lab Safety Auditor") as demo:
    # Header Banner
    gr.Markdown("""
    # ⚗️ Automated Lab Safety Auditor
    **[RAG] [MCP] [LLM] [Pydantic]** · OSHA Regulatory Compliance Analysis for Chemical Formulations
    """)

    with gr.Row():
        # Input Form
        with gr.Column(scale=3):
            gr.Markdown("### 📝 Formulation Note Input")
            
            # Non-filterable dropdown to prevent keyboard popup / option editing
            preset_dd = gr.Dropdown(
                label="Load an Example Preset:",
                choices=list(example_inputs.keys()),
                value="Custom Input (Type below)",
                filterable=False,
                container=True
            )
            
            user_input = gr.Textbox(
                label="Formulation Note Input",
                placeholder="Enter chemical names, concentrations, equipment and operating temperature...",
                lines=5,
                show_label=False
            )
            
            run_btn = gr.Button("🔍 Run Audit", variant="primary")

        # Sidebar Description
        with gr.Column(scale=1, min_width=200):
            gr.Markdown("""
            ### ⚙️ Pipeline Overview
            * **Step 1: RAG Retrieval**: Query ChromaDB for regulatory data.
            * **Step 2: MCP Tool Call**: Verify thermal compatibility bounds.
            * **Step 3: LLM Analysis**: Generate safely formatted compliance reports.
            * **Step 4: Pydantic Validation**: Validate strict output boundaries.
            
            ---
            
            **Chemicals in database:**
            Benzene · Acetone · Toluene · Methanol · Isopropanol
            
            **Hardware in database:**
            Soda-lime glass · Borosilicate glass · Stainless steel · Polypropylene
            """)

    # Output Section
    gr.Markdown("### 📊 Compliance Report")
    with gr.Row():
        with gr.Column():
            status_badge = gr.Markdown("Submit a formulation to display status.")
            summary_desc = gr.Markdown("")

    with gr.Row():
        with gr.Column(scale=2):
            gr.Markdown("#### 🧪 Chemical Compliance")
            chem_comp = gr.HTML(value="<p style='color:var(--body-text-color-subdued);'>No audit results loaded.</p>")
        with gr.Column(scale=2):
            gr.Markdown("#### 🔩 Hardware Safety")
            hw_comp = gr.HTML(value="<p style='color:var(--body-text-color-subdued);'>No audit results loaded.</p>")
        with gr.Column(scale=1, min_width=250):
            gr.Markdown("#### 📊 Evaluation Metrics")
            metrics_comp = gr.HTML(value="<p style='color:var(--body-text-color-subdued);'>No audit results loaded.</p>")

    with gr.Row():
        with gr.Column():
            with gr.Accordion("🗂️ View Raw JSON Report", open=False):
                raw_json = gr.JSON(label="JSON Output")

    # Footer
    gr.Markdown("""
    ---
    <div style='text-align:center; font-size:0.8rem; margin-bottom: 2rem;'>
        Automated Lab Safety Auditor · OSHA Regulatory Compliance
    </div>
    """)

    # Event Bindings
    preset_dd.change(fn=on_select_preset, inputs=preset_dd, outputs=user_input)
    run_btn.click(
        fn=run_audit, 
        inputs=user_input, 
        outputs=[status_badge, summary_desc, chem_comp, hw_comp, metrics_comp, raw_json]
    )

if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=7860, show_error=True, css=css)
