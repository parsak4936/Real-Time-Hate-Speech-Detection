"""
Canonical prompt library for the Modular Moderation Pipeline.

Every LLM-facing string used anywhere in src/ MUST live here. Agents import
the constants or call the build_* helpers — never inline prompt text in
the agent modules themselves. This is the single source of truth that the
thesis (docs/PROMPTS.md) cites.

Closed taxonomies are exported so the Context Agent prompt and any
downstream validator agree on the legal value space.
"""

# ---------------------------------------------------------------------------
# Closed taxonomies (used by Context Agent + downstream validators)
# ---------------------------------------------------------------------------

ENV_DOMAINS = [
    "Gaming",
    "Politics",
    "News",
    "Music",
    "Sports",
    "Education",
    "Entertainment",
    "Technology",
    "Lifestyle",
    "General",
]

ENV_STRICTNESS = ["low", "medium", "high"]

# Reference mapping from coarse domain -> default strictness. The LLM may
# override on a per-stream basis but this is the fallback when parsing fails.
DOMAIN_DEFAULT_STRICTNESS = {
    "Gaming": "low",
    "Entertainment": "low",
    "Music": "medium",
    "Sports": "medium",
    "Lifestyle": "medium",
    "Technology": "medium",
    "Education": "medium",
    "General": "medium",
    "News": "high",
    "Politics": "high",
}


# ---------------------------------------------------------------------------
# Context Agent — assigns env_domain / env_subgenre / env_strictness
# ---------------------------------------------------------------------------

def build_context_agent_prompt(source_platform: str, raw_meta: dict) -> str:
    meta_string = "\n".join(f"{k.capitalize()}: {v}" for k, v in raw_meta.items())
    domains = " | ".join(ENV_DOMAINS)
    return f"""You are an automated metadata classifier for a Trust & Safety data ingestion pipeline.
Analyze the following metadata scraped from a {source_platform} stream.

--- METADATA ---
{meta_string}
----------------

TASK:
1. Choose ONE env_domain from this CLOSED list (no other value is permitted):
   {domains}
   - Always pick the single best main category. Do not invent compound names like "Gaming/Esports".
2. Optionally set env_subgenre to a short free-text refinement (e.g. "Esports", "Survival", "Talk show", "Live news").
   - Leave it empty string "" if there is no meaningful refinement.
3. Choose env_strictness from {{low, medium, high}}:
   - low  = Gaming, esports, casual streams (slang and aggressive gaming terms are expected).
   - high = Politics, news, medical (strict professional conduct expected).
   - medium = everything else (general chatting, music, sports commentary).

OUTPUT FORMAT:
Output ONLY a valid JSON object with exactly these three keys:
{{"env_domain": "...", "env_subgenre": "...", "env_strictness": "..."}}
"""


# ---------------------------------------------------------------------------
# Tier-2 Forensic Judge (used by xai_batch_judge and xai_judge_tool)
# ---------------------------------------------------------------------------

JUDGE_FORENSIC_RULES = """ADVANCED FORENSIC RULES:
1. Sarcasm & In-Game Events: If the domain is Gaming, analyze if the text represents in-game actions, celebrations, or sarcastic trash talk (e.g., "kill him", "you psycho"). Override DistilBERT if it is standard gameplay rhetoric.
2. Evasion & Dogwhistles: Hunt for leetspeak (e.g., "n1gg3r"), symbol replacement, or known political dogwhistles (e.g., using innocent words like "skittles" to target groups). Expose the true intent.
3. Cultural Context: Factor in regional/cultural slang. Words that are severe slurs in high-strictness US politics may be standard colloquialisms or endearments in low-strictness international gaming.
4. Instigator/Troll Detection: If DistilBERT labeled this 'Normal', but the text is highly manipulative, passive-aggressive, or clearly baiting another user into an argument, rule it a False Negative."""


