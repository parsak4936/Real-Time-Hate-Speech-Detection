# Codebase tour — a sequenced reading path

If you sit down to study the project from zero (or come back after a break), read the files in this order. Each tier builds on the previous one. Total time to read everything: **3-4 hours of focused study**.

Use this together with [`GLOSSARY.md`](GLOSSARY.md) (concepts) and [`AUDIT_GUIDE.md`](AUDIT_GUIDE.md) (per-file checklist).

---

## Tier 0 — Read this first to orient yourself (30 min)

1. **[`Internship_report_Draft_1 (1).pdf`](../Internship_report_Draft_1%20(1).pdf)** — the original scientific framing. §1 Introduction, §3 Architecture, §4 Multi-Tiered AI Architecture, §6 Results.
2. **[`README.md`](../README.md)** — entry point. Repository structure, setup, run commands.
3. **[`STATUS.md`](STATUS.md)** — current state. Tells you what's built, what's pending, whether to commit.
4. **[`ROADMAP.md`](ROADMAP.md)** — the 8-stage plan (Stage 0 → Stage 7), planning lens only.

You now know: what the project is, what's done, what's planned.

---

## Tier 1 — Architecture and data shape (45 min)

5. **[`ARCHITECTURE.md`](ARCHITECTURE.md)** — 5-layer figure mapped to folders. Process boundaries (which Python file is which process). Mermaid flow diagram.
6. **[`SCHEMA.md`](SCHEMA.md)** — every field that flows through Kafka and lives in Elasticsearch. The Universal Schema (producer contract) vs the ES document schema (analyst contract). Per-pipeline-variant verdict columns.
7. **[`GLOSSARY.md`](GLOSSARY.md)** — every tool and concept in plain language with alternatives and citations.

You now know: how data flows, what shape it takes at each stop, and what each component is.

---

## Tier 2 — Configuration and shared utilities (30 min)

These are the foundations every other file depends on. Read them before any agent code.

8. **`src/shared_utils/config.py`** — every environment-driven knob (ES host, Kafka brokers, Ollama model, memory window, RAG settings). Loaded once at process start.
9. **`src/shared_utils/prompts.py`** — every LLM prompt the project ever issues. Single source of truth. Four judge variants (baseline, with_memory, with_rag, with_memory_and_rag) plus the context-agent prompt plus the leader-agent router.
10. **`src/shared_utils/llm.py`** — thin Ollama wrapper. `ollama_chat_json()` pins temperature=0, format=json, retries once on parse failure. Used by every agent.
11. **`config/taxonomy.yaml`** — domain seed list (16 canonicals + aliases + default strictness). Read before reading `taxonomy.py`.
12. **`src/shared_utils/taxonomy.py`** — LLM proposal → canonical normaliser. Four-pass match (exact → alias → fuzzy → unknown policy).
13. **`src/shared_utils/memory.py`** — Elasticsearch retrieval for user history, thread context, behavioural fingerprint. No LLM calls.
14. **`config/rag.yaml`** — embedding model + retrieval knobs.
15. **`src/shared_utils/rag.py`** — Qdrant client + sentence-transformers embedder. Mirrors `memory.py` API surface.

You now know: every helper an agent might call.

---

## Tier 3 — Layer 1: ingestion (30 min)

16. **`src/ingestion/omni_ingest.py`** — entry point. Asks for a URL, routes to the right adapter. Currently YouTube-only.
17. **`src/ingestion/adapters/youtube_adapter.py`** — scrapes YouTube watch-page HTML, calls Context Agent, opens `pytchat` live-chat connection, pushes Universal Schema messages to Kafka.
18. **`src/ingestion/adapters/context_agent.py`** — the agentic discovery layer. Calls the LLM with `build_context_agent_prompt`, normalises the result via `taxonomy.py`. Returns the rich env dict that flows into Kafka.

You now know: how a YouTube chat message becomes a Kafka record with `env_domain`, `env_subgenre`, `env_strictness`.

---

## Tier 4 — Layer 3: Tier-1 static classifier (30 min)

19. **`src/static_classifier/distilbert_processor.py`** — long-running Kafka consumer. Loads DistilBERT from `models/bert_final/`, classifies each message, writes a verdict + all Universal Schema fields to Elasticsearch.
20. **`src/Hate_speach_Project.ipynb`** — the training notebook. **Don't run** (hours-long GPU job); read for methodology only. Hyperparameters, class balancing, evaluation metrics from the internship phase.

You now know: how a Kafka record becomes an Elasticsearch document with `model_label` + `model_confidence`.

---

## Tier 5 — Layer 5: Tier-2 agents (45 min)

21. **`src/agents/xai_batch_judge.py`** — the async sweep. Queries ES for low-confidence unreviewed records, optionally calls `memory.fetch_memory_bundle`, calls the LLM via `llm.ollama_chat_json`, writes `agent_*` fields back to ES.
22. **`src/agents/tools/xai_judge_tool.py`** — single-record version used by the Leader Agent. Same logic as the batch judge.
23. **`src/agents/tools/search_tool.py`** — Elasticsearch search tool for the Leader Agent. Term-exact filtering on `.keyword` subfields; fuzzy match on `author_name`.
24. **`src/agents/tools/stats_tool.py`** — Elasticsearch aggregation tool. Counts, breakdowns, latency averages.
25. **`src/agents/tools/weather_tool.py`** — external API tool (Open-Meteo). Demonstrates the tool-registry pattern.
26. **`src/agents/leader_agent.py`** — the orchestrator. Two-phase: (1) router LLM call decides which tool to invoke from analyst input; (2) tool runs; (3) synthesis LLM call summarises the raw tool output for the analyst.

