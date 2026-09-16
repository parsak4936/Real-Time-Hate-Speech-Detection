"""
Stage 4 — Multi-Agent decomposition.

The monolithic Tier-2 judge is replaced by FOUR specialist agents that run
in sequence, each a focused LLM call:

    1. Risk Scorer        — scores message content in isolation (0..1).
    2. Behavior Profiler  — characterises the author from their history.
    3. Escalator          — routes (auto_clear / auto_flag / human_review).
    4. Supervisor         — reconciles all signals into the final verdict.

`run_multi_agent()` orchestrates them and returns a dict carrying the final
decision PLUS every intermediate signal, so the evaluation notebook (and the
thesis) can analyse how each agent contributed.

This module performs NO Elasticsearch or Qdrant queries itself — the caller
passes in a pre-fetched memory bundle (from shared_utils.memory) and an
optional precedents string (from shared_utils.rag). That keeps the agent
logic pure and testable, and lets the replay script control retrieval cost.

Cost note: 4 LLM calls per record (~20-30s each on gpt-oss:120b-cloud).
For a 298-record benchmark expect ~1.5-2 hours. Use the replay script's
--limit flag to test on a handful first.
"""

from __future__ import annotations

from shared_utils.llm import ollama_chat_json
from shared_utils.prompts import (
    build_risk_scorer_prompt,
    build_behavior_profiler_prompt,
    build_escalator_prompt,
    build_supervisor_prompt,
)

_VALID_DECISIONS = {"Correct", "False Positive", "False Negative"}


def _risk_score(raw_text, domain, strictness, subgenre):
    res = ollama_chat_json(build_risk_scorer_prompt(raw_text, domain, strictness, subgenre))
    if not res:
        return 0.5, "(risk scorer parse failure)"
    try:
        score = float(res.get("risk_score", 0.5))
    except (TypeError, ValueError):
        score = 0.5
    score = max(0.0, min(1.0, score))
    return score, str(res.get("rationale", ""))[:300]


def _behavior_profile(author_name, fingerprint, user_history_text):
    res = ollama_chat_json(build_behavior_profiler_prompt(author_name, fingerprint, user_history_text))
    if not res:
        return "medium", "(profiler parse failure)"
    behavior_risk = str(res.get("behavior_risk", "medium")).strip().lower()
    if behavior_risk not in ("low", "medium", "high"):
        behavior_risk = "medium"
    return behavior_risk, str(res.get("profile_summary", ""))[:300]


def _escalate(raw_text, risk_score, behavior_risk, thread_context_text, strictness):
    res = ollama_chat_json(
        build_escalator_prompt(raw_text, risk_score, behavior_risk, thread_context_text, strictness)
    )
    if not res:
        return "human_review", True, "(escalator parse failure)"
    action = str(res.get("action", "human_review")).strip().lower()
    if action not in ("auto_clear", "auto_flag", "human_review"):
        action = "human_review"
    escalate = bool(res.get("escalate_to_human", action == "human_review"))
    return action, escalate, str(res.get("rationale", ""))[:300]


def _supervise(raw_text, original_prediction, confidence, domain, strictness,
               risk_score, risk_rationale, behavior_risk, profile_summary,
               escalation_action, precedents_text, subgenre):
    res = ollama_chat_json(build_supervisor_prompt(
        raw_text, original_prediction, confidence, domain, strictness,
        risk_score, risk_rationale, behavior_risk, profile_summary,
        escalation_action, precedents_text, subgenre,
    ))
    if not res:
        return "Parsing Error", "(supervisor parse failure)"
    decision = str(res.get("decision", "")).strip()
    # Tolerate minor casing / wording drift.
    for valid in _VALID_DECISIONS:
        if decision.lower() == valid.lower():
            decision = valid
            break
    else:
        decision = "Parsing Error"
    return decision, str(res.get("explanation", ""))[:500]


def run_multi_agent(
    raw_text: str,
    original_prediction: str,
    confidence: float,
    domain: str,
    strictness: str,
    *,
    author_name: str = "Unknown",
    fingerprint: str = "(no fingerprint)",
    user_history_text: str = "(no history)",
    thread_context_text: str = "(no thread context)",
    precedents_text: str = "",
    subgenre: str = "",
) -> dict:
    """
    Run the four-agent pipeline. Returns a dict with the final decision and
    every intermediate signal. Never raises — parse failures degrade to
    sensible defaults so a batch run is not interrupted by one bad record.
    """
    # 1. Risk Scorer (content only)
    risk_score, risk_rationale = _risk_score(raw_text, domain, strictness, subgenre)

    # 2. Behavior Profiler (history only)
    behavior_risk, profile_summary = _behavior_profile(author_name, fingerprint, user_history_text)

    # 3. Escalator (routing)
    action, escalate, escalation_rationale = _escalate(
        raw_text, risk_score, behavior_risk, thread_context_text, strictness
    )

    # 4. Supervisor (final verdict)
    decision, explanation = _supervise(
        raw_text, original_prediction, confidence, domain, strictness,
        risk_score, risk_rationale, behavior_risk, profile_summary,
        action, precedents_text, subgenre,
    )

    return {
        "decision": decision,
        "explanation": explanation,
        "risk_score": risk_score,
        "risk_rationale": risk_rationale,
        "behavior_risk": behavior_risk,
        "profile_summary": profile_summary,
        "escalation_action": action,
        "escalate_to_human": escalate,
        "escalation_rationale": escalation_rationale,
    }
