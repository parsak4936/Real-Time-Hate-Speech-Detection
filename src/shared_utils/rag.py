"""
Retrieval-Augmented Moderation — embedding + direct-HTTP Qdrant access.

Why direct HTTP instead of qdrant-client:
    The official qdrant-client Python library hangs on Windows when the
    server is on a different patch version (1.10 server, 1.17 client). Even
    with check_compatibility=False, the internal HTTP layer wedges on
    .get_collections() and never returns. Bare `requests` calls against
    the same endpoints return in <100ms. So this module uses requests
    directly for all Qdrant operations. The embedder (sentence-transformers)
    still lazy-loads as before.

Public API (unchanged from previous version):
    - get_embedder()                          → SentenceTransformer model
    - get_client()                            → no-op kept for compatibility
    - ensure_collection_exists()              → creates collection if missing
    - index_record(record)                    → embed + upsert one ES record
    - index_records_bulk(records)             → batched embed + upsert
    - retrieve_similar(query, k, exclude_id)  → top-k cosine-similar hits
    - format_precedents_for_prompt(hits)      → prompt-ready string
    - fetch_retrieval_bundle(text, ...)       → convenience dict
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Iterable, Optional

import requests
import yaml

# CRITICAL: Set CUDA env var BEFORE any torch/transformers import.
# This prevents PyTorch from stalling on cuda.is_available() probes on Windows.
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

from shared_utils.config import QDRANT_HOST, QDRANT_PORT, QDRANT_COLLECTION

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "rag.yaml"

_CONFIG: dict | None = None
_EMBEDDER = None

QDRANT_URL = f"http://{QDRANT_HOST}:{QDRANT_PORT}"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config(path: Path = _CONFIG_PATH) -> dict:
    global _CONFIG
    if _CONFIG is None:
        with open(path, "r", encoding="utf-8") as f:
            _CONFIG = yaml.safe_load(f)
    return _CONFIG


# ---------------------------------------------------------------------------
# Direct-HTTP Qdrant helpers
# ---------------------------------------------------------------------------

def _qdrant_get(path: str, timeout: float = 10):
    r = requests.get(f"{QDRANT_URL}{path}", timeout=timeout)
    r.raise_for_status()
    return r.json()


def _qdrant_put(path: str, json_data: dict, timeout: float = 30):
    r = requests.put(f"{QDRANT_URL}{path}", json=json_data, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _qdrant_post(path: str, json_data: dict, timeout: float = 30):
    r = requests.post(f"{QDRANT_URL}{path}", json=json_data, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _collection_exists() -> bool:
    try:
        r = requests.get(f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def ensure_collection_exists():
    """Create the Qdrant collection if it doesn't already exist."""
    cfg = load_config()
    dim = int(cfg["embedding"]["dim"])

    if _collection_exists():
        print(f"-> [RAG] Collection {QDRANT_COLLECTION!r} already exists.")
        return

    print(f"-> [RAG] Creating collection {QDRANT_COLLECTION!r} (dim={dim}, cosine)...")
    _qdrant_put(f"/collections/{QDRANT_COLLECTION}", {
        "vectors": {"size": dim, "distance": "Cosine"},
    })
    print(f"-> [RAG] Collection created.")


def get_client():
    """Compatibility shim — old callers expected to call this to ensure
    the collection. We forward to ensure_collection_exists()."""
    ensure_collection_exists()


# ---------------------------------------------------------------------------
# Embedder (lazy-loaded sentence-transformers)
# ---------------------------------------------------------------------------

def get_embedder():
    global _EMBEDDER
    if _EMBEDDER is None:
        import time
        cfg = load_config()
        device = cfg["embedding"].get("device", "cpu")
        
        # qdrant-client hangs on Windows; we use requests directly instead.
        # PyTorch is similarly fragile — force device="cpu" in rag.yaml
        # and skip any torch.cuda probes entirely.
        print(f"-> [RAG] Importing sentence-transformers (first import is slow, ~20-40s)...", flush=True)
        from sentence_transformers import SentenceTransformer
        model_name = cfg["embedding"]["model_name"]
        
        print(f"-> [RAG] Loading embedding model {model_name!r} on device={device}...", flush=True)
        print(f"-> [RAG] First-run downloads ~80 MB. Cached after that.", flush=True)
        _t0 = time.time()
        _EMBEDDER = SentenceTransformer(model_name, device=device)
        elapsed = time.time() - _t0
        print(f"-> [RAG] Embedder ready in {elapsed:.1f}s.", flush=True)
    return _EMBEDDER


# ---------------------------------------------------------------------------
# Point-id helpers
# ---------------------------------------------------------------------------

