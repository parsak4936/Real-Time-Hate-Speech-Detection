"""
Context Agent — discovers env_domain / env_subgenre / env_strictness for every
ingested record before it reaches Kafka.

Design:
    Discovery is agentic — the LLM proposes a domain in free text without
    being shown a closed taxonomy. Normalisation happens AFTER the LLM call
    via shared_utils/taxonomy.py, which maps the proposal onto a canonical
    analytics key while preserving the raw proposal alongside it.

    Strictness is reasoned by the LLM from principles. The taxonomy YAML
    only provides a fallback when the LLM output is malformed.

    On any failure the agent falls back to safe defaults so the pipeline
    never blocks ingestion.
"""

import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.abspath(os.path.join(current_dir, "../../"))
if src_dir not in sys.path:
    sys.path.append(src_dir)

from shared_utils.config import ACTIVE_MODEL
from shared_utils.llm import ollama_chat_json
from shared_utils.prompts import build_context_agent_prompt
from shared_utils.taxonomy import normalise_domain, default_strictness_for

_VALID_STRICTNESS = {"low", "medium", "high"}


def resolve_environment(source_platform: str, raw_meta: dict) -> dict:
    """
    Returns a dict carrying both normalised analytics keys and the raw LLM
    discovery, so downstream consumers can use either:

        {
            "env_domain":                "Gaming",          # canonical
            "env_domain_raw":            "esports tournament", # LLM proposal
            "env_domain_match":          "alias",           # exact|alias|fuzzy|unknown
            "env_subgenre":              "Dota 2 Major",
            "env_strictness":            "low",
            "env_strictness_reasoning":  "Live esports tournament — banter expected.",
        }

    The downstream Universal Schema relays every field as-is.
    """
    print(f"-> [Context Agent] Booting... Analyzing {source_platform} metadata.")
    print(f"-> [Context Agent] Using LLM: {ACTIVE_MODEL}")

    prompt = build_context_agent_prompt(source_platform, raw_meta)
    context_data = ollama_chat_json(prompt)

    if context_data is None:
        print("-> [Context Agent Error] Failed to parse AI response. Using fallback.")
        return _fallback_env()

    raw_domain = (context_data.get("env_domain") or "").strip()
    subgenre = (context_data.get("env_subgenre") or "").strip()
    strictness = (context_data.get("env_strictness") or "").strip().lower()
    strictness_reasoning = (context_data.get("env_strictness_reasoning") or "").strip()

    # Normalise the domain proposal onto the canonical taxonomy.
    domain_info = normalise_domain(raw_domain)
    canonical_domain = domain_info["canonical"]
    match_quality = domain_info["match_quality"]

    # Validate LLM strictness; fall back to the canonical's default if malformed.
    if strictness not in _VALID_STRICTNESS:
        fallback = default_strictness_for(canonical_domain)
        print(
            f"-> [Context Agent] LLM returned invalid strictness {strictness!r}; "
            f"falling back to canonical default for {canonical_domain!r}: {fallback!r}."
        )
        strictness = fallback
        if not strictness_reasoning:
            strictness_reasoning = f"(fallback: default strictness for {canonical_domain})"

    if match_quality == "unknown":
        print(
            f"-> [Context Agent] LLM proposed off-taxonomy domain {raw_domain!r}; "
            f"logged for review."
        )

    return {
        "env_domain":               canonical_domain,
        "env_domain_raw":           raw_domain,
        "env_domain_match":         match_quality,
        "env_subgenre":             subgenre,
        "env_strictness":           strictness,
        "env_strictness_reasoning": strictness_reasoning,
    }


def _fallback_env() -> dict:
    return {
        "env_domain":               "General",
        "env_domain_raw":           "",
        "env_domain_match":         "unknown",
        "env_subgenre":             "",
        "env_strictness":           default_strictness_for("General"),
        "env_strictness_reasoning": "(fallback: Context Agent LLM call failed)",
    }
