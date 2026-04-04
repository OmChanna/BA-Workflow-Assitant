"""
BA Workflow Assistant — Streamlit UI
12 Agents · BABOK Grounded · Life Sciences Commercial
"""
import streamlit as st
import json
from backend import (
    run_pipeline, run_correction, draw_flow_svg,
    get_nfr_count, get_gxp_default_count,
    extract_text_from_file, check_context_match,
    AGENT_ARTEFACT_TYPE, AGENT_DOWNSTREAM,
    run_frd_on_demand,
)

# ── Page config ──
st.set_page_config(
    page_title="BA Workflow Assistant",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ──
st.markdown("""
<style>
    .block-container { padding-top: 1rem; }
    .stTabs [data-baseweb="tab-list"] { gap: 2px; }
    .stTabs [data-baseweb="tab"] { padding: 8px 16px; font-size: 13px; }
    div[data-testid="stMetric"] { background: #f8f9fa; padding: 12px; border-radius: 8px; }
    .correction-box { background: #2C2C2A; color: white; padding: 10px 16px; border-radius: 8px; margin-top: 16px; font-size: 13px; }
</style>
""", unsafe_allow_html=True)


# ── Session state init ──
if "pipeline_result" not in st.session_state:
    st.session_state.pipeline_result = None
if "logs" not in st.session_state:
    st.session_state.logs = []
if "api_key" not in st.session_state:
    st.session_state.api_key = ""
if "uploaded_docs" not in st.session_state:
    st.session_state.uploaded_docs = []
if "context_check" not in st.session_state:
    st.session_state.context_check = None


def log_msg(msg):
    """Callback for pipeline logging — stores in session state."""
    st.session_state.logs.append(msg)


def render_correction_widget(tab_agent_id, tab_label):
    """Render a correction form scoped to a specific agent/tab."""
    if st.session_state.pipeline_result is None:
        return
    with st.container():
        st.markdown(f"""<div class="correction-box">
            🔄 <b>BA Review Gate</b> — {tab_label}
            <span style="float:right;font-size:11px;color:#D3D1C7;">BABOK KA5 6.5/6.6</span>
        </div>""", unsafe_allow_html=True)
        correction = st.text_area(
            "Enter your correction",
            placeholder="Be specific: 'Add stakeholder: DPO, regulator, high influence' or 'REQ-003 risk should be 5 not 3'",
            key=f"correction_{tab_agent_id}",
            height=80,
        )
        if st.button(f"Submit Correction & Re-run", key=f"btn_{tab_agent_id}", type="secondary"):
            if correction.strip():
                with st.spinner(f"Re-running {tab_agent_id} with corrections..."):
                    st.session_state.logs = []
                    st.session_state.pipeline_result = run_correction(
                        api_key=st.session_state.api_key,
                        pipeline_result=st.session_state.pipeline_result,
                        agent_id=tab_agent_id,
                        correction_text=correction.strip(),
                        log_fn=log_msg,
                    )
                st.rerun()
            else:
                st.warning("Enter a correction before submitting.")


# ══════════════════════════════════════════════════════════════════════════════
#  SIDEBAR — Project Setup
# ══════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("## 📋 BA Workflow Assistant")
    st.markdown(f"**GPT-4o · 13 Agents · BABOK Grounded**")
    st.markdown(f"NFR Library: {get_nfr_count()} NFRs ({get_gxp_default_count()} GxP defaults)")
    st.divider()

    api_key = st.text_input("OpenAI API Key", type="password", value=st.session_state.api_key)
    if api_key:
        st.session_state.api_key = api_key

    st.divider()
    project_name = st.text_input("Project Name", placeholder="e.g. Veeva CRM Enhancement")
    domain = st.selectbox("Domain", [
        "Life Sciences Commercial", "Life Sciences Regulatory",
        "General IT", "Financial Services", "Healthcare"
    ])
    brief_text = st.text_area("Project Brief", placeholder="Paste your raw client brief here...", height=200)

    # ── File Upload ──
    st.divider()
    st.markdown("**📎 Supporting Documents** *(optional)*")
    st.caption("PDF, Word, Excel, TXT, CSV")
    uploaded_files = st.file_uploader(
        "Upload documents",
        type=["pdf", "docx", "xlsx", "xls", "txt", "csv"],
        accept_multiple_files=True,
        label_visibility="collapsed",
    )
    
    # Process uploaded files
    if uploaded_files:
        new_docs = []
        for uf in uploaded_files:
            # Check if already processed
            existing = [d for d in st.session_state.uploaded_docs if d["filename"] == uf.name]
            if existing:
                new_docs.append(existing[0])
            else:
                parsed = extract_text_from_file(uf)
                new_docs.append(parsed)
        st.session_state.uploaded_docs = new_docs
    else:
        st.session_state.uploaded_docs = []
    
    # Show uploaded docs with delete buttons
    if st.session_state.uploaded_docs:
        docs_to_remove = []
        for i, doc in enumerate(st.session_state.uploaded_docs):
            col_name, col_del = st.columns([4, 1])
            with col_name:
                if doc["success"]:
                    st.markdown(f"✅ **{doc['filename']}** ({doc['file_type']}, {len(doc['text']):,} chars)")
                else:
                    st.markdown(f"❌ **{doc['filename']}** — {doc.get('error', 'Failed')}")
            with col_del:
                if st.button("✕", key=f"del_doc_{i}", help=f"Remove {doc['filename']}"):
                    docs_to_remove.append(i)
        
        # Remove marked docs
        if docs_to_remove:
            st.session_state.uploaded_docs = [d for i, d in enumerate(st.session_state.uploaded_docs) if i not in docs_to_remove]
            st.rerun()
        
        # Context match check button
        if brief_text.strip() and api_key:
            successful_docs = [d for d in st.session_state.uploaded_docs if d["success"]]
            if successful_docs:
                if st.button("🔍 Check Context Match", use_container_width=True):
                    with st.spinner("Checking document alignment..."):
                        st.session_state.context_check = check_context_match(
                            api_key=api_key,
                            brief_text=brief_text.strip(),
                            document_texts=successful_docs,
                        )
                    st.rerun()
        
        # Show context check results
        if st.session_state.context_check:
            cc = st.session_state.context_check
            if cc.get("aligned"):
                st.success(f"✅ {cc.get('summary', 'Documents are aligned with brief.')}")
            else:
                st.error(f"⚠️ Context mismatch detected")
                for w in cc.get("warnings", []):
                    st.warning(w)
                st.info(cc.get("summary", ""))

    st.divider()

    # Combine brief + document texts for pipeline
    combined_brief = brief_text.strip() if brief_text else ""
    successful_docs = [d for d in st.session_state.uploaded_docs if d.get("success")]
    if successful_docs:
        doc_appendix = "\n\n--- SUPPORTING DOCUMENTS ---\n"
        for doc in successful_docs:
            doc_appendix += f"\n[Document: {doc['filename']} ({doc['file_type']})]\n{doc['text'][:3000]}\n"
        combined_brief += doc_appendix

    run_disabled = not (api_key and project_name and (brief_text or successful_docs))
    if st.button("🚀 Structure this Brief", disabled=run_disabled, type="primary", use_container_width=True):
        # Warn if context check showed mismatch
        if st.session_state.context_check and not st.session_state.context_check.get("aligned"):
            st.warning("⚠️ Context mismatch was detected. Proceeding anyway — review results carefully.")
        
        st.session_state.logs = []
        with st.spinner("Running 12 agents through pipeline (~3-4 minutes)..."):
            st.session_state.pipeline_result = run_pipeline(
                api_key=api_key,
                project_name=project_name.strip(),
                domain=domain,
                brief_text=combined_brief,
                log_fn=log_msg,
            )
        st.rerun()

    # Show logs
    if st.session_state.logs:
        with st.expander("Pipeline Log", expanded=False):
            for log in st.session_state.logs:
                st.text(log)


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN CONTENT — Tabs
# ══════════════════════════════════════════════════════════════════════════════

if st.session_state.pipeline_result is None:
    st.markdown("## Welcome to the BA Workflow Assistant")
    st.markdown("""
    Enter your project details in the sidebar and click **Structure this Brief** to run the full pipeline.
    
    **Pipeline:** A01 Stakeholders → A04 BRD → A09 Process Flows → A05 NFR → A08 Risk → A09 FSD → A10 Change Impact → A06 Traceability → A14 Agile/Sprint → A11 Test Scripts → A13 Handover
    
    **On-demand:** A15 FRD (Functional Requirements Document) — generated after BA reviews BRD
    
    **Covers all 8 BABOK phases:** Pre-discovery → Discovery → Requirements → Analysis → Prioritisation → Agile/Scrum → Testing → Handover
    """)
    st.stop()

# ── Data extraction ──
pr = st.session_state.pipeline_result
s = pr["summary"]
r = pr["results"]
risk = s.get("risk_summary", {})

# ── Summary metrics bar ──
head_col1, head_col2 = st.columns([3, 2])
with head_col1:
    st.markdown(f"## {pr['project_name']}")
with head_col2:
    st.caption(f"BA Workflow Assistant · 12 Agents · {pr['domain']}")
c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
c1.metric("Stakeholders", s["stakeholders"])
c2.metric("Requirements", s["requirements"])
c3.metric("NFRs", s["nfrs"])
c4.metric("High+ Risks", risk.get("critical_count", 0) + risk.get("high_count", 0))
c5.metric("User Stories", s.get("user_stories", 0))
c6.metric("Test Cases", s.get("test_cases", 0))
c7.metric("Handover Docs", s.get("handover_docs", 0))

st.divider()

# ── Tabs ──
tabs = st.tabs([
    "👥 Stakeholders", "📄 Requirements", "🔄 Process Flows", "⚙️ NFR Register",
    "⚠️ Risk & Priority", "🏗️ Solution Design", "📋 FRD", "🏃 Agile/Sprint",
    "🧪 Testing", "📦 Handover", "📊 Overview"
])


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 0: STAKEHOLDERS
# ══════════════════════════════════════════════════════════════════════════════
with tabs[0]:
    st.subheader("Stakeholder Analysis — KA1 Task 2.2")
    a01 = r.get("A01", {})
    stkh = a01.get("stakeholders", [])

    if stkh:
        st.dataframe(
            [{"Name": sh.get("name"), "Type": sh.get("stakeholder_type"), "Influence": sh.get("influence_level"),
              "RACI": sh.get("raci_role"), "Reasoning": sh.get("reasoning", "")} for sh in stkh],
            use_container_width=True, hide_index=True,
        )

    # Interview guide
    guide = a01.get("interview_guide", {})
    if guide:
        with st.expander("Interview Guide by Stakeholder Type"):
            for stype, questions in guide.items():
                st.markdown(f"**{stype.replace('_', ' ').title()}**")
                for q in questions:
                    st.markdown(f"- {q}")

    # LS flags
    flags = a01.get("ls_regulatory_flags", [])
    if flags:
        st.warning("**LS Regulatory Flags:** " + "; ".join(flags))

    render_correction_widget("A01", "Stakeholders & RACI")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 1: REQUIREMENTS
# ══════════════════════════════════════════════════════════════════════════════
with tabs[1]:
    st.subheader("Business Requirements Document — KA3 Task 4.4")
    a04 = r.get("A04", {})
    reqs = a04.get("requirements", [])

    # Debug: check if A04 had a parse error
    if a04.get("parse_error"):
        st.error("⚠️ A04 BRD agent returned malformed JSON. The response was too long or truncated. Try with a shorter brief or re-run.")
        with st.expander("Raw A04 Response (debug)"):
            st.code(a04.get("raw_response", "No raw response")[:2000])

    # Executive Summary
    exec_sum = a04.get("executive_summary", {})
    if exec_sum:
        st.markdown("#### Executive Summary")
        st.markdown(f"""<div style="background:#f0f4f8;border-left:4px solid #185FA5;padding:14px 18px;border-radius:0 8px 8px 0;margin-bottom:16px;">
            <div style="font-size:18px;font-weight:600;color:#185FA5;margin-bottom:8px;">{exec_sum.get('project_name', pr['project_name'])}</div>
            <div style="font-size:13px;margin-bottom:8px;">{exec_sum.get('purpose', '')}</div>
            <div style="font-size:12px;color:#555;"><b>Business Drivers:</b> {', '.join(exec_sum.get('business_drivers', []))}</div>
            <div style="font-size:12px;color:#555;"><b>Expected Outcomes:</b> {', '.join(exec_sum.get('expected_outcomes', []))}</div>
            <div style="font-size:12px;color:#555;"><b>Target Users:</b> {', '.join(exec_sum.get('target_users', []))}</div>
        </div>""", unsafe_allow_html=True)
        if exec_sum.get("regulatory_context"):
            st.warning(f"**Regulatory Context:** {exec_sum.get('regulatory_context')}")

    # Business Objectives
    objectives = a04.get("business_objectives", [])
    if objectives:
        st.markdown("#### Business Objectives — KA4 Task 5.1")
        st.dataframe([{
            "ID": o.get("id"), "Objective": o.get("objective"),
            "Success Metric": o.get("success_metric"),
            "Priority": o.get("priority", "?").upper(),
            "Linked Reqs": ", ".join(o.get("linked_requirement_ids", [])),
        } for o in objectives if isinstance(o, dict)], use_container_width=True, hide_index=True)

    st.divider()

    # Functional Requirements with audience views
    st.markdown("#### Functional Requirements — 3 Audience Views")
    for req in reqs:
        priority = req.get("priority_suggestion", "?")
        color_map = {"must": "🔴", "should": "🟠", "could": "🔵", "wont": "⚪"}
        icon = color_map.get(priority, "⚪")

        with st.expander(f"{icon} {req.get('id', '?')} — {req.get('text', '')[:80]}... [{priority.upper()}]"):
            st.markdown(f"**Full requirement:** {req.get('text', '')}")
            st.markdown(f"**Acceptance criteria:** {req.get('acceptance_criteria', 'N/A')}")
            st.markdown(f"**Source:** {req.get('source_stakeholder', 'N/A')}")
            linked_objs = req.get("linked_objective_ids", [])
            if linked_objs:
                st.markdown(f"**Supports objectives:** {', '.join(linked_objs)}")

            reg_flags = req.get("ls_regulatory_flags", [])
            if reg_flags:
                st.error("**Regulatory:** " + ", ".join(reg_flags))
            amb_flags = req.get("ambiguity_flags", [])
            if amb_flags:
                st.warning("**Ambiguity detected:** " + ", ".join(amb_flags))

            v1, v2, v3 = st.columns(3)
            with v1:
                st.markdown("**🟢 Business Summary**")
                st.markdown(req.get("business_summary", "N/A"))
            with v2:
                st.markdown("**🔵 Functional Spec**")
                st.markdown(req.get("functional_spec", "N/A"))
            with v3:
                st.markdown("**🟣 Technical Notes**")
                st.markdown(req.get("technical_notes", "N/A"))

    # Sub-sections
    col1, col2 = st.columns(2)

    with col1:
        # Assumptions
        assumptions = a04.get("assumptions_log", [])
        if assumptions:
            with st.expander(f"Assumptions Log ({len(assumptions)}) — KA5 Task 6.4"):
                st.dataframe([{
                    "ID": a.get("id"), "Description": a.get("description"),
                    "Risk if Wrong": a.get("risk_if_wrong"), "Validation": a.get("validation_method")
                } for a in assumptions if isinstance(a, dict)], use_container_width=True, hide_index=True)

        # Scope
        scope = a04.get("scope_boundaries", {})
        if scope:
            with st.expander("Scope Boundaries — KA4 Task 5.4"):
                st.markdown("**In Scope:**")
                for item in scope.get("in_scope", []):
                    st.markdown(f"✅ {item}")
                st.markdown("**Out of Scope:**")
                for item in scope.get("out_of_scope", []):
                    if isinstance(item, dict):
                        st.markdown(f"❌ **{item.get('item')}** — {item.get('reason')}")

    with col2:
        # Constraints
        constraints = a04.get("constraint_register", [])
        if constraints:
            with st.expander(f"Constraint Register ({len(constraints)}) — KA5 Task 6.4"):
                st.dataframe([{
                    "ID": c.get("id"), "Type": c.get("type"),
                    "Constraint": c.get("description"), "Impact": c.get("impact")
                } for c in constraints if isinstance(c, dict)], use_container_width=True, hide_index=True)

        # Glossary
        glossary = a04.get("glossary", [])
        if glossary:
            with st.expander(f"Glossary ({len(glossary)}) — T 9.5"):
                st.dataframe([{
                    "Term": g.get("term"), "Definition": g.get("definition"), "Context": g.get("context")
                } for g in glossary if isinstance(g, dict)], use_container_width=True, hide_index=True)

    # Data Dictionary
    data_dict = a04.get("data_dictionary", [])
    if data_dict:
        with st.expander(f"Data Dictionary ({len(data_dict)} entities) — T 9.5"):
            for de in data_dict:
                if not isinstance(de, dict):
                    continue
                hcp = " 🔒 HCP Data" if de.get("hcp_data_flag") else ""
                st.markdown(f"**{de.get('id')}: {de.get('entity_name')}**{hcp} — ALCOA: {de.get('alcoa_classification', 'Standard')}")
                st.markdown(f"{de.get('description', '')}")
                st.markdown(f"Owner: {de.get('data_owner', '')} · Source: {de.get('source_system', '')} · Reqs: {', '.join(de.get('requirement_ids', []))}")
                attrs = de.get("attributes", [])
                if attrs:
                    st.dataframe([{
                        "Attribute": a.get("name"), "Type": a.get("data_type"),
                        "Required": "✓" if a.get("required") else "—",
                        "Validation": a.get("validation_rules"), "Sample": a.get("sample_value")
                    } for a in attrs if isinstance(a, dict)], use_container_width=True, hide_index=True)
                st.divider()

    # Dependencies
    dependencies = a04.get("dependencies", [])
    if dependencies:
        with st.expander(f"Dependencies ({len(dependencies)})"):
            st.dataframe([{
                "ID": d.get("id"), "Type": d.get("type"),
                "Description": d.get("description"),
                "Linked Reqs": ", ".join(d.get("dependent_requirement_ids", [])),
                "Owner": d.get("owner"),
                "Status": d.get("status", "?").upper(),
                "Risk if Unresolved": d.get("risk_if_unresolved"),
            } for d in dependencies if isinstance(d, dict)], use_container_width=True, hide_index=True)

    # Open questions
    openqs = a04.get("open_questions", [])
    if openqs:
        with st.expander(f"Open Questions ({len(openqs)})"):
            for i, q in enumerate(openqs):
                st.markdown(f"**Q{i+1}:** {q}")

    render_correction_widget("A04", "Requirements & BRD")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 2: PROCESS FLOWS
# ══════════════════════════════════════════════════════════════════════════════
with tabs[2]:
    st.subheader("Process Flows — KA5 Task 6.2, T 9.21")

    asis_flow = r.get("A09_ASIS", {}).get("flow", {})
    tobe_flow = r.get("A09_TOBE", {}).get("flow", {})
    gap_summary = r.get("A09_ASIS", {}).get("gap_summary", "")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### AS-IS — Current State")
        st.markdown("*Dashed red nodes = pain points*")
    with col2:
        st.markdown("#### TO-BE — Future State")

    # Render flows vertically (full width) to prevent overlap
    st.markdown("---")
    st.markdown("##### AS-IS — Current State")
    svg_asis = draw_flow_svg(asis_flow, is_asis=True)
    st.markdown(f'<div style="overflow-x:auto;background:#f8f6f0;border-radius:8px;padding:10px;">{svg_asis}</div>', unsafe_allow_html=True)

    st.markdown("")
    st.markdown("##### TO-BE — Future State")
    svg_tobe = draw_flow_svg(tobe_flow, is_asis=False)
    st.markdown(f'<div style="overflow-x:auto;background:#f8f6f0;border-radius:8px;padding:10px;">{svg_tobe}</div>', unsafe_allow_html=True)

    if gap_summary:
        st.info(f"**Gap Summary:** {gap_summary}")

    fc1, fc2 = st.columns(2)
    with fc1:
        render_correction_widget("A09_ASIS", "AS-IS Process Flow")
    with fc2:
        render_correction_widget("A09_TOBE", "TO-BE Process Flow")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 3: NFR REGISTER
# ══════════════════════════════════════════════════════════════════════════════
with tabs[3]:
    st.subheader("NFR Register — T 9.17, ISO 25010")
    a05 = r.get("A05", {})
    nfrs = a05.get("applicable_nfrs", [])

    if nfrs:
        st.dataframe([{
            "Category": n.get("category"), "NFR": n.get("name"),
            "Suggested Value": n.get("suggested_value", n.get("library_default")),
            "GxP Default": "✓" if n.get("is_gxp_default") else "—",
            "Needs Review": "⚠" if n.get("needs_tech_arch_review") else "—",
            "Reasoning": n.get("applicability_reasoning", "")
        } for n in nfrs], use_container_width=True, hide_index=True)

    proj_nfrs = a05.get("project_specific_nfrs", [])
    if proj_nfrs:
        with st.expander(f"Project-Specific NFRs ({len(proj_nfrs)})"):
            st.dataframe([{
                "Category": n.get("category"), "NFR": n.get("name"),
                "Value": n.get("suggested_value"), "Reasoning": n.get("reasoning")
            } for n in proj_nfrs], use_container_width=True, hide_index=True)

    render_correction_widget("A05", "NFR Register")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 4: RISK & PRIORITY
# ══════════════════════════════════════════════════════════════════════════════
with tabs[4]:
    st.subheader("Risk Register & MoSCoW — KA5 6.1, T 9.24")
    a08 = r.get("A08", {})
    scored = a08.get("scored_requirements", [])

    # Risk summary cards
    rc1, rc2, rc3, rc4 = st.columns(4)
    rc1.metric("Critical", risk.get("critical_count", 0))
    rc2.metric("High", risk.get("high_count", 0))
    rc3.metric("Medium", risk.get("medium_count", 0))
    rc4.metric("Low", risk.get("low_count", 0))

    if scored:
        st.dataframe([{
            "Req ID": sc.get("requirement_id"),
            "Requirement": sc.get("requirement_text", "")[:60],
            "MoSCoW": sc.get("moscow_priority", "?").upper(),
            "Reg(2x)": sc.get("risk_scores", {}).get("regulatory_exposure", {}).get("score", "?"),
            "Integ": sc.get("risk_scores", {}).get("integration_complexity", {}).get("score", "?"),
            "Stake": sc.get("risk_scores", {}).get("stakeholder_dependency", {}).get("score", "?"),
            "Ambig": sc.get("risk_scores", {}).get("implementation_ambiguity", {}).get("score", "?"),
            "Total": sc.get("weighted_total", "?"),
            "Tier": sc.get("risk_tier", "?").upper(),
        } for sc in scored], use_container_width=True, hide_index=True)

    # Top risks
    top_risks = risk.get("top_risks", [])
    if top_risks:
        with st.expander("Top Risks"):
            for tr in top_risks:
                st.markdown(f"- {tr}")

    render_correction_widget("A08", "Risk Scoring & MoSCoW")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 5: SOLUTION DESIGN (FSD + Change Impact + Traceability)
# ══════════════════════════════════════════════════════════════════════════════
with tabs[5]:
    st.subheader("Solution Design — KA6 7.1/7.2")
    fsd = r.get("A09_FSD", {})
    fsd_modules = fsd.get("modules", [])
    fsd_usecases = fsd.get("use_cases", [])
    fsd_integrations = fsd.get("integration_points", [])
    fsd_overview = fsd.get("solution_overview", "")

    if fsd_overview:
        st.info(f"**Solution Overview:** {fsd_overview}")

    # FSD Modules
    if fsd_modules:
        st.markdown(f"#### FSD Modules ({len(fsd_modules)})")
        for mod in fsd_modules:
            gxp = " 🔬 GxP" if mod.get("gxp_validation_required") else ""
            with st.expander(f"{mod.get('id')}: {mod.get('name')}{gxp}"):
                st.markdown(f"**Purpose:** {mod.get('purpose')}")
                st.markdown(f"**Traces to:** {', '.join(mod.get('requirement_ids', []))}")
                st.markdown(f"**Processing:** {mod.get('processing_logic', 'N/A')}")
                rules = mod.get("business_rules", [])
                if rules:
                    st.markdown(f"**Business rules:** {'; '.join(rules)}")
                reg = mod.get("ls_regulatory_flags", [])
                if reg:
                    st.error("**Regulatory:** " + ", ".join(reg))

    # Use Cases
    if fsd_usecases:
        with st.expander(f"Use Cases ({len(fsd_usecases)}) — T 9.26"):
            for uc in fsd_usecases:
                st.markdown(f"**{uc.get('id')}: {uc.get('title')}** (Actor: {uc.get('actor')})")
                st.markdown(f"Preconditions: {'; '.join(uc.get('preconditions', []))}")
                for step in uc.get("main_flow", []):
                    st.markdown(f"  {step}")
                st.markdown(f"Postconditions: {'; '.join(uc.get('postconditions', []))}")
                st.divider()

    # Integration Points
    if fsd_integrations:
        with st.expander(f"Integration Points ({len(fsd_integrations)})"):
            st.dataframe([{
                "ID": i.get("id"), "Source": i.get("source_system"),
                "Target": i.get("target_system"), "Data": i.get("data_exchanged"),
                "Method": i.get("method"), "Frequency": i.get("frequency", "")
            } for i in fsd_integrations], use_container_width=True, hide_index=True)

    st.divider()

    # Change Impact
    a10 = r.get("A10", {})
    impact = a10.get("impact_assessment", [])
    amplifiers = a10.get("change_amplifiers", [])

    if impact:
        st.markdown("#### Change Impact Assessment — KA3 Task 4.1")
        if amplifiers:
            st.warning(f"**⚡ {len(amplifiers)} Change Amplifiers** — single changes with disproportionate downstream impact")
            for amp in amplifiers:
                if isinstance(amp, dict):
                    st.markdown(f"- **{amp.get('requirement_id')}** — {amp.get('downstream_count')} downstream — {amp.get('reason')}")

        st.dataframe([{
            "Req ID": ia.get("requirement_id"),
            "Affected": ia.get("total_affected_artefacts", 0),
            "Max Severity": ia.get("max_severity", "?").upper(),
            "Amplifier": "⚡" if ia.get("is_change_amplifier") else "—",
            "Actions": "; ".join(ia.get("recommended_actions", [])[:2]),
        } for ia in impact if isinstance(ia, dict)], use_container_width=True, hide_index=True)

    st.divider()

    # Traceability
    a06 = r.get("A06", {})
    matrix = a06.get("traceability_matrix", [])
    chains = a06.get("dependency_chains", [])
    trace_cov = a06.get("coverage_summary", {})

    if matrix:
        st.markdown("#### Traceability Matrix — KA3 Task 4.2")
        tc1, tc2, tc3 = st.columns(3)
        tc1.metric("Fully Traced", trace_cov.get("fully_traced", 0))
        tc2.metric("Orphans", trace_cov.get("orphans", 0))
        tc3.metric("Chains", trace_cov.get("dependency_chains_identified", 0))

        st.dataframe([{
            "Req ID": t.get("requirement_id"), "Source": t.get("source"),
            "Depends On": ", ".join(t.get("depends_on", [])),
            "Status": t.get("status", "?")
        } for t in matrix], use_container_width=True, hide_index=True)

    if chains:
        with st.expander("Dependency Chains"):
            for c in chains:
                st.markdown(f"**{c.get('chain_name')}:** {' → '.join(c.get('requirements', []))}")
                st.markdown(f"  *{c.get('risk_note', '')}*")

    col_fsd, col_a10, col_a06 = st.columns(3)
    with col_fsd:
        render_correction_widget("A09_FSD", "FSD")
    with col_a10:
        render_correction_widget("A10", "Change Impact")
    with col_a06:
        render_correction_widget("A06", "Traceability")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 6: FRD — Functional Requirements Document (on-demand)
# ══════════════════════════════════════════════════════════════════════════════
with tabs[6]:
    st.subheader("Functional Requirements Document — KA3 Task 4.4")
    st.caption("On-demand: Generated after BA reviews and approves BRD requirements")

    frd = r.get("A15", {})

    if not frd:
        st.info("📋 **FRD not yet generated.** Review BRD requirements first, then generate the FRD.")
        st.markdown("""
        The FRD expands approved BRD requirements into a detailed technical contract with:
        - **14 standardised segments** following professional FRD template
        - **Use cases** with main flows, alternative flows, exception handling
        - **Data dictionary** with field-level specifications
        - **Business rules** with violation handling
        - **Reuses** BRD scope, assumptions, constraints, glossary — enriched with technical context
        """)
        if st.button("📋 Generate FRD", type="primary", key="gen_frd"):
            if not st.session_state.api_key:
                st.error("Enter API key in sidebar first.")
            elif st.session_state.pipeline_result is None:
                st.error("Run the pipeline first to generate BRD requirements.")
            else:
                with st.spinner("Generating FRD (14 segments)... this may take 60-90 seconds"):
                    st.session_state.pipeline_result = run_frd_on_demand(
                        api_key=st.session_state.api_key,
                        pipeline_result=st.session_state.pipeline_result,
                        log_fn=log_msg,
                    )
                st.rerun()
    else:
        # ── Segment 1: Introduction ──
        seg1 = frd.get("segment_1_introduction", {})
        if seg1:
            st.markdown("#### Segment 1: Introduction")
            proj = seg1.get("project_summary", {})
            if proj:
                st.markdown(f"""<div style="background:#f0f4f8;border-left:4px solid #185FA5;padding:14px 18px;border-radius:0 8px 8px 0;margin-bottom:12px;">
                    <div style="font-size:16px;font-weight:600;color:#185FA5;margin-bottom:6px;">{proj.get('project_name', '')}</div>
                    <div style="font-size:13px;margin-bottom:6px;">{proj.get('system_description', '')}</div>
                    <div style="font-size:12px;color:#555;"><b>Vision:</b> {proj.get('primary_vision', '')}</div>
                </div>""", unsafe_allow_html=True)

            bg = seg1.get("background", {})
            if bg:
                with st.expander("Background & Business Problem"):
                    st.markdown(f"**Problem:** {bg.get('business_problem', '')}")
                    st.markdown(f"**Why needed:** {bg.get('why_new_system', '')}")
                    st.markdown(f"**Cost of inaction:** {bg.get('cost_of_not_building', '')}")

            scope = seg1.get("project_scope", {})
            if scope:
                with st.expander("Project Scope"):
                    sc1, sc2 = st.columns(2)
                    with sc1:
                        st.markdown("**✅ In Scope**")
                        for item in scope.get("in_scope", []):
                            st.markdown(f"- {item}")
                    with sc2:
                        st.markdown("**❌ Out of Scope**")
                        for item in scope.get("out_of_scope", []):
                            if isinstance(item, dict):
                                st.markdown(f"- **{item.get('item', '')}** — {item.get('reason', '')} *(→ {item.get('deferred_to', 'TBD')})*")
                            else:
                                st.markdown(f"- {item}")

            sys_purpose = seg1.get("system_purpose", {})
            if sys_purpose and sys_purpose.get("user_roles"):
                with st.expander(f"User Roles ({len(sys_purpose['user_roles'])})"):
                    st.dataframe([{
                        "Role": ur.get("role"), "Description": ur.get("description"),
                        "Key Needs": ur.get("key_needs"),
                    } for ur in sys_purpose["user_roles"]], use_container_width=True, hide_index=True)

        st.divider()

        # ── Segment 2: Functional Objectives ──
        seg2 = frd.get("segment_2_functional_objectives", {})
        if seg2:
            st.markdown("#### Segment 2: Functional Objectives")
            for priority_level, label, color in [
                ("high_priority", "🔴 High Priority (Critical)", "red"),
                ("medium_priority", "🟠 Medium Priority (Important)", "orange"),
                ("low_priority", "🔵 Low Priority (Nice-to-Have)", "blue"),
            ]:
                items = seg2.get(priority_level, [])
                if items:
                    st.markdown(f"**{label}** ({len(items)})")
                    for obj in items:
                        if isinstance(obj, dict):
                            linked = ", ".join(obj.get("linked_requirements", []))
                            st.markdown(f"- **{obj.get('id', '')}:** {obj.get('objective', '')} — *{obj.get('business_value', '')}* → {linked}")

        st.divider()

        # ── Segment 3: NFR Summary ──
        seg3 = frd.get("segment_3_nfr", {})
        if seg3:
            st.markdown("#### Segment 3: Non-Functional Requirements")
            nfr_categories = [
                ("reliability", "Reliability"), ("usability", "Usability"),
                ("performance", "Performance"), ("security", "Security"),
                ("supportability", "Supportability"), ("documentation", "Documentation"),
                ("external_interfaces", "External Interfaces"), ("ls_compliance", "LS Compliance"),
            ]
            for key, label in nfr_categories:
                cat = seg3.get(key, {})
                if cat and cat.get("requirements"):
                    with st.expander(f"{label} — {len(cat['requirements'])} requirements"):
                        st.markdown(f"*{cat.get('description', '')}*")
                        for req in cat["requirements"]:
                            st.markdown(f"- {req}")

        st.divider()

        # ── Segment 4: Context Model ──
        seg4 = frd.get("segment_4_context_model", {})
        if seg4:
            st.markdown("#### Segment 4: Context Model")
            if seg4.get("goal_statement"):
                st.info(f"**Goal:** {seg4['goal_statement']}")
            if seg4.get("context_diagram_description"):
                st.markdown(f"*Context diagram:* {seg4['context_diagram_description']}")
            externals = seg4.get("system_externals", [])
            if externals:
                st.dataframe([{
                    "System": e.get("name"), "Type": e.get("type"),
                    "Frequency": e.get("frequency"), "Format": e.get("data_format"),
                    "Criticality": e.get("criticality", "").upper(),
                } for e in externals], use_container_width=True, hide_index=True)

        st.divider()

        # ── Segment 5: Use Cases ──
        seg5 = frd.get("segment_5_use_cases", [])
        if seg5:
            st.markdown(f"#### Segment 5: Use Cases ({len(seg5)})")
            for uc in seg5:
                if not isinstance(uc, dict):
                    continue
                related = ", ".join(uc.get("related_requirements", []))
                with st.expander(f"{uc.get('id', '?')}: {uc.get('name', '?')} — Actor: {uc.get('actor', '?')}"):
                    st.markdown(f"**Related requirements:** {related}")
                    st.markdown(f"**Preconditions:** {'; '.join(uc.get('preconditions', []))}")
                    st.markdown("**Main Flow:**")
                    for i, step in enumerate(uc.get("main_flow", []), 1):
                        st.markdown(f"  {i}. {step}")
                    alt_flows = uc.get("alternative_flows", [])
                    if alt_flows:
                        st.markdown("**Alternative Flows:**")
                        for af in alt_flows:
                            if isinstance(af, dict):
                                st.markdown(f"  *If {af.get('condition', '')}:* {'; '.join(af.get('steps', []))}")
                    exceptions = uc.get("exception_handling", [])
                    if exceptions:
                        st.markdown(f"**Exception Handling:** {'; '.join(exceptions)}")
                    st.markdown(f"**Postconditions:** {'; '.join(uc.get('postconditions', []))}")

        st.divider()

        # ── Segment 7: Detailed Functional Requirements ──
        seg7 = frd.get("segment_7_detailed_requirements", {})
        if seg7:
            st.markdown("#### Segment 7: Detailed Functional Requirements")

            # Data Dictionary
            dd = seg7.get("data_dictionary", [])
            if dd:
                with st.expander(f"7.1 Data Dictionary ({len(dd)} fields)"):
                    st.dataframe([{
                        "Entity": d.get("entity"), "Field": d.get("field_name"),
                        "Type": d.get("data_type"), "Length": d.get("length"),
                        "Req'd": d.get("required"), "Validation": d.get("validation_rules"),
                        "Example": d.get("example"),
                    } for d in dd if isinstance(d, dict)], use_container_width=True, hide_index=True)

            # Business Processes
            bp = seg7.get("business_processes", [])
            if bp:
                with st.expander(f"7.2.1 Business Processes ({len(bp)})"):
                    for proc in bp:
                        if not isinstance(proc, dict):
                            continue
                        st.markdown(f"**{proc.get('id', '?')}: {proc.get('name', '?')}**")
                        st.markdown(f"*{proc.get('description', '')}*")
                        for i, step in enumerate(proc.get("steps", []), 1):
                            st.markdown(f"  {i}. {step}")
                        related = ", ".join(proc.get("related_requirements", []))
                        if related:
                            st.caption(f"Related: {related}")
                        st.divider()

            # Business Rules
            br = seg7.get("business_rules", [])
            if br:
                with st.expander(f"7.2.2 Business Rules ({len(br)})"):
                    st.dataframe([{
                        "ID": rule.get("id"), "Rule": rule.get("rule_statement"),
                        "When Applies": rule.get("when_applies"),
                        "If Violated": rule.get("if_violated"),
                        "Related Reqs": ", ".join(rule.get("related_requirements", [])),
                    } for rule in br if isinstance(rule, dict)], use_container_width=True, hide_index=True)

        st.divider()

        # ── Segments 9, 10, 11: Assumptions, Constraints, Glossary ──
        seg9 = frd.get("segment_9_assumptions", [])
        seg10 = frd.get("segment_10_constraints", [])
        seg11 = frd.get("segment_11_glossary", [])

        col_a, col_c = st.columns(2)
        with col_a:
            if seg9:
                st.markdown(f"#### Segment 9: Assumptions ({len(seg9)})")
                st.dataframe([{
                    "ID": a.get("id"), "Assumption": a.get("statement"),
                    "Why": a.get("why_necessary"), "If False": a.get("if_false"),
                } for a in seg9 if isinstance(a, dict)], use_container_width=True, hide_index=True)
        with col_c:
            if seg10:
                st.markdown(f"#### Segment 10: Constraints ({len(seg10)})")
                st.dataframe([{
                    "ID": c.get("id"), "Constraint": c.get("description"),
                    "Why": c.get("why_exists"), "Impact": c.get("design_implications"),
                } for c in seg10 if isinstance(c, dict)], use_container_width=True, hide_index=True)

        if seg11:
            with st.expander(f"Segment 11: Glossary ({len(seg11)} terms)"):
                st.dataframe([{
                    "Term": g.get("term"), "Definition": g.get("definition"),
                    "Context": g.get("context"),
                    "Related": ", ".join(g.get("related_terms", [])) if isinstance(g.get("related_terms"), list) else "",
                } for g in seg11 if isinstance(g, dict)], use_container_width=True, hide_index=True)

        # ── Segment 13: Sign-off ──
        seg13 = frd.get("segment_13_signoff", {})
        if seg13:
            st.divider()
            st.markdown("#### Segment 13: Sign-Off")
            sigs = seg13.get("signatories", [])
            if sigs:
                st.dataframe([{
                    "Role": s.get("role"), "Name": s.get("name", "TBD"),
                    "Status": s.get("status", "pending").upper(),
                } for s in sigs if isinstance(s, dict)], use_container_width=True, hide_index=True)
            if seg13.get("attestation"):
                st.caption(f"*{seg13['attestation']}*")

        st.divider()

        # ── FRD Summary Metrics ──
        frd_uc = len(seg5) if isinstance(seg5, list) else 0
        frd_dd = len(seg7.get("data_dictionary", [])) if seg7 else 0
        frd_br = len(seg7.get("business_rules", [])) if seg7 else 0
        frd_bp = len(seg7.get("business_processes", [])) if seg7 else 0

        mc1, mc2, mc3, mc4 = st.columns(4)
        mc1.metric("Use Cases", frd_uc)
        mc2.metric("Data Fields", frd_dd)
        mc3.metric("Business Rules", frd_br)
        mc4.metric("Processes", frd_bp)

        # ── Regenerate button ──
        if st.button("🔄 Regenerate FRD", key="regen_frd"):
            with st.spinner("Regenerating FRD..."):
                st.session_state.pipeline_result = run_frd_on_demand(
                    api_key=st.session_state.api_key,
                    pipeline_result=st.session_state.pipeline_result,
                    log_fn=log_msg,
                )
            st.rerun()

        render_correction_widget("A15", "FRD")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 7: AGILE/SPRINT
# ══════════════════════════════════════════════════════════════════════════════
with tabs[7]:
    st.subheader("Agile/Sprint — T 9.33, T 9.1")
    a14 = r.get("A14", {})
    user_stories = a14.get("user_stories", [])
    acc_criteria = a14.get("acceptance_criteria", [])
    backlog = a14.get("product_backlog", {})
    release_plan = a14.get("release_plan", {})
    dor = a14.get("definition_of_ready", [])
    dod = a14.get("definition_of_done", [])

    # AC lookup
    ac_by_story = {}
    for ac in acc_criteria:
        if isinstance(ac, dict):
            ac_by_story.setdefault(ac.get("story_id", ""), []).append(ac)

    # User Stories
    if user_stories:
        st.markdown(f"#### User Stories ({len(user_stories)})")
        for us in user_stories:
            if not isinstance(us, dict):
                continue
            m = us.get("moscow", "?")
            icon = {"must": "🔴", "should": "🟠", "could": "🔵", "wont": "⚪"}.get(m, "⚪")
            reg = " 🔬" if us.get("is_regulatory") else ""
            sp = us.get("story_points", "?")

            with st.expander(f"{icon} {us.get('id')} [{sp}pts] — {us.get('story', '')[:70]}...{reg}"):
                st.markdown(f"*{us.get('story', '')}*")
                st.markdown(f"**Actor:** {us.get('actor')} · **Reqs:** {', '.join(us.get('requirement_ids', []))} · **Sprint:** {us.get('sprint_suggestion', '?')}")

                story_acs = ac_by_story.get(us.get("id", ""), [])
                if story_acs:
                    st.markdown(f"**Acceptance Criteria ({len(story_acs)}):**")
                    for ac in story_acs:
                        reg_tag = " 🔬" if ac.get("is_regulatory") else ""
                        st.markdown(f"""
                        **{ac.get('id', '')}**{reg_tag}
                        - **GIVEN** {ac.get('given', '')}
                        - **WHEN** {ac.get('when', '')}
                        - **THEN** {ac.get('then', '')}
                        """)

    # Sprint Breakdown
    sprint_bd = backlog.get("sprint_breakdown", [])
    if sprint_bd:
        with st.expander(f"Product Backlog — Sprint Breakdown ({backlog.get('total_story_points', 0)} total pts)"):
            st.dataframe([{
                "Sprint": sb.get("sprint"), "Stories": ", ".join(sb.get("story_ids", [])),
                "Points": sb.get("story_points", 0)
            } for sb in sprint_bd if isinstance(sb, dict)], use_container_width=True, hide_index=True)

    # Release Plan
    releases = release_plan.get("releases", [])
    if releases:
        with st.expander(f"Release Plan (velocity: {release_plan.get('velocity_assumption', 'N/A')})"):
            for rel in releases:
                if isinstance(rel, dict):
                    st.markdown(f"**{rel.get('release')}** ({rel.get('moscow_tier', '?').upper()}) — {rel.get('total_story_points', 0)} pts, ~{rel.get('estimated_sprints', 0)} sprints")
                    st.markdown(f"Stories: {', '.join(rel.get('story_ids', []))}")
                    risks = rel.get("key_risks", [])
                    if risks:
                        st.warning(f"Risks: {'; '.join(risks)}")
                    st.divider()

    # DoR + DoD
    if dor or dod:
        dc1, dc2 = st.columns(2)
        with dc1:
            with st.expander("Definition of Ready (DoR) — KA5 6.5"):
                for item in dor:
                    if isinstance(item, str):
                        st.checkbox(item, value=False, key=f"dor_{item[:20]}", disabled=True)
        with dc2:
            with st.expander("Definition of Done (DoD) — T 9.1"):
                for item in dod:
                    if isinstance(item, str):
                        st.checkbox(item, value=False, key=f"dod_{item[:20]}", disabled=True)

    render_correction_widget("A14", "User Stories & Backlog")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 8: TESTING
# ══════════════════════════════════════════════════════════════════════════════
with tabs[8]:
    st.subheader("Functional Test Cases — KA6 7.5, P5")
    a11 = r.get("A11", {})
    test_cases = a11.get("test_cases", [])
    gxp_templates = a11.get("gxp_test_templates", [])
    test_plan = a11.get("test_plan", {})
    req_coverage = a11.get("requirements_coverage", [])
    test_cov = a11.get("coverage_summary", {})

    # Test plan
    if test_plan:
        with st.expander("Test Plan — UAT Approach"):
            st.markdown(f"**Approach:** {test_plan.get('test_approach', '')}")
            entry = test_plan.get("entry_criteria", [])
            if entry:
                st.markdown(f"**Entry criteria:** {'; '.join(entry)}")
            exit_c = test_plan.get("exit_criteria", [])
            if exit_c:
                st.markdown(f"**Exit criteria:** {'; '.join(exit_c)}")
            oos = test_plan.get("out_of_scope", [])
            if oos:
                st.warning(f"**Out of BA scope:** {'; '.join(oos)}")

    # Coverage metrics
    cv1, cv2, cv3 = st.columns(3)
    cv1.metric("Total Test Cases", test_cov.get("total_test_cases", len(test_cases)))
    cv2.metric("GxP Templates", len(gxp_templates))
    cv3.metric("Requirements Covered", f"{test_cov.get('fully_covered', 0)}/{test_cov.get('total_requirements', 0)}")

    # Test Cases
    if test_cases:
        for tc in test_cases:
            if not isinstance(tc, dict):
                continue
            priority = tc.get("priority", "medium")
            icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(priority, "⚪")
            reg = " 🔬" if tc.get("is_regulatory") else ""

            with st.expander(f"{icon} {tc.get('id')}: {tc.get('title', '')}{reg} [{priority.upper()}]"):
                st.markdown(f"**Reqs:** {', '.join(tc.get('requirement_ids', []))} · **Story:** {tc.get('user_story_id', '—')} · **From AC:** {tc.get('derived_from_ac', '—')}")
                preconds = tc.get("preconditions", [])
                if preconds:
                    st.markdown(f"**Preconditions:** {'; '.join(preconds)}")

                steps = tc.get("test_steps", [])
                if steps:
                    st.dataframe([{
                        "#": step.get("step_number"),
                        "Action": step.get("action"),
                        "Expected Result": step.get("expected_result"),
                        "Test Data": step.get("test_data", "—"),
                        "P/F": "☐"
                    } for step in steps if isinstance(step, dict)], use_container_width=True, hide_index=True)

                st.markdown(f"**Pass criteria:** {tc.get('pass_criteria', '')}")

    # GxP Templates
    if gxp_templates:
        st.divider()
        st.markdown("#### GxP Validation Test Templates")
        st.warning("⚠ BA-generated drafts for validation team review. Not final validation protocols.")
        for gxp in gxp_templates:
            if isinstance(gxp, dict):
                st.markdown(f"**{gxp.get('id')}: {gxp.get('title')}** [{gxp.get('gxp_type')}]")
                st.markdown(f"Objective: {gxp.get('test_objective', '')} · Expected: {gxp.get('expected_outcome', '')}")
                st.markdown(f"Reqs: {', '.join(gxp.get('requirement_ids', []))} · Sign-off: {', '.join(gxp.get('sign_off_roles', []))}")
                st.divider()

    # Coverage Matrix
    if req_coverage:
        with st.expander("Requirements Test Coverage Matrix"):
            st.dataframe([{
                "Req ID": rc.get("requirement_id"),
                "Test Cases": ", ".join(rc.get("test_case_ids", [])) or "—",
                "GxP Templates": ", ".join(rc.get("gxp_template_ids", [])) or "—",
                "Coverage": rc.get("coverage_status", "?").upper()
            } for rc in req_coverage if isinstance(rc, dict)], use_container_width=True, hide_index=True)

    render_correction_widget("A11", "Test Scripts")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 9: HANDOVER
# ══════════════════════════════════════════════════════════════════════════════
with tabs[9]:
    st.subheader("Handover Documentation — KA6 7.3/7.4/7.6, P7")
    a13 = r.get("A13", {})

    # Training Manual
    training = a13.get("training_manual", {})
    if training:
        with st.expander("📖 Training Manual — KA6 7.3.4", expanded=True):
            st.markdown(f"**System Overview:** {training.get('system_overview', '')}")
            roles = training.get("user_roles", [])
            if roles:
                st.markdown("**User Roles:**")
                for role in roles:
                    if isinstance(role, dict):
                        st.markdown(f"- **{role.get('role')}**: {role.get('description')} ({', '.join(role.get('key_tasks', []))})")
            guides = training.get("process_guides", [])
            if guides:
                st.markdown("**Process Guides:**")
                for g in guides:
                    if isinstance(g, dict):
                        st.markdown(f"**{g.get('process_name')}:** {' → '.join(g.get('steps', []))}")
            faq = training.get("faq", [])
            if faq:
                st.markdown("**FAQ:**")
                for f in faq:
                    if isinstance(f, dict):
                        st.markdown(f"**Q:** {f.get('question')} **A:** {f.get('answer')}")

    # L1 Support Guide
    l1 = a13.get("l1_support_guide", {})
    if l1:
        issues = l1.get("common_issues", [])
        with st.expander(f"🛟 L1 Support Guide ({len(issues)} issues) — KA6 7.4"):
            if issues:
                st.dataframe([{
                    "Issue": iss.get("issue"), "Resolution": iss.get("resolution"),
                    "Severity": iss.get("severity", "?").upper()
                } for iss in issues if isinstance(iss, dict)], use_container_width=True, hide_index=True)
            esc = l1.get("escalation_matrix", [])
            if esc:
                st.markdown("**Escalation Matrix:**")
                for e in esc:
                    if isinstance(e, dict):
                        st.markdown(f"- **When:** {e.get('condition')} → **To:** {e.get('escalate_to')} (SLA: {e.get('sla')})")

    # Onboarding
    onb = a13.get("onboarding_doc", {})
    if onb:
        with st.expander("👋 Onboarding Document — KA6 7.3"):
            st.markdown(f"**Project Context:** {onb.get('project_context', '')}")
            st.markdown(f"**System Landscape:** {onb.get('system_landscape', '')}")
            decisions = onb.get("key_decisions", [])
            if decisions:
                st.markdown("**Key Decisions:**")
                for d in decisions:
                    if isinstance(d, dict):
                        st.markdown(f"- **{d.get('decision')}** — {d.get('rationale')}")
            lims = onb.get("known_limitations", [])
            if lims:
                st.markdown("**Known Limitations:**")
                for l in lims:
                    st.markdown(f"- ❌ {l}")

    # Business Readiness Runbook
    runbook = a13.get("business_readiness_runbook", {})
    if runbook:
        with st.expander("🚀 Business Readiness Runbook — KA6 7.4"):
            pre = runbook.get("pre_golive", [])
            if pre:
                st.markdown("**Pre-Go-Live Checks:**")
                for p in pre:
                    if isinstance(p, dict):
                        st.checkbox(f"{p.get('check')} ({p.get('owner', '')})", value=False,
                                   key=f"pre_{str(p.get('check',''))[:20]}", disabled=True)
            golive = runbook.get("golive_day", [])
            if golive:
                st.markdown("**Go-Live Day:**")
                for g in golive:
                    if isinstance(g, dict):
                        st.markdown(f"- **{g.get('time', '')}** — {g.get('activity')} ({g.get('owner', '')})")
            rollback = runbook.get("rollback_criteria", [])
            if rollback:
                st.error("**Rollback Criteria:** " + "; ".join(rollback))

    # Hypercare Plan
    hyper = a13.get("hypercare_plan", {})
    if hyper:
        with st.expander("🩺 Hypercare Plan — KA6 7.6"):
            st.markdown(f"**Duration:** {hyper.get('duration', '')}")
            kpis = hyper.get("monitoring_kpis", [])
            if kpis:
                st.dataframe([{
                    "KPI": k.get("kpi"), "Target": k.get("target"),
                    "Measurement": k.get("measurement_method")
                } for k in kpis if isinstance(k, dict)], use_container_width=True, hide_index=True)
            success = hyper.get("success_criteria", [])
            if success:
                st.markdown("**Exit Criteria:**")
                for sc in success:
                    st.markdown(f"- ✅ {sc}")

    render_correction_widget("A13", "Handover Documentation")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 10: OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════
with tabs[10]:
    st.subheader("Project Overview & Event Log")

    # Pipeline summary
    st.markdown("#### Pipeline Summary")
    ov1, ov2, ov3, ov4 = st.columns(4)
    ov1.metric("FSD Modules", s.get("fsd_modules", 0))
    ov2.metric("Use Cases", s.get("fsd_usecases", 0))
    ov3.metric("Story Points", s.get("total_story_points", 0))
    ov4.metric("GxP Templates", s.get("gxp_templates", 0))

    # Change impact summary
    ci = s.get("change_impact", {})
    if ci:
        st.markdown("#### Change Impact Summary")
        ci1, ci2, ci3, ci4 = st.columns(4)
        ci1.metric("Critical Impact", ci.get("critical_impact_count", 0))
        ci2.metric("High Impact", ci.get("high_impact_count", 0))
        ci3.metric("Amplifiers", ci.get("change_amplifier_count", 0))
        ci4.metric("Regulatory Impact", ci.get("regulatory_impact_count", 0))

    # Test coverage
    tc = s.get("test_coverage", {})
    if tc:
        st.markdown("#### Test Coverage")
        tc1, tc2, tc3 = st.columns(3)
        tc1.metric("Covered", tc.get("fully_covered", 0))
        tc2.metric("Partial", tc.get("partially_covered", 0))
        tc3.metric("Uncovered", tc.get("uncovered", 0))

    # Event log
    event_store = pr.get("event_store")
    if event_store:
        events = event_store.get_project_events_sync(pr.get("project_id"), limit=30)
        if events:
            with st.expander(f"Change Ledger ({len(events)} events)"):
                st.dataframe([{
                    "Time": e.get("timestamp", "")[:19],
                    "Actor": e.get("actor_id"),
                    "Action": e.get("action"),
                    "Artefact": e.get("artefact_type"),
                    "Context": (e.get("context") or "")[:80],
                } for e in events], use_container_width=True, hide_index=True)

    # Raw JSON export
    with st.expander("Raw JSON Output (for debugging)"):
        st.json({"summary": s})
