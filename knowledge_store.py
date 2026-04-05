# ══════════════════════════════════════════════════════════════════════════════
#  KNOWLEDGE STORE — Qdrant Wrapper for RAG
#  Supports both local Docker Qdrant and Qdrant Cloud (free tier)
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations
import os
import json
import hashlib
from datetime import datetime
from typing import Optional
from openai import OpenAI

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct,
    Filter, FieldCondition, MatchValue,
    models,
)


# ── Config ────────────────────────────────────────────────────────────────────

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536

COLLECTION_STRUCTURE = "structure_examples"
COLLECTION_DOMAIN = "domain_knowledge"

CHUNK_SIZE_TOKENS = 500
CHUNK_OVERLAP_TOKENS = 50
CHARS_PER_TOKEN = 4


def _read_secret(key, default=""):
    """Read a secret value. Tries every known method."""
    val = None
    
    # Method 1: Streamlit secrets (primary for Streamlit Cloud)
    try:
        import streamlit as st
        if hasattr(st, "secrets"):
            try:
                val = st.secrets.get(key, None)
            except Exception:
                pass
            if val is None:
                try:
                    val = st.secrets.get(key.lower(), None)
                except Exception:
                    pass
    except Exception:
        pass
    
    # Method 2: Environment variables
    if val is None:
        val = os.environ.get(key, None)
    
    # Method 3: Default
    if val is None:
        val = default
    
    # Clean: strip whitespace and newlines (TOML editor can inject these)
    if isinstance(val, str):
        val = val.strip().replace("\n", "").replace("\r", "")
    
    return val


def _get_qdrant_config() -> dict:
    """Get Qdrant connection config. Called fresh every time."""
    host = _read_secret("QDRANT_HOST", "localhost")
    port = _read_secret("QDRANT_PORT", "6333")
    api_key = _read_secret("QDRANT_API_KEY", "")
    
    try:
        port = int(port)
    except (ValueError, TypeError):
        port = 6333
    
    return {
        "host": host,
        "port": port,
        "api_key": api_key,
    }


# ── Embedding Client ──────────────────────────────────────────────────────────

def get_embedding(api_key: str, text: str) -> list[float]:
    client = OpenAI(api_key=api_key)
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=text)
    return response.data[0].embedding


def get_embeddings_batch(api_key: str, texts: list[str]) -> list[list[float]]:
    client = OpenAI(api_key=api_key)
    all_embeddings = []
    batch_size = 100
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        response = client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
        all_embeddings.extend([d.embedding for d in response.data])
    return all_embeddings


# ── Qdrant Client Factory ────────────────────────────────────────────────────

def get_qdrant_client() -> QdrantClient:
    """Create Qdrant client. Reads config fresh every call."""
    cfg = _get_qdrant_config()
    
    if cfg["api_key"]:
        # Qdrant Cloud
        host = cfg["host"]
        # Ensure https:// prefix
        if not host.startswith("http"):
            host = f"https://{host}"
        host = host.rstrip("/")
        return QdrantClient(
            url=host,
            api_key=cfg["api_key"],
            timeout=30,
            port=None,  # Qdrant Cloud uses URL, not host+port
        )
    else:
        # Local Docker
        return QdrantClient(host=cfg["host"], port=cfg["port"], timeout=30)


def ensure_collections():
    client = get_qdrant_client()
    existing = [c.name for c in client.get_collections().collections]

    for coll_name in [COLLECTION_STRUCTURE, COLLECTION_DOMAIN]:
        if coll_name not in existing:
            client.create_collection(
                collection_name=coll_name,
                vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
            )
            for field in ["agent_id", "domain", "subdomain", "doc_id"]:
                client.create_payload_index(
                    collection_name=coll_name,
                    field_name=field,
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )
    return True


