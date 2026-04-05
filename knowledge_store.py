# ══════════════════════════════════════════════════════════════════════════════
#  KNOWLEDGE STORE — Qdrant Wrapper for RAG
#  Two namespaces: structure_examples (agent output style) + domain_knowledge
#  Used by: ingestion.py, pages/admin.py, backend agents at runtime
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

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536  # text-embedding-3-small output dimension

COLLECTION_STRUCTURE = "structure_examples"
COLLECTION_DOMAIN = "domain_knowledge"

# Chunk config
CHUNK_SIZE_TOKENS = 500
CHUNK_OVERLAP_TOKENS = 50
# Approximate chars-per-token ratio for English text
CHARS_PER_TOKEN = 4


# ── Embedding Client ──────────────────────────────────────────────────────────

def get_embedding(api_key: str, text: str) -> list[float]:
    """Get embedding vector for a text chunk via OpenAI."""
    client = OpenAI(api_key=api_key)
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text,
    )
    return response.data[0].embedding


def get_embeddings_batch(api_key: str, texts: list[str]) -> list[list[float]]:
    """Batch embed multiple texts (max 2048 per call by OpenAI)."""
    client = OpenAI(api_key=api_key)
    # OpenAI batch limit is 2048 inputs
    all_embeddings = []
    batch_size = 100  # conservative batch to avoid token limits
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        response = client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=batch,
        )
        all_embeddings.extend([d.embedding for d in response.data])
    return all_embeddings


# ── Qdrant Client Factory ────────────────────────────────────────────────────

def get_qdrant_client() -> QdrantClient:
    """Create Qdrant client. Connects to local Docker instance."""
    return QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=30)


