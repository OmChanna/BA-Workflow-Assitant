"""
BA Workflow Assistant — Knowledge Management Admin
Manage structure examples (per agent) and domain knowledge (per subdomain).
Two-panel layout with upload, view, delete functionality.
"""
import streamlit as st
from knowledge_store import (
    COLLECTION_STRUCTURE, COLLECTION_DOMAIN,
    list_documents, delete_document, get_collection_stats,
    check_qdrant_health, ensure_collections,
)
from ingestion import (
    ingest_structure_example, ingest_domain_knowledge,
    AGENT_DISPLAY_MAP, DOMAIN_TREE,
)


# ── Page Config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Knowledge Management — BA Workflow Assistant",
    page_icon="🧠",
    layout="wide",
)

st.markdown("""
<style>
    .block-container { padding-top: 1rem; }
    div[data-testid="stMetric"] { background: #f8f9fa; padding: 10px; border-radius: 8px; }
    .doc-card { background: #f8f9fa; padding: 10px; border-radius: 6px; margin-bottom: 8px;
                border-left: 3px solid #5DCAA5; font-size: 13px; }
    .doc-card-domain { border-left-color: #85B7EB; }
</style>
""", unsafe_allow_html=True)


# ── Session State ─────────────────────────────────────────────────────────────

if "admin_api_key" not in st.session_state:
    st.session_state.admin_api_key = st.session_state.get("api_key", "")


# ── Header ────────────────────────────────────────────────────────────────────

st.title("🧠 Knowledge Management")
st.caption("Upload reference documents to improve agent output quality. "
           "Structure examples teach output style; domain knowledge provides context.")

# API key (needed for embeddings)
api_key = st.text_input(
    "OpenAI API Key (required for embedding)",
    value=st.session_state.admin_api_key,
    type="password",
    key="admin_api_key_input",
)
if api_key:
    st.session_state.admin_api_key = api_key


# ── Health Check ──────────────────────────────────────────────────────────────

health = check_qdrant_health()
if not health["healthy"]:
    st.error(f"⚠️ Qdrant not reachable: {health.get('error', 'Unknown error')}")
    st.info("Start Qdrant with: `docker run -p 6333:6333 -v ./qdrant_data:/qdrant/storage qdrant/qdrant`")
    st.stop()

# Ensure collections exist
try:
    ensure_collections()
except Exception as e:
    st.error(f"Failed to initialize collections: {e}")
    st.stop()

# Stats row
col_s1, col_s2, col_s3 = st.columns(3)
struct_stats = get_collection_stats(COLLECTION_STRUCTURE)
domain_stats = get_collection_stats(COLLECTION_DOMAIN)
col_s1.metric("Structure Examples", f"{struct_stats['total_points']} chunks")
col_s2.metric("Domain Knowledge", f"{domain_stats['total_points']} chunks")
col_s3.metric("Qdrant Status", "🟢 Connected" if health["healthy"] else "🔴 Down")

st.divider()


# ══════════════════════════════════════════════════════════════════════════════
#  TWO-PANEL LAYOUT
# ══════════════════════════════════════════════════════════════════════════════

left_panel, right_panel = st.columns(2)


# ── LEFT PANEL: Structure / Template Examples ─────────────────────────────────

with left_panel:
    st.subheader("📐 Structure / Template Examples")
    st.caption("Upload past good BRDs, FRDs, FSD docs, etc. to teach agents output style.")

    # Agent selector — grouped by BABOK phase/tab
    tabs_agents = {}
    for agent_id, info in AGENT_DISPLAY_MAP.items():
        tab = info["tab"]
        if tab not in tabs_agents:
            tabs_agents[tab] = []
        tabs_agents[tab].append((agent_id, info["name"]))

    # Expandable tree by tab
    for tab_name, agents in tabs_agents.items():
        with st.expander(f"📁 {tab_name}", expanded=False):
            for agent_id, agent_name in agents:
                st.markdown(f"**{agent_id} — {agent_name}**")

                # List existing docs for this agent
                docs = list_documents(COLLECTION_STRUCTURE, filters={"agent_id": agent_id})
                if docs:
                    for doc in docs:
                        c1, c2 = st.columns([4, 1])
                        with c1:
                            upload_date = doc.get("upload_date", "")[:10]
                            st.markdown(
                                f'<div class="doc-card">'
                                f'📄 <b>{doc["filename"]}</b> · {doc["chunk_count"]} chunks · {upload_date}'
                                f'</div>',
                                unsafe_allow_html=True,
                            )
                        with c2:
                            if st.button("🗑️", key=f"del_struct_{doc['doc_id']}",
                                         help=f"Delete {doc['filename']}"):
                                deleted = delete_document(COLLECTION_STRUCTURE, doc["doc_id"])
                                st.success(f"Deleted {deleted} chunks")
                                st.rerun()
                else:
                    st.caption("No examples uploaded yet.")

                # Upload widget
                uploaded = st.file_uploader(
                    f"Upload example for {agent_id}",
                    type=["pdf", "docx", "txt", "md", "xlsx", "csv", "json"],
                    key=f"upload_struct_{agent_id}",
                    label_visibility="collapsed",
                )
                if uploaded and api_key:
                    with st.spinner(f"Ingesting {uploaded.name}..."):
                        result = ingest_structure_example(
                            api_key=api_key,
                            uploaded_file=uploaded,
                            agent_id=agent_id,
                        )
                        if result["success"]:
                            st.success(f"✅ {result['filename']}: {result['chunk_count']} chunks stored")
                            st.rerun()
                        else:
                            st.error(f"❌ {result['error']}")
                elif uploaded and not api_key:
                    st.warning("Enter API key above to enable ingestion.")

                st.markdown("---")


