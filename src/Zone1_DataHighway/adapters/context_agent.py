"""
Context Agent — assigns env_domain / env_subgenre / env_strictness to every
ingested record before it reaches Kafka.

The agent is intentionally headless: no UI, no state. It just maps raw
metadata (scraped from the source platform) to the closed taxonomy
declared in shared_utils/prompts.py. On any failure it falls back to a
safe default so the pipeline never blocks.
"""

import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.abspath(os.path.join(current_dir, "../../"))
if src_dir not in sys.path:
    sys.path.append(src_dir)

from shared_utils.config import ACTIVE_MODEL
from shared_utils.llm import ollama_chat_json
from shared_utils.prompts import (
    build_context_agent_prompt,
    ENV_DOMAINS,
    ENV_STRICTNESS,
    DOMAIN_DEFAULT_STRICTNESS,
)


def resolve_environment(source_platform: str, raw_meta: dict):
    """
    Returns (env_domain, env_strictness, env_subgenre).

    env_domain is always one of the closed taxonomy values in ENV_DOMAINS.
    env_subgenre is a short free-text refinement (may be "").
    env_strictness is one of {"low", "medium", "high"}.
    """
    print(f"-> [Context Agent] Booting... Analyzing {source_platform} metadata.")
    print(f"-> [Context Agent] Using LLM: {ACTIVE_MODEL}")

    prompt = build_context_agent_prompt(source_platform, raw_meta)
    context_data = ollama_chat_json(prompt)

    if context_data is None:
        print("-> [Context Agent Error] Failed to parse AI response. Using fallback.")
        return "General", "medium", ""

    domain = context_data.get("env_domain", "General")
    subgenre = context_data.get("env_subgenre", "") or ""
    strictness = context_data.get("env_strictness", "")

    # Closed-taxonomy enforcement: clamp any out-of-taxonomy LLM output.
    if domain not in ENV_DOMAINS:
        print(f"-> [Context Agent] LLM returned out-of-taxonomy domain '{domain}'; clamping to 'General'.")
        domain = "General"

    if strictness not in ENV_STRICTNESS:
        strictness = DOMAIN_DEFAULT_STRICTNESS.get(domain, "medium")

    return domain, strictness, subgenre
