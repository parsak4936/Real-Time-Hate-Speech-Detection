"""
Retrieval backend selector — the switchable module (RAG vs LLM-Wiki).

One interface, two interchangeable backends. The `RETRIEVAL_BACKEND` config flag
decides what grounds the Tier-2 judge:

    "none"  -> no retrieval; the judge runs memory-only or baseline.
    "rag"   -> semantically similar PAST CASES from Qdrant (shared_utils.rag).
    "wiki"  -> curated KNOWLEDGE from the wiki/ pages (shared_utils.wiki).

Both backends are hidden behind `fetch_context()` and `build_prompt()`, so calling
code never needs to know which one is active. Switching between RAG and the LLM-Wiki
is a single flag; nothing else changes. This is the concrete form of the thesis's
"switchable retrieval backend" claim, and the live judge (xai_batch_judge) uses it.
"""

from __future__ import annotations

from typing import Optional

from shared_utils.config import RETRIEVAL_BACKEND
from shared_utils import prompts

_VALID = ("none", "rag", "wiki")


def active_backend() -> str:
    b = (RETRIEVAL_BACKEND or "none").strip().lower()
    return b if b in _VALID else "none"


def fetch_context(text: str, domain: str = "General", message_id: Optional[str] = None) -> dict:
    """
    Return the active backend's context in a uniform shape:
        {"backend": <name>, "context_text": <prompt-ready string>, "count": <int>}
    Imports are local so a backend's dependencies load only when that backend is used.
    """
    backend = active_backend()
    if backend == "rag":
        from shared_utils.rag import fetch_retrieval_bundle
        rb = fetch_retrieval_bundle(query_text=text, exclude_message_id=message_id)
        return {"backend": "rag", "context_text": rb["precedents_text"], "count": rb["precedents_count"]}
    if backend == "wiki":
        from shared_utils.wiki import fetch_wiki_bundle
        wb = fetch_wiki_bundle(query_text=text, domain=domain)
        return {"backend": "wiki", "context_text": wb["knowledge_text"], "count": wb["count"]}
    return {"backend": "none", "context_text": "", "count": 0}


def build_prompt(
    *,
    raw_text: str,
    original_prediction: str,
    confidence: float,
    domain: str,
    strictness: str,
    subgenre: str,
    context_text: str,
) -> str:
    """Pick the judge prompt that matches the active backend."""
    backend = active_backend()
    if backend == "rag":
        return prompts.build_judge_prompt_with_rag(
            raw_text, original_prediction, confidence, domain, strictness, context_text, subgenre
        )
    if backend == "wiki":
        return prompts.build_judge_prompt_with_wiki(
            raw_text, original_prediction, confidence, domain, strictness, context_text, subgenre
        )
    return prompts.build_judge_prompt(
        raw_text, original_prediction, confidence, domain, strictness, subgenre
    )