# ── Chunking ──────────────────────────────────────────────────────────────────

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE_TOKENS,
               overlap: int = CHUNK_OVERLAP_TOKENS) -> list[dict]:
    char_chunk = chunk_size * CHARS_PER_TOKEN
    char_overlap = overlap * CHARS_PER_TOKEN
    chunks = []
    start = 0
    idx = 0

    while start < len(text):
        end = start + char_chunk
        if end < len(text):
            search_start = max(start, end - int(char_chunk * 0.2))
            last_period = text.rfind('. ', search_start, end)
            last_newline = text.rfind('\n', search_start, end)
            break_point = max(last_period, last_newline)
            if break_point > search_start:
                end = break_point + 1

        chunk_text_str = text[start:end].strip()
        if chunk_text_str:
            chunks.append({"text": chunk_text_str, "index": idx,
                           "char_start": start, "char_end": end})
            idx += 1

        start = end - char_overlap
        if start >= len(text) or end >= len(text):
            break

    return chunks


# ── Storage Operations ────────────────────────────────────────────────────────

def generate_doc_id(filename: str, collection: str, agent_id: str = "",
                    domain: str = "", subdomain: str = "") -> str:
    key = f"{collection}:{agent_id}:{domain}:{subdomain}:{filename}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def store_chunks(api_key: str, collection: str, chunks: list[dict], metadata: dict) -> int:
    if not chunks:
        return 0
    texts = [c["text"] for c in chunks]
    embeddings = get_embeddings_batch(api_key, texts)
    client = get_qdrant_client()
    points = []
    doc_id = metadata.get("doc_id", "unknown")

    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        point_id_str = f"{doc_id}_{i}"
        point_id_hash = int(hashlib.sha256(point_id_str.encode()).hexdigest()[:15], 16)
        payload = {
            **metadata,
            "chunk_text": chunk["text"], "chunk_index": chunk["index"],
            "char_start": chunk["char_start"], "char_end": chunk["char_end"],
            "stored_at": datetime.utcnow().isoformat(),
        }
        points.append(PointStruct(id=point_id_hash, vector=embedding, payload=payload))

    for i in range(0, len(points), 100):
        client.upsert(collection_name=collection, points=points[i:i + 100])
    return len(points)


def retrieve_chunks(api_key: str, collection: str, query_text: str,
                    top_k: int = 5, filters: Optional[dict] = None,
                    score_threshold: float = 0.3) -> list[dict]:
    query_embedding = get_embedding(api_key, query_text)
    qdrant_filter = None
    if filters:
        conditions = []
        for field, value in filters.items():
            if isinstance(value, list):
                for v in value:
                    conditions.append(FieldCondition(key=field, match=MatchValue(value=v)))
            else:
                conditions.append(FieldCondition(key=field, match=MatchValue(value=value)))
        if conditions:
            qdrant_filter = Filter(must=conditions)

    client = get_qdrant_client()
    results = client.search(
        collection_name=collection, query_vector=query_embedding,
        limit=top_k, query_filter=qdrant_filter, score_threshold=score_threshold,
    )
    return [{"text": hit.payload.get("chunk_text", ""), "score": hit.score,
             "metadata": {k: v for k, v in hit.payload.items() if k != "chunk_text"}}
            for hit in results]


def delete_document(collection: str, doc_id: str) -> int:
    client = get_qdrant_client()
    count_before = client.count(
        collection_name=collection,
        count_filter=Filter(must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]),
    ).count
    client.delete(
        collection_name=collection,
        points_selector=models.FilterSelector(
            filter=Filter(must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]),
        ),
    )
    return count_before