You now know: how Tier-2 reviews Tier-1's decisions, and how the analyst interrogates the pipeline through natural language.

---

## Tier 6 — Evaluation (30 min)

27. **[`EVAL.md`](EVAL.md)** — how the 93.5% from the report was produced; how to reproduce it.
28. **[`RUNBOOK.md`](RUNBOOK.md)** — two paths (A: Stage 3 RAG without labels; B: Stage 2 memory with labels).
29. **`notebooks/evaluation.ipynb`** — living evaluation notebook. §1 baseline reproduces the report; §4 measures temporal memory; §5 measures RAG; §7 cross-pipeline comparison.
30. **`scripts/_build_eval_notebook.py`** — the generator that produces `evaluation.ipynb`. Used only when restructuring the notebook.

You now know: how to evaluate every variant, run the existing benchmark, and compare across stages.

---

## Tier 7 — Operational scripts (20 min)

31. **`scripts/normalize_domains.py`** — taxonomy backfill for old open-taxonomy ES records.
32. **`scripts/seed_rag_from_csv.py`** — push the internship benchmark CSV into Qdrant.
33. **`scripts/build_rag_index.py`** — push live ES records into Qdrant.
34. **`scripts/replay_with_memory.py`** — re-judge reviewed ES records with memory injected.
35. **`scripts/replay_with_rag.py`** — leave-one-out RAG evaluation on the CSV.
36. **`src/export_subset.py`** — pull reviewed records out of ES into a benchmark CSV (with `message_id` + `timestamp` for replay matching).
37. **`src/reset_db.py`** — destructive index wipe (requires `--yes`).

You now know: every standalone command and what it does.

---

## Tier 8 — Documentation and prompts in detail (60 min)

38. **[`PROMPTS.md`](PROMPTS.md)** — full text and design rationale for every LLM prompt. Read this when you want to understand *why* a prompt is shaped the way it is.
39. **[`MONITORING.md`](MONITORING.md)** — how to verify each component is doing what it should.
40. **[`AUDIT_GUIDE.md`](AUDIT_GUIDE.md)** — per-file audit notes for when you modify something.

---

## Suggested reading sessions

If you only have an afternoon:

| Time | Read |
|---|---|
| First hour | Tier 0 + Tier 1 (orientation + architecture) |
| Second hour | Tier 2 (shared utilities — config, prompts, llm, memory, rag) |
| Third hour | Pick ONE of: Tier 3 (ingestion) OR Tier 5 (agents). Trace one example record end-to-end. |

If you have a full day:

Read all eight tiers in order. At each tier, write down questions; they're often answered in the next tier.

If you're prepping for the thesis defence:

Focus on Tier 0, Tier 1, GLOSSARY, and PROMPTS. The examiner will ask about *concepts and design choices*, not Python syntax.

---

## Key dependency graph

```
config.py
  ↓
prompts.py ──→ llm.py ──→ memory.py
                          │
                          ↓
                        rag.py ←── taxonomy.py
                          │            │
                          ↓            ↓
                    agents/*.py     ingestion/adapters/context_agent.py
                          │            │
                          ↓            ↓
                  Elasticsearch     Kafka → distilbert_processor.py → Elasticsearch
```

Read top-to-bottom following arrows. The agents are the consumers; everything else is plumbing.

---

## One-line summaries (cheat-sheet)

| File | One sentence |
|---|---|
| `src/shared_utils/config.py` | Reads env vars; everyone imports from here. |
| `src/shared_utils/prompts.py` | All LLM prompts. Single source of truth. |
| `src/shared_utils/llm.py` | `ollama_chat_json` — temp=0, format=json, 1 retry. |
| `src/shared_utils/taxonomy.py` | Maps free-text LLM domain proposals to canonical seeds. |
| `src/shared_utils/memory.py` | Pulls user history + thread context out of ES. |
| `src/shared_utils/rag.py` | Pushes vectors to Qdrant, retrieves k nearest. |
| `src/ingestion/omni_ingest.py` | "Paste a URL", routes to adapter. |
| `src/ingestion/adapters/youtube_adapter.py` | YouTube scraper + chat producer. |
| `src/ingestion/adapters/context_agent.py` | LLM discovers env_domain; normalises via taxonomy. |
| `src/static_classifier/distilbert_processor.py` | Kafka → DistilBERT → ES. |
| `src/agents/xai_batch_judge.py` | Async sweep of low-confidence ES records. |
| `src/agents/leader_agent.py` | Natural-language analyst console. |
| `src/agents/tools/*.py` | Tools the leader can invoke. |
| `scripts/*.py` | One-off utilities — replay, backfill, bootstrap. |
| `notebooks/evaluation.ipynb` | Living per-variant evaluation. |