# ── RIGHT PANEL: Domain Knowledge ─────────────────────────────────────────────

with right_panel:
    st.subheader("📚 Domain Knowledge")
    st.caption("Upload regulatory docs, SOPs, style guides, industry standards.")

    for domain_key, domain_info in DOMAIN_TREE.items():
        with st.expander(f"🏢 {domain_info['name']}", expanded=(domain_key == "life_sciences")):
            for sub_key, sub_name in domain_info["subdomains"].items():
                st.markdown(f"**{sub_name}**")

                # List existing docs
                docs = list_documents(COLLECTION_DOMAIN, filters={
                    "domain": domain_key, "subdomain": sub_key
                })
                if docs:
                    for doc in docs:
                        c1, c2 = st.columns([4, 1])
                        with c1:
                            upload_date = doc.get("upload_date", "")[:10]
                            st.markdown(
                                f'<div class="doc-card doc-card-domain">'
                                f'📄 <b>{doc["filename"]}</b> · {doc["chunk_count"]} chunks · {upload_date}'
                                f'</div>',
                                unsafe_allow_html=True,
                            )
                        with c2:
                            if st.button("🗑️", key=f"del_domain_{doc['doc_id']}",
                                         help=f"Delete {doc['filename']}"):
                                deleted = delete_document(COLLECTION_DOMAIN, doc["doc_id"])
                                st.success(f"Deleted {deleted} chunks")
                                st.rerun()
                else:
                    st.caption("No documents uploaded yet.")

                # Upload widget
                uploaded = st.file_uploader(
                    f"Upload for {sub_name}",
                    type=["pdf", "docx", "txt", "md", "xlsx", "csv", "json"],
                    key=f"upload_domain_{domain_key}_{sub_key}",
                    label_visibility="collapsed",
                )
                if uploaded and api_key:
                    with st.spinner(f"Ingesting {uploaded.name}..."):
                        result = ingest_domain_knowledge(
                            api_key=api_key,
                            uploaded_file=uploaded,
                            domain=domain_key,
                            subdomain=sub_key,
                        )
                        if result["success"]:
                            st.success(f"✅ {result['filename']}: {result['chunk_count']} chunks stored")
                            st.rerun()
                        else:
                            st.error(f"❌ {result['error']}")
                elif uploaded and not api_key:
                    st.warning("Enter API key above to enable ingestion.")

                st.markdown("---")


# ── Footer Info ───────────────────────────────────────────────────────────────

st.divider()
with st.expander("ℹ️ How it works"):
    st.markdown("""
**Structure Examples** teach agents HOW to format and structure their outputs:
- Upload a past good BRD under A04 → system learns your BRD style
- Upload a past FRD under A15 → system learns your FRD conventions
- At runtime, the agent retrieves matching examples and uses them as reference

**Domain Knowledge** teaches agents WHAT domain context to apply:
- Upload regulatory SOPs → agents reference compliance requirements
- Upload style guides → agents follow your naming/formatting standards
- Orchestrator identifies applicable subdomains from the brief and retrieves matching knowledge

**RAG Pipeline:** Upload → Parse → Chunk (500 tokens, 50 overlap) → Embed (text-embedding-3-small) → Store (Qdrant)

**At runtime:** Agent query → Semantic search + metadata filter → Top 5 chunks → Injected into prompt
    """)
