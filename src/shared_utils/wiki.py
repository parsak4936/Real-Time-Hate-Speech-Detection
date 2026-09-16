"""
LLM Wiki — curated-knowledge retrieval backend (the switchable alternative to RAG).

Where `rag.py` retrieves similar PAST CASES from Qdrant, this module retrieves
relevant CURATED KNOWLEDGE (policies, domain rules, glossary, edge cases) from the
version-controlled markdown pages under `wiki/`. Both backends inject context into
the SAME Tier-2 judge prompt slot, so they can be compared head to head; the only
variable between them is the corpus, not the retriever.

Design (Karpathy "LLM Wiki" pattern, adapted for moderation):
    - Each `wiki/*.md` page is split into titled entries (by `##` headings).
    - Entries are embedded ONCE with the same MiniLM model RAG uses (reused from
      rag.get_embedder), cached in memory.
    - For a query, the core policy page and the matching domain page are always
      included; the top-k most relevant glossary/edge-case entries are added by
      cosine similarity. That is "consult the relevant wiki pages", not "find
      similar past messages".

Public API (mirrors rag.py):
    - retrieve_wiki(query_text, domain, k)   -> list[entry dicts]
    - format_wiki_for_prompt(entries)        -> prompt-ready string
    - fetch_wiki_bundle(query_text, domain)  -> convenience dict
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import numpy as np
import yaml

# Reuse RAG's embedder so both backends share the exact same encoder.
from shared_utils.rag import get_embedder

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _REPO_ROOT / "config" / "wiki.yaml"

_CONFIG: dict | None = None
_ENTRIES: list[dict] | None = None      # {source, kind, domain, title, text}
_ENTRY_VECS: np.ndarray | None = None   # (n, dim) L2-normalised


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config(path: Path = _CONFIG_PATH) -> dict:
    global _CONFIG
    if _CONFIG is None:
        with open(path, "r", encoding="utf-8") as f:
            _CONFIG = yaml.safe_load(f)
    return _CONFIG


def _kb_dir() -> Path:
    return _REPO_ROOT / load_config()["knowledge_base"]["path"]


# ---------------------------------------------------------------------------
# Knowledge-base loading + chunking
# ---------------------------------------------------------------------------

# domain_<tag>.md pages match a message's env_domain by these keyword hints.
_DOMAIN_HINTS = {
    "gaming":        ["gam", "esport", "stream", "twitch"],
    "politics_news": ["polit", "news", "current", "govern"],
    "reviews":       ["review", "ecommerce", "e-commerce", "shopping", "retail", "trustpilot", "product"],
    "general":       ["general"],
}


def _kind_and_domain(stem: str) -> tuple[str, str]:
    """Derive an entry's kind (policy/domain/glossary/edge/other) and domain tag."""
    if stem.startswith("policy"):
        return "policy", ""
    if stem.startswith("domain_"):
        return "domain", stem[len("domain_"):]
    if stem.startswith("glossary"):
        return "glossary", ""
    if stem.startswith("edge"):
        return "edge", ""
    return "other", ""


def _parse_page(path: Path) -> list[dict]:
    """Split one markdown page into titled entries by '##' headings."""
    kind, domain = _kind_and_domain(path.stem)
    if kind == "other" and path.stem == "index":
        return []  # the index page is navigation, not knowledge

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    page_title = path.stem
    for ln in lines:
        if ln.startswith("# "):
            page_title = ln[2:].strip()
            break

    entries: list[dict] = []
    cur_title = page_title
    cur_body: list[str] = []

    def _flush():
        body = "\n".join(cur_body).strip()
        if body:
            entries.append({
                "source": path.stem,
                "kind": kind,
                "domain": domain,
                "title": cur_title,
                "text": body,
            })

    for ln in lines:
        if ln.startswith("# "):
            continue  # page title, already captured
        if ln.startswith("## "):
            _flush()
            cur_title = f"{page_title} > {ln[3:].strip()}"
            cur_body = []
        else:
            cur_body.append(ln)
    _flush()
    return entries


def _load_entries() -> list[dict]:
    kb = _kb_dir()
    if not kb.exists():
        return []
    entries: list[dict] = []
    for path in sorted(kb.glob("*.md")):
        entries.extend(_parse_page(path))
    return entries


def _get_index() -> tuple[list[dict], np.ndarray]:
    """Lazily load + embed the knowledge base once, then cache it."""
    global _ENTRIES, _ENTRY_VECS
    if _ENTRIES is None:
        _ENTRIES = _load_entries()
        if _ENTRIES:
            embedder = get_embedder()
            texts = [f"{e['title']}\n{e['text']}" for e in _ENTRIES]
            vecs = embedder.encode(texts, convert_to_numpy=True)
            _ENTRY_VECS = _l2_normalise(vecs)
        else:
            _ENTRY_VECS = np.zeros((0, 384), dtype=np.float32)
    return _ENTRIES, _ENTRY_VECS


def _l2_normalise(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return mat / norms


def _match_domain_tag(domain: str) -> str:
    d = (domain or "").strip().lower()
    for tag, hints in _DOMAIN_HINTS.items():
        if tag == "general":
            continue
        if any(h in d for h in hints):
            return tag
    return "general"


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

def retrieve_wiki(query_text: str, domain: str = "General", k: Optional[int] = None) -> list[dict]:
    cfg = load_config().get("retrieval", {})
    if k is None:
        k = int(cfg.get("top_k", 4))
    threshold = float(cfg.get("similarity_threshold", 0.15))

    entries, vecs = _get_index()
    if not entries:
        return []

    selected: list[dict] = []
    used: set[int] = set()

    if cfg.get("always_include_policy", True):
        for i, e in enumerate(entries):
            if e["kind"] == "policy":
                selected.append({**e, "score": None})
                used.add(i)

    if cfg.get("always_include_domain", True):
        dtag = _match_domain_tag(domain)
        for i, e in enumerate(entries):
            if e["kind"] == "domain" and e["domain"] == dtag and i not in used:
                selected.append({**e, "score": None})
                used.add(i)

    query_text = (query_text or "").strip()
    if query_text and k > 0:
        qv = get_embedder().encode(query_text, convert_to_numpy=True)
        qv = qv / (np.linalg.norm(qv) or 1.0)
        sims = vecs @ qv
        for i in np.argsort(-sims):
            i = int(i)
            if i in used:
                continue
            if sims[i] < threshold:
                break
            selected.append({**entries[i], "score": float(sims[i])})
            used.add(i)
            if sum(1 for s in selected if s.get("score") is not None) >= k:
                break

    return selected


# ---------------------------------------------------------------------------
# Prompt formatting
# ---------------------------------------------------------------------------

def format_wiki_for_prompt(entries: list[dict], max_text_len: int = 600) -> str:
    if not entries:
        return "(no relevant knowledge-base entries found)"
    lines = []
    for e in entries:
        tag = e["kind"].upper()
        score = "" if e.get("score") is None else f" | relevance={e['score']:.2f}"
        body = e["text"].replace("\n", " ").strip()[:max_text_len]
        lines.append(f"[{tag}: {e['title']}{score}]\n{body}")
    return "\n\n".join(lines)


def fetch_wiki_bundle(query_text: str, domain: str = "General", k: Optional[int] = None) -> dict:
    entries = retrieve_wiki(query_text, domain=domain, k=k)
    return {
        "knowledge_text": format_wiki_for_prompt(entries),
        "pages_used": [e["title"] for e in entries],
        "count": len(entries),
        "raw_entries": entries,
    }
