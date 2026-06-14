# Audit guide — per-file checklist

A reviewer's companion. For every important file: **what it does**, **what to check**, **what changes propagate where**, **how to spot if it broke**. Use this when you (or your supervisor, or a thesis examiner) want to convince yourself a specific file is correct.

Pair with [`CODEBASE_TOUR.md`](CODEBASE_TOUR.md) (for reading order) and [`GLOSSARY.md`](GLOSSARY.md) (for terminology).

---

## How to use this file

For each file the audit gives four things:

1. **Purpose** — one paragraph.
2. **What to check** — a numbered checklist you can tick off.
3. **Change propagation** — "if you change line X, also check files Y and Z".
4. **How to verify it broke** — the symptom you'd see, without needing to write a test.

---

## `src/shared_utils/config.py`

**Purpose.** Loads `.env`, exposes every infrastructure connection string and feature flag as a Python constant. Imported by literally every other file.

**What to check.**
1. `ES_HOST`, `KAFKA_BROKERS`, `KAFKA_TOPICS`, `INDEX_NAME` match the values in `docker-compose.yml`.
2. `OLLAMA_MODEL` and `ACTIVE_MODEL` agree.
3. The Stage 2 knobs (`MEMORY_ENABLED`, `MEMORY_USER_WINDOW_SIZE`, `MEMORY_THREAD_WINDOW_SIZE`, `MEMORY_LOOKBACK_HOURS`, `MEMORY_FINGERPRINT_WINDOW`) all parse as the right types (bool, int).
4. The Stage 3 knobs (`RAG_ENABLED`, `QDRANT_HOST`, `QDRANT_PORT`, `QDRANT_COLLECTION`) are present.
5. No literal secrets in the file — they should come from `.env` (which is in `.gitignore`).

**Change propagation.** Adding a new knob requires updating one or more of:
- `docs/SCHEMA.md` if it adds an ES field.
- `docs/RUNBOOK.md` if it changes how to run a script.
- The relevant shared util (`memory.py`, `rag.py`, etc.) that consumes the knob.

**How to verify it broke.** `ImportError` from any other module on first import, or `KeyError` when a downstream consumer asks for a missing constant.

---

## `src/shared_utils/prompts.py`

**Purpose.** Single source of truth for every LLM prompt. If a prompt string appears anywhere else in the project, that is a bug.

**What to check.**
1. Four judge variants present: `build_judge_prompt`, `build_judge_prompt_with_memory`, `build_judge_prompt_with_rag`, `build_judge_prompt_with_memory_and_rag`.
2. Each variant's docstring explains when it's used and what it expects.
3. The forensic rules (`JUDGE_FORENSIC_RULES`) are defined once at the top and reused by every variant via interpolation.
4. The context agent prompt (`build_context_agent_prompt`) does NOT show the LLM a closed list of domains. The taxonomy is mentioned in the docstring as "see `taxonomy.py`" but not shown to the model.
5. The leader router prompt (`build_leader_router_prompt`) maps analyst vocabulary onto ES field names correctly.

**Change propagation.** Adding a new prompt or modifying an existing one:
- Update [`docs/PROMPTS.md`](PROMPTS.md) to document the change.
- Re-run `replay_with_memory.py` (or whichever replay script applies) before citing any new accuracy numbers.
- The internship report's 93.5% number is bound to the original prompt — re-measure before claiming new figures.

**How to verify it broke.** The LLM starts returning `Parsing Error` verdicts at >5% rate, or the leader agent picks the wrong tool for an obvious analyst query.

---

## `src/shared_utils/llm.py`

**Purpose.** Thin wrapper around `ollama.chat`. Pins `temperature=0`, sets `format="json"`, retries once on parse failure with the parser error appended as a follow-up message.

**What to check.**
1. `ollama_chat_json` returns a `dict` on success and `None` on repeated parse failure (no exceptions thrown).
2. `ollama_chat_text` does not force JSON mode (used for free-form synthesis).
3. Both functions read `model` from `shared_utils.config.ACTIVE_MODEL` by default but accept an override.

**Change propagation.** Swapping the model (changing `OLLAMA_MODEL` in `.env`) invalidates every measured accuracy number in the eval notebook.