def build_judge_prompt(
    raw_text: str,
    original_prediction: str,
    confidence: float,
    domain: str,
    strictness: str,
    subgenre: str = "",
) -> str:
    subgenre_line = f" | SUBGENRE: {subgenre}" if subgenre else ""
    return f"""[ROLE: XAI CONTEXT JUDGE - TRUST & SAFETY ADVISOR]
Evaluate the following prediction made by a static DistilBERT model.

TEXT TO ANALYZE: "{raw_text}"
PREDICTION: {original_prediction} (Confidence: {confidence:.2%})
DOMAIN: {domain}{subgenre_line} | STRICTNESS: {strictness}

{JUDGE_FORENSIC_RULES}

TASK:
1. Validate: Is DistilBERT's prediction Correct, a False Positive, or a False Negative?
2. Explain: Detail exactly why. You MUST reference the forensic rules above (sarcasm, evasion, culture, or instigation) if they apply to the text.

OUTPUT FORMAT: Output ONLY valid JSON: {{"decision": "...", "explanation": "..."}}
The decision MUST be exactly one of: "Correct", "False Positive", "False Negative".
"""


# ---------------------------------------------------------------------------
# Leader Agent — intent router (Phase 1) and synthesis (Phase 3)
# ---------------------------------------------------------------------------

def build_leader_router_prompt(user_input: str, db_schema_keys: list) -> str:
    return f"""You are the Orchestrator AI for a Trust & Safety Data Pipeline.
Analyze the user's request and choose the correct tool.

CRITICAL DATABASE SCHEMA: You have access to these exact columns: {db_schema_keys}

YOUR VOCABULARY & DATABASE MAPPING:
* "First AI", "Static", "DistilBERT", "hate speech", or "flagged" = map to `model_label` (Values are usually "HATE", "OFFENSIVE", or "Normal").
* "LLM", "Tier-2", "Reviewed", "Overturned", "False Positive", "False Negative", "Correct" = map to `agent_final_decision`.
* "judged by agent", "reviewed by agent", "checked by AI", "agent_review" = map to `agent_reviewed` (Values MUST be boolean: true or false).
* "time", "speed", "latency" = map to `processing_time_ms` or `agent_latency_seconds`.
* "domain", "category", "topic", "genre" = map to `env_domain` (one of: Gaming, Politics, News, Music, Sports, Education, Entertainment, Technology, Lifestyle, General).
* "subgenre", "subcategory" = map to `env_subgenre` (free-text refinement).

CRITICAL SEARCH RULES:
- ONLY use "keywords" if the user is looking for a specific chat word.
- DO NOT put label names (like "hate speech") in the "keywords" list!

You must output a JSON object using ONE of these formats:

1. For reading messages, searching history, or finding examples:
   {{"tool": "UNIVERSAL_SEARCH", "filters": {{"agent_final_decision": "False Positive"}}, "limit": 5}}

2. For counting data, statistics, breakdowns, or finding totals based on ANY condition:
   {{"tool": "GET_STATISTICS", "filters": {{"exact_schema_key": value}}}}
   - You MUST map the user's request directly to the CRITICAL DATABASE SCHEMA keys.
   - Example A: "how many entries are reviewed" -> {{"tool": "GET_STATISTICS", "filters": {{"agent_reviewed": true}}}}
   - Example B: "how many from youtube" -> {{"tool": "GET_STATISTICS", "filters": {{"source_platform": "YouTube"}}}}
   - Example C: "how many false positives" -> {{"tool": "GET_STATISTICS", "filters": {{"agent_final_decision": "False Positive"}}}}
   - Example D: "how many in gaming" -> {{"tool": "GET_STATISTICS", "filters": {{"env_domain": "Gaming"}}}}
   - For global overall stats (no filters), leave it empty: {{"tool": "GET_STATISTICS", "filters": {{}}}}

3. For investigating a SPECIFIC user or running an audit:
   {{"tool": "XAI_JUDGE", "target_user": "exact_username_here"}}

4. For weather/time/location:
   {{"tool": "GET_WEATHER"}}

5. For general conversation:
   {{"tool": "DIRECT_MESSAGE", "message": "..."}}

User Request: "{user_input}"

Respond ONLY with raw JSON. Do not include markdown formatting, backticks, or extra text.
"""


def build_leader_synthesis_prompt(user_input: str, raw_database_results: str) -> str:
    return f"""You are a Trust & Safety Analyst. The user asked: "{user_input}"

I ran a database search based on their request. Here is the exact raw data pulled from our servers:
---
{raw_database_results}
---

Read the raw data above and answer the user's original question.
CRITICAL RULE: Our database uses "Fuzzy Matching" to automatically correct human typos. If the user asks about a specific username, and the raw data returns a slightly differently spelled username, you MUST assume the user made a typo and treat the returned data as the correct match. Do not say the user is missing!

Be concise, analytical, and ground your entire response ONLY in the provided data.
"""
