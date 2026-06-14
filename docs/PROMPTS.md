# Prompts

All LLM prompts the pipeline issues are defined in **one file**: `src/shared_utils/prompts.py`. This document is the human-readable companion — it cites each prompt by the helper that builds it, explains the design intent, and links the prompt back to the report section that justifies it.

> If a prompt appears in a code file outside `src/shared_utils/prompts.py`, that is a bug — please open it and route the prompt back here. The previous version of this pipeline had the forensic-rules prompt duplicated in two places and they had already started drifting.

## 1. Context Agent prompt — `build_context_agent_prompt(...)`

**Used by:** `src/ingestion/adapters/context_agent.py`
**Report section:** §4.3.2 (Prompt Architecture and Output Constraints)
**Output format:** Strict JSON via Ollama `format="json"`

### What it does

Takes the scraped HTML metadata of a live stream (title, channel, description, is_live flag) and asks the LLM to **discover**:

- `env_domain` — what the stream is about (free text, the LLM proposes; no closed list shown to it).
- `env_subgenre` — a short refinement, free text, may be `""`.
- `env_strictness` — `low` / `medium` / `high`, reasoned from principles.
- `env_strictness_reasoning` — one-sentence justification.

### Why agentic discovery (not closed-list classification)

The initial Stage 0 implementation showed the LLM a closed 10-value taxonomy and asked it to **pick**. That turned the Context Agent into a classifier and defeated the project's stated goal of agentic moderation. The Stage 1.5 rewrite removes the menu: the LLM proposes a category in whatever words it thinks best fit the stream, and a separate normaliser (see §1.1 below) maps that proposal to a canonical analytics key.

Strictness uses the same philosophy. The prompt no longer says *"low = Gaming, high = Politics"*; it describes the principles ("low = casual entertainment context", "high = serious or professional setting") and lets the LLM reason from the metadata. The principles do not name any specific domain.

### 1.1 Taxonomy normalisation (downstream, not in prompt)

After the LLM responds, `shared_utils/taxonomy.py::normalise_domain()` maps the free-text proposal onto a canonical entry from `config/taxonomy.yaml`. Four match qualities are recorded on the ES doc:

| `env_domain_match` | What it means |
|---|---|
| `exact` | The LLM's proposal matched a canonical name letter-for-letter. |
| `alias` | It matched a known alias of a canonical (e.g. "esports" → Gaming). |
| `fuzzy` | A `SequenceMatcher` ratio ≥ `fuzzy_match_threshold` matched a canonical or alias. |
| `unknown` | No canonical was close enough. The `unknown_policy.action` in the YAML decides what happens (default: `accept_and_log` — keep the proposal, write to `data/pending_taxonomy.log` for later promotion). |

The LLM's raw proposal is preserved verbatim in `env_domain_raw` on every ES doc. The canonical name is in `env_domain`. Analytics aggregations key on `env_domain.keyword` so they stay stable across thousands of records.

### 1.2 Extending the taxonomy

Operators edit `config/taxonomy.yaml` — no code change. Append an entry to `canonical:` with optional `aliases` and `default_strictness`. Restart any running producer to pick up the change. To analyse which categories the LLM keeps proposing that you have not yet canonicalised, read `data/pending_taxonomy.log`.

## 2. Forensic Judge prompt — `build_judge_prompt(...)` and `build_judge_prompt_with_memory(...)`

**Used by:**
- `src/agents/xai_batch_judge.py` (async sweep) — picks the memory variant when `MEMORY_ENABLED`.
- `src/agents/tools/xai_judge_tool.py` (on-demand audit) — same.
- `scripts/replay_with_memory.py` — always uses the memory variant (it exists to populate the v2 verdicts).

**Report section:** §4.4 (Tier-2 Agentic Auditor)
**Output format:** Strict JSON via Ollama `format="json"`

### Variants

| Variant | When used | Extra context |
|---|---|---|
| `build_judge_prompt` | Baseline. Used when `MEMORY_ENABLED=False` and `RAG_ENABLED=False`. | None — message judged in isolation. |
| `build_judge_prompt_with_memory` | When `MEMORY_ENABLED=True` and `RAG_ENABLED=False` (default live config after Stage 2). | Three injected blocks: USER BEHAVIOR FINGERPRINT, RECENT USER HISTORY, THREAD CONTEXT. |
| `build_judge_prompt_with_rag` | RAG only, no memory. Used by `scripts/replay_with_rag.py` for clean Stage 3 isolation (measuring the RAG contribution alone). | One injected block: RETRIEVED PRECEDENTS (top-k semantically similar past cases, with their model_label, env_domain, and Tier-2 baseline verdict — **human_ground_truth is deliberately omitted from the payload to prevent label leakage**). |
| `build_judge_prompt_with_memory_and_rag` | When both `MEMORY_ENABLED=True` and `RAG_ENABLED=True` (full memory + retrieval). Wired into agents when both flags are flipped. | All three memory blocks AND the RETRIEVED PRECEDENTS block. |

All four prompts share the same four forensic rules. Each step up the ladder adds contextual rules:

- **Memory variant** adds rules 5–7: **Behavioral Pattern**, **Conversational Continuity**, **Memory is Evidence Not Verdict**.
- **RAG variant** adds rules 5–6: **Precedent Reasoning** + **Precedents Are Evidence Not Verdict**.
- **Memory + RAG variant** combines both rule sets (5–8).

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

**Used by:** `src/agents/leader_agent.py` (Phase 1)
**Output format:** Strict JSON via Ollama `format="json"`

Routes the analyst's natural-language input to one of five tools:

1. `UNIVERSAL_SEARCH` — retrieve specific messages.
2. `GET_STATISTICS` — aggregate counts, breakdowns, latencies.
3. `XAI_JUDGE` — forensic audit of a single user.
4. `GET_WEATHER` — utility (location + weather + time).
5. `DIRECT_MESSAGE` — fallback chit-chat.

The router prompt includes a "vocabulary & database mapping" block that translates analyst language ("false positives", "in gaming", "checked by AI") into the exact ES field name. Without that mapping, the LLM produces filters keyed on column names that don't exist, and the tool silently returns zero rows.

## 4. Leader Agent synthesis prompt — `build_leader_synthesis_prompt(...)`

**Used by:** `src/agents/leader_agent.py` (Phase 3)
**Output format:** Free text (no JSON constraint)

Takes the raw tool output and the original analyst question, asks the LLM to compose a concise grounded report. The "fuzzy matching" instruction is there because `search_tool` uses ES fuzzy matching on `author_name`, so the synthesis layer must accept that a slightly-different-spelled username in the raw data is the user's typo.

## Re-running prompts after changes

Whenever you modify any of these prompts, follow the procedure in [EVAL.md](EVAL.md) to re-establish the benchmark before citing new numbers in the thesis. The prompts file is the canonical artefact the thesis defends — keep it under version control.
