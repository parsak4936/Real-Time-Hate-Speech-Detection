# Prompts

All LLM prompts the pipeline issues are defined in **one file**: `src/shared_utils/prompts.py`. This document is the human-readable companion — it cites each prompt by the helper that builds it, explains the design intent, and links the prompt back to the report section that justifies it.

> If a prompt appears in a code file outside `src/shared_utils/prompts.py`, that is a bug — please open it and route the prompt back here. The previous version of this pipeline had the forensic-rules prompt duplicated in two places and they had already started drifting.

## 1. Context Agent prompt — `build_context_agent_prompt(...)`

**Used by:** `src/Zone1_DataHighway/adapters/context_agent.py`
**Report section:** §4.3.2 (Prompt Architecture and Output Constraints)
**Output format:** Strict JSON via Ollama `format="json"`

### What it does

Takes the scraped HTML metadata of a live stream (title, channel, description, is_live flag) and asks the LLM to classify it into three fields:

- `env_domain` — **one** main category from a closed 10-value taxonomy.
- `env_subgenre` — short free-text refinement, may be `""`.
- `env_strictness` — `low` / `medium` / `high`.

### Why a closed taxonomy

In the internship benchmark `env_domain` was open-ended and the LLM produced compound values like `Gaming/Survival`, `Gaming/Esports`, `Politics/News`. This fragmented the `env_domain.keyword` aggregation in Kibana and `stats_tool`, and made cross-stream comparison impossible. The Stage 0 cleanup pins the main category to a closed list (`ENV_DOMAINS` in the prompt module) and pushes the granularity into the new optional `env_subgenre` field. Any out-of-taxonomy LLM output is clamped to `"General"` by `resolve_environment()`.

### Closed taxonomies

```python
ENV_DOMAINS = [
    "Gaming", "Politics", "News", "Music", "Sports",
    "Education", "Entertainment", "Technology", "Lifestyle", "General",
]
ENV_STRICTNESS = ["low", "medium", "high"]
```

## 2. Forensic Judge prompt — `build_judge_prompt(...)`

**Used by:**
- `src/Zone3_Agents/xai_batch_judge.py` (async sweep)
- `src/Zone3_Agents/tools/xai_judge_tool.py` (on-demand audit)

**Report section:** §4.4 (Tier-2 Agentic Auditor)
**Output format:** Strict JSON via Ollama `format="json"`

### What it does

Asks the LLM to validate a Tier-1 DistilBERT prediction by reasoning over four forensic axes. The decision is constrained to exactly one of: `"Correct"`, `"False Positive"`, `"False Negative"`. The explanation is a free-text rationale stored alongside the decision in Elasticsearch for full auditability.

### The four forensic rules

These are the rules cited in the report, in their canonical form (see `JUDGE_FORENSIC_RULES` in `prompts.py`):

1. **Sarcasm & In-Game Events** — Override DistilBERT in Gaming contexts when the text is standard gameplay rhetoric or trash talk.
2. **Evasion & Dogwhistles** — Detect leetspeak, symbol replacement, and dogwhistles (e.g. innocent code-words used as targeting).
3. **Cultural Context** — Adjust severity based on regional/cultural slang vs high-strictness environments.
4. **Instigator/Troll Detection** — Catch False Negatives where DistilBERT labelled passive-aggressive or baiting content as `Normal`.

### Why no few-shot examples

The Stage 0 rewrite intentionally preserves the report's Table 8 (93.5%) baseline. Adding few-shot examples per domain would likely improve accuracy but would also invalidate the report's claim until Table 8 is re-run. That work is parked for Stage 1, where the evaluation harness exists and we can prove the delta.

### Determinism guarantees

The report (§4.4) states inference runs at `temperature=0.0`. In the previous code that flag was missing from every `ollama.chat` call — Ollama defaults to 0.8. The Stage 0 wrapper `ollama_chat_json` now pins `options={"temperature": 0.0}` and `format="json"` for every Tier-2 call.

## 3. Leader Agent router prompt — `build_leader_router_prompt(...)`

**Used by:** `src/Zone3_Agents/leader_agent.py` (Phase 1)
**Output format:** Strict JSON via Ollama `format="json"`

Routes the analyst's natural-language input to one of five tools:

1. `UNIVERSAL_SEARCH` — retrieve specific messages.
2. `GET_STATISTICS` — aggregate counts, breakdowns, latencies.
3. `XAI_JUDGE` — forensic audit of a single user.
4. `GET_WEATHER` — utility (location + weather + time).
5. `DIRECT_MESSAGE` — fallback chit-chat.

The router prompt includes a "vocabulary & database mapping" block that translates analyst language ("false positives", "in gaming", "checked by AI") into the exact ES field name. Without that mapping, the LLM produces filters keyed on column names that don't exist, and the tool silently returns zero rows.

## 4. Leader Agent synthesis prompt — `build_leader_synthesis_prompt(...)`

**Used by:** `src/Zone3_Agents/leader_agent.py` (Phase 3)
**Output format:** Free text (no JSON constraint)

Takes the raw tool output and the original analyst question, asks the LLM to compose a concise grounded report. The "fuzzy matching" instruction is there because `search_tool` uses ES fuzzy matching on `author_name`, so the synthesis layer must accept that a slightly-different-spelled username in the raw data is the user's typo.

## Re-running prompts after changes

Whenever you modify any of these prompts, follow the procedure in [EVAL.md](EVAL.md) to re-establish the benchmark before citing new numbers in the thesis. The prompts file is the canonical artefact the thesis defends — keep it under version control.
