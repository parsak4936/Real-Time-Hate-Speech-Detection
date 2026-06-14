"""
Domain taxonomy normaliser.

The Context Agent is deliberately NOT given a closed taxonomy in its prompt
(see docs/PROMPTS.md for the rationale). It proposes a domain in free text
based purely on stream metadata. This module bridges that agentic discovery
behaviour with the analytics layer's need for a stable canonical key.

Three things live here:

1. `load_taxonomy()` — read config/taxonomy.yaml once and cache it.
2. `normalise_domain(raw)` — map a free-text LLM proposal to a canonical
   entry via exact match → alias match → fuzzy match → unknown policy.
3. `default_strictness_for(canonical)` — fallback used by the Context Agent
   when the LLM's strictness output is malformed.

The taxonomy file is a YAML seed list, not a constraint. Adding a category
is a config-only change.
"""

import datetime
import os
import threading
from difflib import SequenceMatcher
from pathlib import Path

import yaml

_LOCK = threading.Lock()
_CACHED_TAXONOMY = None

_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "taxonomy.yaml"


def load_taxonomy(path: Path = _DEFAULT_PATH):
    """Load and cache the taxonomy YAML. Subsequent calls are free."""
    global _CACHED_TAXONOMY
    with _LOCK:
        if _CACHED_TAXONOMY is None:
            with open(path, "r", encoding="utf-8") as f:
                _CACHED_TAXONOMY = yaml.safe_load(f)
    return _CACHED_TAXONOMY


def reload_taxonomy(path: Path = _DEFAULT_PATH):
    """Force a re-read from disk (useful for tests or runtime hot-swap)."""
    global _CACHED_TAXONOMY
    with _LOCK:
        _CACHED_TAXONOMY = None
    return load_taxonomy(path)


def canonical_names() -> list:
    """Return the current canonical name list — used by other modules for fallbacks."""
    tax = load_taxonomy()
    return [entry["name"] for entry in tax.get("canonical", [])]


def default_strictness_for(canonical: str) -> str:
    """Return the YAML-declared default strictness for a canonical name, else 'medium'."""
    tax = load_taxonomy()
    for entry in tax.get("canonical", []):
        if entry["name"].lower() == canonical.lower():
            return entry.get("default_strictness", "medium")
    return "medium"


def normalise_domain(raw_domain: str) -> dict:
    """
    Map a free-text LLM proposal onto the canonical taxonomy.

    Returns a dict:
        {
          "canonical":      "Gaming",       # canonical name to write to env_domain
          "raw":            "esports",      # the LLM's original proposal (preserved)
          "match_quality":  "alias",        # one of: exact | alias | fuzzy | unknown
          "default_strictness": "low",
        }

    When no match meets the fuzzy threshold, the configured `unknown_policy`
    determines behaviour:
      - accept_and_log: keep raw (title-cased) and append to the unknown log.
      - clamp_to_general: replace with "General".
    """
    tax = load_taxonomy()
    raw_clean = (raw_domain or "").strip()

    if not raw_clean:
        return {
            "canonical": "General",
            "raw": "",
            "match_quality": "unknown",
            "default_strictness": default_strictness_for("General"),
        }

    raw_lower = raw_clean.lower()

    # Pass 1 — exact match on canonical name.
    for entry in tax["canonical"]:
        if raw_lower == entry["name"].lower():
            return {
                "canonical": entry["name"],
                "raw": raw_clean,
                "match_quality": "exact",
                "default_strictness": entry.get("default_strictness", "medium"),
            }

    # Pass 2 — exact match on any alias.
    for entry in tax["canonical"]:
        aliases = [a.lower() for a in entry.get("aliases", [])]
        if raw_lower in aliases:
            return {
                "canonical": entry["name"],
                "raw": raw_clean,
                "match_quality": "alias",
                "default_strictness": entry.get("default_strictness", "medium"),
            }

    # Pass 3 — fuzzy match against every name + alias.
    threshold = float(tax.get("fuzzy_match_threshold", 0.75))
    best_entry = None
    best_score = 0.0
    for entry in tax["canonical"]:
        candidates = [entry["name"]] + entry.get("aliases", [])
        for candidate in candidates:
            score = SequenceMatcher(None, raw_lower, candidate.lower()).ratio()
            if score > best_score:
                best_score = score
                best_entry = entry

    if best_entry is not None and best_score >= threshold:
        return {
            "canonical": best_entry["name"],
            "raw": raw_clean,
            "match_quality": "fuzzy",
            "default_strictness": best_entry.get("default_strictness", "medium"),
        }

    # Pass 4 — unknown policy.
    policy = tax.get("unknown_policy", {})
    action = policy.get("action", "accept_and_log")

    if action == "clamp_to_general":
        return {
            "canonical": "General",
            "raw": raw_clean,
            "match_quality": "unknown",
            "default_strictness": default_strictness_for("General"),
        }

    # accept_and_log
    log_path = policy.get("log_path")
    if log_path:
        _append_unknown_log(raw_clean, log_path)

    return {
        "canonical": raw_clean.title(),
        "raw": raw_clean,
        "match_quality": "unknown",
        "default_strictness": "medium",
    }


def _append_unknown_log(raw_domain: str, log_path: str) -> None:
    """Append a single line to the unknown-domain log for later operator review."""
    try:
        log_path_abs = Path(log_path)
        if not log_path_abs.is_absolute():
            log_path_abs = Path(__file__).resolve().parents[2] / log_path
        log_path_abs.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now().isoformat(timespec="seconds")
        with open(log_path_abs, "a", encoding="utf-8") as f:
            f.write(f"{timestamp}\t{raw_domain}\n")
    except Exception as exc:
        # Logging failure is never fatal to ingestion — print and continue.
        print(f"-> [Taxonomy] Could not write unknown-domain log: {exc}")