**How to verify it broke.** Every judge call returns `Parsing Error` (the model output isn't JSON) — usually means `format="json"` was removed.

---

## `src/shared_utils/taxonomy.py`

**Purpose.** Loads `config/taxonomy.yaml` once, exposes `normalise_domain(raw)` and `default_strictness_for(canonical)`. Maps free-text LLM proposals to canonical seeds via four passes (exact → alias → fuzzy → unknown policy).

**What to check.**
1. The fuzzy threshold (`fuzzy_match_threshold` in YAML, default 0.75) is sensible — too low and unrelated proposals match; too high and obvious aliases miss.
2. `unknown_policy.action` is either `accept_and_log` or `clamp_to_general`. Default is `accept_and_log`.
3. Unknown proposals get written to `data/pending_taxonomy.log` (not lost silently).
4. The module is thread-safe (a `_LOCK` is held when populating `_CACHED_TAXONOMY`).
5. `reload_taxonomy()` exists so a long-running process can pick up YAML edits without restart.

**Change propagation.** Editing `config/taxonomy.yaml`:
- Adding canonical entries: no other file needs changes.
- Renaming an existing canonical: must update the Kibana dashboard and any cached references.
- Lowering `fuzzy_match_threshold` drastically: re-test with the smoke-test snippet in [`STATUS.md`](STATUS.md).

**How to verify it broke.** Every LLM-proposed domain returns `[unknown]` match quality — usually means `_CACHED_TAXONOMY` failed to load.

---

## `src/shared_utils/memory.py`

**Purpose.** Pulls per-user and per-thread history from Elasticsearch. Returns prompt-ready strings (not raw ES hits) for direct injection into the memory-augmented judge prompt.

**What to check.**
1. The user-history query filters by `author_id.keyword` (exact match), `timestamp` ≥ cutoff, optionally `< before_timestamp`.
2. The thread-context query filters by `thread_id.keyword` (exact match).
3. Both queries support `exclude_message_id` so the current record never appears in its own context.
4. `get_user_behavior_fingerprint` produces a single line in the format `"Last N msgs: X Normal / Y OFFENSIVE / Z HATE. Most recent flagged: T ago."`.
5. `fetch_memory_bundle` returns a dict with both formatted strings AND raw counts (for writing `agent_memory_user_msgs` etc. to ES).

**Change propagation.** Changing the user-history window (`MEMORY_USER_WINDOW_SIZE`) changes how much context the LLM gets — re-measure before citing accuracy.

**How to verify it broke.** All judge calls log `(no prior history available)` for users you know have history. Likely cause: `author_id.keyword` field doesn't exist on the ES doc (schema drift).

---

## `src/shared_utils/rag.py`

**Purpose.** Qdrant client + sentence-transformers embedder. Public API: `index_record`, `index_records_bulk`, `retrieve_similar`, `format_precedents_for_prompt`, `fetch_retrieval_bundle`. All lazy-loaded so `import shared_utils.rag` is cheap.

**What to check.**
1. Embedder is lazy-loaded (no model download on import).
2. Qdrant client auto-creates the collection if missing, with cosine distance and the right dim.
3. Point IDs are derived from `message_id` via blake2b hash → unsigned int64 (Qdrant constraint). Idempotent.
4. `retrieve_similar` over-fetches by 1 when `exclude_self=True` so the count after self-exclusion still equals `k`.
5. Payload includes `agent_final_decision` but NOT `human_ground_truth` — leakage prevention.
6. `format_precedents_for_prompt` produces one line per precedent with score, static label, agent verdict, human label (only when caller chose to include it), domain, truncated text.

**Change propagation.** Changing the embedding model name in `config/rag.yaml`:
- Update the `dim` field to match the new model.
- Recompute the Qdrant collection (it's keyed by the old dim).
- Re-run `seed_rag_from_csv.py --apply` to repopulate.

**How to verify it broke.** `retrieve_similar` returns an empty list for queries you know should match. Likely causes: collection doesn't exist; embedding dim mismatch; cosine threshold too high.

---

## `src/ingestion/adapters/youtube_adapter.py`

**Purpose.** Scrapes the YouTube watch-page HTML, calls the Context Agent, opens `pytchat`, formats each chat message into the Universal Schema, pushes to Kafka.

**What to check.**
1. `extract_video_id` handles both `youtube.com/watch?v=...` and `youtu.be/...` URL forms.
2. `fetch_youtube_metadata` returns a dict with `title`, `channel_name`, `description`, `is_live`. Failures degrade gracefully (no crash).
3. The script blocks streams that aren't `is_live=True`.
4. The Universal Schema payload includes every Stage 0.5 field (`env_domain`, `env_domain_raw`, `env_domain_match`, `env_subgenre`, `env_strictness`, `env_strictness_reasoning`).
5. `KafkaProducer` flushes on every send (no buffered loss).

**Change propagation.** Adding a field to the Universal Schema:
- Update [`docs/SCHEMA.md`](SCHEMA.md).
- Update `distilbert_processor.py` to read the new field and write it to ES.
- Update any new adapter you write (Reddit, Twitch) to produce the same field.

**How to verify it broke.** The producer prints `[BLOCKED]` for streams that ARE live → `'isLiveNow':true` no longer appears in YouTube HTML; need a new heuristic.

---

## `src/ingestion/adapters/context_agent.py`

**Purpose.** The agentic discovery layer. Wraps the Context Agent LLM call + taxonomy normalisation. Returns a rich dict with both the normalised canonical key and the raw LLM proposal.

**What to check.**
1. Calls `build_context_agent_prompt(source_platform, raw_meta)` (no closed-list shown to LLM).
2. Returns dict with: `env_domain` (canonical), `env_domain_raw` (LLM verbatim), `env_domain_match` (exact / alias / fuzzy / unknown), `env_subgenre`, `env_strictness`, `env_strictness_reasoning`.
3. Strictness validation: LLM output is checked against `{low, medium, high}` set; falls back to `default_strictness_for(canonical_domain)` if malformed.
4. `_fallback_env()` is called when the LLM call returns `None` (parse failure) — pipeline never blocks ingestion.

**Change propagation.** Changing the return shape breaks `youtube_adapter.py` (and `distilbert_processor.py` if you forget to update it).

**How to verify it broke.** `youtube_adapter.py` crashes with `KeyError: 'env_domain_raw'` — the Context Agent returned a dict missing the rich fields.

---

## `src/static_classifier/distilbert_processor.py`

**Purpose.** Long-running Kafka consumer. Loads DistilBERT, classifies each Kafka message, writes an ES document. Also appends to `data/stream_log.csv` for offline reproducibility.

**What to check.**
1. Loads tokenizer + model from `models/bert_final/` (NOT from HuggingFace — that would be a fresh untrained model).
2. `get_bert_prediction` returns `(label_id, label_text, probabilities, calc_time_ms)`. The label map is `{0: HATE, 1: OFFENSIVE, 2: Normal}` — DO NOT reorder; it's tied to the trained weights.
3. ES doc includes every Universal Schema field, every Tier-1 prediction field, and `agent_*` fields initialised to `None`/`False` (Tier-2 will overlay later).
4. Audit CSV append never fails (the Kafka consumer must keep draining).

**Change propagation.** Adding new Tier-1 output fields (e.g. softmax probabilities per class):
- Update [`docs/SCHEMA.md`](SCHEMA.md).
- Update `src/export_subset.py` to include them.
- Update Kibana dashboard if you want them charted.

**How to verify it broke.** `BERT Model Loaded successfully.` doesn't print on start → `models/bert_final/` is missing or corrupted; redownload.

---

## `src/agents/xai_batch_judge.py`

**Purpose.** Async sweep of low-confidence ES records. Picks unreviewed records with `model_confidence < TARGET_CONFIDENCE_BELOW`, optionally fetches memory, calls the LLM, writes verdict back.

**What to check.**
1. Master control panel constants at the top (`BATCH_SIZE`, `TARGET_CONFIDENCE_BELOW`, `UPDATE_DATABASE`) are sensibly defaulted.
2. ES query: `must_not` clause excludes already-reviewed records; `must` clause has the confidence filter.
3. When `MEMORY_ENABLED`: calls `fetch_memory_bundle`, passes the strings to `build_judge_prompt_with_memory`. When `MEMORY_ENABLED=False`: calls `build_judge_prompt` directly.
4. Writes `agent_memory_used`, `agent_memory_user_msgs`, `agent_memory_thread_msgs`, `agent_memory_user_profile` to ES (even when False, for explicit "we ran without memory" auditability).
5. `time.sleep(2)` between records — rate-limits Ollama.

**Change propagation.** Changing the confidence threshold changes what gets audited. Lowering it dramatically (e.g. to 1.01) makes the sweep cover every record — useful for one-off re-runs but slow.

**How to verify it broke.** `Found 0 records to audit` even when ES has unreviewed records — likely cause: the `model_confidence` field type is string not float (schema drift); or no records exist below the threshold.

---

## `src/agents/tools/xai_judge_tool.py`

**Purpose.** Single-record version of the batch judge, invoked by the Leader Agent when an analyst asks to audit a specific user.

**What to check.**
Same as `xai_batch_judge.py`. The key difference: it queries ES by `author_name` (fuzzy match), picks the most recent message, and judges that one record only.

**How to verify it broke.** Leader Agent reports `XAI Tool Failure: ...` — usually an ES field name typo or Ollama unreachable.

---

## `src/agents/tools/search_tool.py`

**Purpose.** ES search tool for the Leader Agent. Translates analyst filter dicts (e.g. `{"agent_final_decision": "False Positive"}`) into ES query clauses.

**What to check.**
1. **String filters use `term` on `.keyword` subfields, NOT `match`.** (Critical: `match` tokenises "False Positive" into "false" OR "positive", inflating counts.)
2. Bool filters use `term`.
3. `keywords` parameter uses tokenised `match` on `text` (intentional — chat-keyword search).
4. `author_name` parameter uses fuzzy match (typo tolerance).
5. Default sort is newest-first.

**Change propagation.** If you add a new ES field that the analyst can filter on, update the leader router prompt (`docs/PROMPTS.md` §3) so the LLM knows about it.

**How to verify it broke.** Analyst asks "how many false positives?" and the count is wildly inflated → `match` slipped back in instead of `term`.

---

## `src/agents/tools/stats_tool.py`

**Purpose.** ES aggregation tool. Counts, breakdowns by `source_platform.keyword` / `env_domain.keyword` / `model_label.keyword` / `agent_final_decision.keyword`, average latencies.

**What to check.** Same `term` vs `match` rule as `search_tool.py`. The same code duplication bug from Stage 0 is gone.

---

## `src/agents/leader_agent.py`

**Purpose.** Natural-language analyst console. Three phases: route (LLM picks a tool), execute (tool runs), synthesise (LLM summarises raw tool output for the analyst).

**What to check.**
1. `get_database_schema` introspects ES at boot to inform the router prompt of the live field set.
2. Tool registry is a Python dict mapping the LLM's chosen tool name to the function to call.
3. `leader_router` handles the `None` return from `ollama_chat_json` gracefully (no crash; prints `Routing Error`).
4. The `XAI_JUDGE` tool requires `target_user` — verify the router prompt teaches the LLM this.

**Change propagation.** Adding a new tool:
1. Write the tool function in `src/agents/tools/`.
2. Add it to `TOOL_REGISTRY` in `leader_agent.py`.
3. Add a JSON schema example to `build_leader_router_prompt` in `prompts.py`.
4. Document in `docs/PROMPTS.md` §3.

**How to verify it broke.** Analyst's queries always return `The AI hallucinated a tool. 'XXX' is not in the registry.` — the router LLM is inventing tool names not in the prompt.

---

## `scripts/seed_rag_from_csv.py`

**Purpose.** Reads a benchmark CSV, embeds each row's text, upserts into Qdrant. Used for Stage 3 evaluation without live ES.

**What to check.**
1. Payload does NOT include `human_ground_truth` (leakage prevention).
2. Synthesises `csv-row-N` IDs when the CSV has no `message_id` column.
3. Dry-run default (`--apply` to actually write).
4. Idempotent (re-upsert by stable hash of message_id).

---

## `scripts/replay_with_rag.py`

**Purpose.** Leave-one-out RAG evaluation on a CSV.

**What to check.**
1. For each row, calls `fetch_retrieval_bundle(query_text=text, exclude_message_id=...)` — passes the synthesised csv-row-N ID for exclusion.
2. Writes `agent_final_decision_with_rag`, `agent_explanation_with_rag`, `agent_retrieved_precedent_ids`, `agent_retrieval_count` to the CSV.
3. Idempotent: rows with non-empty `agent_final_decision_with_rag` are skipped unless `--force`.
4. Defaults to overwriting the input CSV; pass `--output other.csv` to preserve original.

---

## `scripts/replay_with_memory.py`

**Purpose.** Re-judges already-reviewed ES records with memory-augmented prompt; writes to `agent_final_decision_with_memory`.

**What to check.**
1. Reads from ES via scan API (not pandas → DataFrame).
2. Writes only `_with_memory` fields — NEVER overwrites `agent_final_decision`.
3. `--csv` flag filters to only the records matching the CSV's `message_id` column (exact ID match).
4. Sleep between LLM calls (rate-limit).

---

## `notebooks/evaluation.ipynb`

**Purpose.** Living evaluation. Reproduces the report's 93.5%; adds sections as new pipeline variants land.

**What to check.**
1. §1 (Baseline) numbers match the report exactly: 71.0% / 93.5% / 68.4% / 67.1% / 26.4%.
2. Latency (§1.7): 36.10 ms / 6951.81 ms / 192.6× match the report.
3. §4 (Memory) and §5 (RAG) print "skip" messages when the relevant `_with_memory` / `_with_rag` columns are missing — they don't crash.
4. §7 (Cross-pipeline comparison) renders the `RESULTS_REGISTRY` regardless of how many variants have landed.

**Regenerating.** Run `python scripts/_build_eval_notebook.py` to recreate the notebook from the build script. Use this for structural changes; inline edits in Jupyter for one-off tweaks.

**How to verify it broke.** §1.4 reports a number other than 93.5% for the Agent accuracy — either the CSV is wrong or the `agent_effective_label` function changed.

---

## `config/taxonomy.yaml`

**What to check.**
1. Every canonical entry has at least `name` and `default_strictness`.
2. Aliases are case-insensitive (normaliser lowercases on comparison).
3. `fuzzy_match_threshold` between 0 and 1.
4. `unknown_policy.action` is `accept_and_log` or `clamp_to_general`.
5. `log_path` is relative to the project root (e.g. `data/pending_taxonomy.log`).

---

## `config/rag.yaml`

**What to check.**
1. `qdrant.collection` matches `QDRANT_COLLECTION` in `config.py`.
2. `embedding.dim` matches the actual output dim of `embedding.model_name`. Mismatch = Qdrant rejects every upsert.
3. `retrieval.top_k` ≥ 1 and ≤ 20 (more is wasteful, less is too few precedents).
4. `retrieval.similarity_threshold` between 0 and 1. Below 0.5 returns lots of noise; above 0.85 returns almost nothing.

---

## `docker-compose.yml`

**What to check.**
1. All 6 services declared (zookeeper, kafka, elasticsearch, kibana, spark-master, spark-worker, qdrant).
2. `bigdata-net` network is shared by all.
3. Persistent volumes for: `es_data`, `kafka_data`, `spark_meta`, `qdrant_data`.
4. Healthchecks where applicable (zookeeper, kafka, elasticsearch).
5. Kafka external listener is `localhost:9093` so host scripts can reach it.

---

## Common "did I break the schema?" checklist

When you've changed something and want a quick sanity sweep:

```bash
# 1. Every Python file still compiles:
python -m py_compile $(find src scripts -name "*.py")

# 2. Notebook still generates from the build script:
python scripts/_build_eval_notebook.py

# 3. Taxonomy smoke-test:
python -c "
import sys; sys.path.insert(0, 'src')
import shared_utils.taxonomy as t
t._CACHED_TAXONOMY = None
print('Canonicals:', len(t.canonical_names()))
for raw in ['gaming', 'esports', 'amazon', 'tweet']:
    r = t.normalise_domain(raw)
    print(f'  {raw} -> {r[\"canonical\"]} [{r[\"match_quality\"]}]')
"

# 4. Inspect the ES doc shape (needs ES running):
python src/agents/check_db_size.py
```

If all four pass, you have not broken anything structural. Behaviour (model output, accuracy) requires the eval notebook to verify.