def list_documents(collection: str, filters: Optional[dict] = None) -> list[dict]:
    client = get_qdrant_client()
    qdrant_filter = None
    if filters:
        conditions = [FieldCondition(key=f, match=MatchValue(value=v)) for f, v in filters.items()]
        if conditions:
            qdrant_filter = Filter(must=conditions)

    docs = {}
    offset = None
    while True:
        results, next_offset = client.scroll(
            collection_name=collection, scroll_filter=qdrant_filter,
            limit=100, offset=offset, with_payload=True, with_vectors=False,
        )
        for point in results:
            doc_id = point.payload.get("doc_id", "unknown")
            if doc_id not in docs:
                docs[doc_id] = {
                    "doc_id": doc_id, "filename": point.payload.get("filename", "unknown"),
                    "agent_id": point.payload.get("agent_id", ""),
                    "domain": point.payload.get("domain", ""),
                    "subdomain": point.payload.get("subdomain", ""),
                    "upload_date": point.payload.get("stored_at", ""),
                    "chunk_count": 0,
                }
            docs[doc_id]["chunk_count"] += 1
        if next_offset is None or len(results) < 100:
            break
        offset = next_offset
    return sorted(docs.values(), key=lambda d: d.get("upload_date", ""), reverse=True)


def get_collection_stats(collection: str) -> dict:
    try:
        client = get_qdrant_client()
        info = client.get_collection(collection_name=collection)
        return {"total_points": info.points_count,
                "status": info.status.value if hasattr(info.status, 'value') else str(info.status)}
    except Exception as e:
        return {"total_points": 0, "status": f"error: {str(e)}"}


# ── Runtime Retrieval Helpers ─────────────────────────────────────────────────

def retrieve_structure_examples(api_key: str, agent_id: str, query_text: str,
                                domain: str = "", top_k: int = 5) -> list[dict]:
    filters = {"agent_id": agent_id}
    if domain:
        filters["domain"] = domain
    return retrieve_chunks(api_key=api_key, collection=COLLECTION_STRUCTURE,
                           query_text=query_text, top_k=top_k, filters=filters)


def retrieve_domain_knowledge(api_key: str, subdomains: list[str],
                              query_text: str, top_k: int = 5) -> list[dict]:
    all_results = []
    per_k = max(2, top_k // len(subdomains)) if subdomains else top_k
    for subdomain in subdomains:
        results = retrieve_chunks(api_key=api_key, collection=COLLECTION_DOMAIN,
                                  query_text=query_text, top_k=per_k,
                                  filters={"subdomain": subdomain})
        all_results.extend(results)
    seen = set()
    unique = []
    for r in sorted(all_results, key=lambda x: x["score"], reverse=True):
        h = hashlib.md5(r["text"].encode()).hexdigest()
        if h not in seen:
            seen.add(h)
            unique.append(r)
    return unique[:top_k]


def format_rag_context(chunks: list[dict], section_label: str) -> str:
    if not chunks:
        return ""
    lines = [f"\n{section_label}:"]
    for i, chunk in enumerate(chunks, 1):
        source = chunk.get("metadata", {}).get("filename", "unknown")
        score = chunk.get("score", 0)
        lines.append(f"--- Reference {i} (source: {source}, relevance: {score:.2f}) ---")
        lines.append(chunk["text"])
        lines.append("")
    return "\n".join(lines)


# ── Health Check ──────────────────────────────────────────────────────────────

def check_qdrant_health() -> dict:
    """Check if Qdrant is reachable. Reads config fresh every call."""
    cfg = _get_qdrant_config()
    try:
        client = get_qdrant_client()
        collections = [c.name for c in client.get_collections().collections]
        return {
            "healthy": True,
            "collections": collections,
            "structure_exists": COLLECTION_STRUCTURE in collections,
            "domain_exists": COLLECTION_DOMAIN in collections,
            "config": {"host": cfg["host"], "port": cfg["port"],
                       "has_api_key": bool(cfg["api_key"])},
        }
    except Exception as e:
        return {
            "healthy": False, "error": str(e),
            "collections": [], "structure_exists": False, "domain_exists": False,
            "config": {"host": cfg["host"], "port": cfg["port"],
                       "has_api_key": bool(cfg["api_key"])},
        }