def ensure_collections():
    """Create both collections if they don't exist."""
    client = get_qdrant_client()
    existing = [c.name for c in client.get_collections().collections]

    for coll_name in [COLLECTION_STRUCTURE, COLLECTION_DOMAIN]:
        if coll_name not in existing:
            client.create_collection(
                collection_name=coll_name,
                vectors_config=VectorParams(
                    size=EMBEDDING_DIM,
                    distance=Distance.COSINE,
                ),
            )
            # Create payload indexes for fast filtering
            client.create_payload_index(
                collection_name=coll_name,
                field_name="agent_id",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
            client.create_payload_index(
                collection_name=coll_name,
                field_name="domain",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
            client.create_payload_index(
                collection_name=coll_name,
                field_name="subdomain",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
            client.create_payload_index(
                collection_name=coll_name,
                field_name="doc_id",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
    return True


# ── Chunking ──────────────────────────────────────────────────────────────────

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE_TOKENS,
               overlap: int = CHUNK_OVERLAP_TOKENS) -> list[dict]:
    """Split text into overlapping chunks. Returns list of {text, index, char_start, char_end}."""
    char_chunk = chunk_size * CHARS_PER_TOKEN
    char_overlap = overlap * CHARS_PER_TOKEN

    chunks = []
    start = 0
    idx = 0

    while start < len(text):
        end = start + char_chunk

        # Try to break at sentence boundary
        if end < len(text):
            # Look for sentence end within last 20% of chunk
            search_start = max(start, end - int(char_chunk * 0.2))
            last_period = text.rfind('. ', search_start, end)
            last_newline = text.rfind('\n', search_start, end)
            break_point = max(last_period, last_newline)
            if break_point > search_start:
                end = break_point + 1

        chunk_text_str = text[start:end].strip()
        if chunk_text_str:
            chunks.append({
                "text": chunk_text_str,
                "index": idx,
                "char_start": start,
                "char_end": end,
            })
            idx += 1

        start = end - char_overlap
        if start >= len(text):
            break
        # Safety: ensure forward progress
        if end >= len(text):
            break

    return chunks


# ── Storage Operations ────────────────────────────────────────────────────────

def generate_doc_id(filename: str, collection: str, agent_id: str = "",
                    domain: str = "", subdomain: str = "") -> str:
    """Deterministic document ID from metadata."""
    key = f"{collection}:{agent_id}:{domain}:{subdomain}:{filename}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def store_chunks(
    api_key: str,
    collection: str,
    chunks: list[dict],
    metadata: dict,
) -> int:
    """Embed and store chunks in Qdrant. Returns count of points stored."""
    if not chunks:
        return 0

    texts = [c["text"] for c in chunks]
    embeddings = get_embeddings_batch(api_key, texts)

    client = get_qdrant_client()
    points = []
    doc_id = metadata.get("doc_id", "unknown")

    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        # Generate a unique point ID from doc_id + chunk index
        point_id_str = f"{doc_id}_{i}"
        point_id_hash = int(hashlib.sha256(point_id_str.encode()).hexdigest()[:15], 16)

        payload = {
            **metadata,
            "chunk_text": chunk["text"],
            "chunk_index": chunk["index"],
            "char_start": chunk["char_start"],
            "char_end": chunk["char_end"],
            "stored_at": datetime.utcnow().isoformat(),
        }

        points.append(PointStruct(
            id=point_id_hash,
            vector=embedding,
            payload=payload,
        ))

    # Upsert in batches of 100
    batch_size = 100
    for i in range(0, len(points), batch_size):
        batch = points[i:i + batch_size]
        client.upsert(collection_name=collection, points=batch)

    return len(points)


def retrieve_chunks(
    api_key: str,
    collection: str,
    query_text: str,
    top_k: int = 5,
    filters: Optional[dict] = None,
    score_threshold: float = 0.3,
) -> list[dict]:
    """Retrieve top-k chunks by semantic similarity with optional metadata filters.

    Args:
        filters: dict of {field: value} for exact match filtering.
                 e.g. {"agent_id": "A04", "domain": "life_sciences"}
    Returns:
        list of {text, score, metadata} sorted by relevance.
    """
    query_embedding = get_embedding(api_key, query_text)

    qdrant_filter = None
    if filters:
        conditions = []
        for field, value in filters.items():
            if isinstance(value, list):
                # Match any of the values
                for v in value:
                    conditions.append(FieldCondition(
                        key=field, match=MatchValue(value=v)
                    ))
            else:
                conditions.append(FieldCondition(
                    key=field, match=MatchValue(value=value)
                ))
        if conditions:
            qdrant_filter = Filter(must=conditions)

    client = get_qdrant_client()
    results = client.search(
        collection_name=collection,
        query_vector=query_embedding,
        limit=top_k,
        query_filter=qdrant_filter,
        score_threshold=score_threshold,
    )

    return [
        {
            "text": hit.payload.get("chunk_text", ""),
            "score": hit.score,
            "metadata": {k: v for k, v in hit.payload.items() if k != "chunk_text"},
        }
        for hit in results
    ]


def delete_document(collection: str, doc_id: str) -> int:
    """Delete all chunks belonging to a document. Returns count of deleted points."""
    client = get_qdrant_client()

    # Count before deletion
    count_before = client.count(
        collection_name=collection,
        count_filter=Filter(must=[
            FieldCondition(key="doc_id", match=MatchValue(value=doc_id))
        ]),
    ).count

    # Delete by filter
    client.delete(
        collection_name=collection,
        points_selector=models.FilterSelector(
            filter=Filter(must=[
                FieldCondition(key="doc_id", match=MatchValue(value=doc_id))
            ]),
        ),
    )

    return count_before


def list_documents(collection: str, filters: Optional[dict] = None) -> list[dict]:
    """List unique documents in a collection, optionally filtered by metadata.
    Returns list of {doc_id, filename, agent_id, domain, subdomain, chunk_count, upload_date}.
    """
    client = get_qdrant_client()

    qdrant_filter = None
    if filters:
        conditions = []
        for field, value in filters.items():
            conditions.append(FieldCondition(
                key=field, match=MatchValue(value=value)
            ))
        if conditions:
            qdrant_filter = Filter(must=conditions)

    # Scroll through all points, extracting unique doc_ids
    docs = {}
    offset = None
    batch_size = 100

    while True:
        results, next_offset = client.scroll(
            collection_name=collection,
            scroll_filter=qdrant_filter,
            limit=batch_size,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )

        for point in results:
            doc_id = point.payload.get("doc_id", "unknown")
            if doc_id not in docs:
                docs[doc_id] = {
                    "doc_id": doc_id,
                    "filename": point.payload.get("filename", "unknown"),
                    "agent_id": point.payload.get("agent_id", ""),
                    "domain": point.payload.get("domain", ""),
                    "subdomain": point.payload.get("subdomain", ""),
                    "upload_date": point.payload.get("stored_at", ""),
                    "chunk_count": 0,
                }
            docs[doc_id]["chunk_count"] += 1

        if next_offset is None or len(results) < batch_size:
            break
        offset = next_offset

    return sorted(docs.values(), key=lambda d: d.get("upload_date", ""), reverse=True)


def get_collection_stats(collection: str) -> dict:
    """Get basic stats for a collection."""
    try:
        client = get_qdrant_client()
        info = client.get_collection(collection_name=collection)
        return {
            "total_points": info.points_count,
            "status": info.status.value if hasattr(info.status, 'value') else str(info.status),
        }
    except Exception as e:
        return {"total_points": 0, "status": f"error: {str(e)}"}


# ── Runtime Retrieval Helpers (used by agents) ────────────────────────────────

def retrieve_structure_examples(
    api_key: str,
    agent_id: str,
    query_text: str,
    domain: str = "",
    top_k: int = 5,
) -> list[dict]:
    """Retrieve structure/template examples for an agent.
    Used at agent runtime to inject reference style into prompts.
    """
    filters = {"agent_id": agent_id}
    if domain:
        filters["domain"] = domain

    return retrieve_chunks(
        api_key=api_key,
        collection=COLLECTION_STRUCTURE,
        query_text=query_text,
        top_k=top_k,
        filters=filters,
    )


def retrieve_domain_knowledge(
    api_key: str,
    subdomains: list[str],
    query_text: str,
    top_k: int = 5,
) -> list[dict]:
    """Retrieve domain knowledge chunks filtered by subdomain(s).
    Used at agent runtime to inject domain context into prompts.
    """
    all_results = []
    per_subdomain_k = max(2, top_k // len(subdomains)) if subdomains else top_k

    for subdomain in subdomains:
        results = retrieve_chunks(
            api_key=api_key,
            collection=COLLECTION_DOMAIN,
            query_text=query_text,
            top_k=per_subdomain_k,
            filters={"subdomain": subdomain},
        )
        all_results.extend(results)

    # De-duplicate and sort by score, return top_k
    seen = set()
    unique = []
    for r in sorted(all_results, key=lambda x: x["score"], reverse=True):
        text_hash = hashlib.md5(r["text"].encode()).hexdigest()
        if text_hash not in seen:
            seen.add(text_hash)
            unique.append(r)
    return unique[:top_k]


def format_rag_context(chunks: list[dict], section_label: str) -> str:
    """Format retrieved chunks into a prompt-injectable string.
    Returns empty string if no chunks found.
    """
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
    """Check if Qdrant is reachable and collections exist."""
    try:
        client = get_qdrant_client()
        collections = [c.name for c in client.get_collections().collections]
        return {
            "healthy": True,
            "collections": collections,
            "structure_exists": COLLECTION_STRUCTURE in collections,
            "domain_exists": COLLECTION_DOMAIN in collections,
        }
    except Exception as e:
        return {
            "healthy": False,
            "error": str(e),
            "collections": [],
            "structure_exists": False,
            "domain_exists": False,
        }