def _stable_point_id(message_id: str) -> int:
    """Qdrant requires unsigned-int or UUID IDs. Hash message_id deterministically
    to a 63-bit positive int (collisions vanishingly unlikely at our scale)."""
    digest = hashlib.blake2b(message_id.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") & ((1 << 63) - 1)


# ---------------------------------------------------------------------------
# Indexing
# ---------------------------------------------------------------------------

def _build_payload(record: dict) -> dict:
    """Strip the record down to fields safe to use as Qdrant payload."""
    return {
        "message_id":              record.get("message_id"),
        "text":                    record.get("text"),
        "timestamp":               record.get("timestamp"),
        "author_id":               record.get("author_id"),
        "author_name":             record.get("author_name"),
        "env_domain":              record.get("env_domain"),
        "env_subgenre":            record.get("env_subgenre"),
        "env_strictness":          record.get("env_strictness"),
        "model_label":             record.get("model_label"),
        "model_confidence":        record.get("model_confidence"),
        "agent_final_decision":    record.get("agent_final_decision"),
        # NOTE: human_ground_truth deliberately omitted to prevent label
        # leakage during leave-one-out RAG evaluation.
    }


def index_record(record: dict) -> bool:
    text = (record.get("text") or "").strip()
    if not text:
        return False
    message_id = record.get("message_id")
    if not message_id or message_id == "UNKNOWN":
        return False

    ensure_collection_exists()
    embedder = get_embedder()
    vector = embedder.encode(text, convert_to_numpy=True).tolist()

    _qdrant_put(f"/collections/{QDRANT_COLLECTION}/points?wait=true", {
        "points": [{
            "id":      _stable_point_id(message_id),
            "vector":  vector,
            "payload": _build_payload(record),
        }],
    })
    return True


def index_records_bulk(records: Iterable[dict]) -> int:
    cfg = load_config()
    batch_size = int(cfg["embedding"].get("batch_size", 32))

    ensure_collection_exists()
    embedder = get_embedder()

    batch_texts: list[str] = []
    batch_payloads: list[dict] = []
    batch_ids: list[int] = []
    total = 0

    def _flush():
        nonlocal total
        if not batch_texts:
            return
        vectors = embedder.encode(
            batch_texts,
            convert_to_numpy=True,
            batch_size=batch_size,
        ).tolist()
        _qdrant_put(f"/collections/{QDRANT_COLLECTION}/points?wait=true", {
            "points": [
                {"id": pid, "vector": vec, "payload": pl}
                for pid, vec, pl in zip(batch_ids, vectors, batch_payloads)
            ],
        })
        total += len(batch_texts)
        print(f"  ...upserted {total} records")
        batch_texts.clear()
        batch_payloads.clear()
        batch_ids.clear()

    for record in records:
        text = (record.get("text") or "").strip()
        message_id = record.get("message_id")
        if not text or not message_id or message_id == "UNKNOWN":
            continue

        batch_texts.append(text)
        batch_ids.append(_stable_point_id(message_id))
        batch_payloads.append(_build_payload(record))

        if len(batch_texts) >= batch_size:
            _flush()

    _flush()
    return total


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

def retrieve_similar(
    query_text: str,
    k: Optional[int] = None,
    exclude_message_id: Optional[str] = None,
) -> list[dict]:
    cfg = load_config()
    rcfg = cfg.get("retrieval", {})
    if k is None:
        k = int(rcfg.get("top_k", 5))
    threshold = float(rcfg.get("similarity_threshold", 0.55))
    exclude_self = bool(rcfg.get("exclude_self", True))

    query_text = (query_text or "").strip()
    if not query_text:
        return []

    embedder = get_embedder()
    vector = embedder.encode(query_text, convert_to_numpy=True).tolist()

    raw = _qdrant_post(f"/collections/{QDRANT_COLLECTION}/points/search", {
        "vector":          vector,
        "limit":           k + (1 if exclude_self else 0),
        "score_threshold": threshold,
        "with_payload":    True,
    })

    hits = []
    for point in raw.get("result", []):
        payload = point.get("payload") or {}
        if exclude_self and exclude_message_id and payload.get("message_id") == exclude_message_id:
            continue
        hits.append({"score": float(point.get("score", 0.0)), "payload": payload})
        if len(hits) >= k:
            break
    return hits


# ---------------------------------------------------------------------------
# Prompt formatting
# ---------------------------------------------------------------------------

def format_precedents_for_prompt(hits: list[dict], max_text_len: int = 80) -> str:
    if not hits:
        return "(no semantically similar precedents found)"

    lines = []
    for hit in hits:
        score = hit.get("score", 0.0)
        p = hit.get("payload", {}) or {}
        label = p.get("model_label", "?")
        agent = p.get("agent_final_decision") or "—"
        domain = p.get("env_domain", "?")
        text = (p.get("text") or "").replace("\n", " ")[:max_text_len]
        lines.append(
            f"  [score={score:.2f} | static={label:<9s} | agent={agent:<14s} | "
            f"domain={domain}] {text}"
        )
    return "\n".join(lines)


def fetch_retrieval_bundle(
    query_text: str,
    k: Optional[int] = None,
    exclude_message_id: Optional[str] = None,
) -> dict:
    hits = retrieve_similar(query_text, k=k, exclude_message_id=exclude_message_id)
    return {
        "precedents_text":   format_precedents_for_prompt(hits),
        "precedents_count":  len(hits),
        "precedent_ids":     [(h["payload"] or {}).get("message_id") for h in hits if h.get("payload")],
        "raw_hits":          hits,
    }
