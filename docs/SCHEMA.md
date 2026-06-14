# Data schema

Two schemas matter for this pipeline. They are deliberately decoupled so a new producer (Twitch, Reddit) can be added without touching the processor, and a schema change in the Tier-2 overlay does not affect Tier-1.

## 1. Universal Kafka payload (Layer 1 → Layer 3)

Every producer writes records of this shape to the Kafka topic `universal_stream`. The processor (`distilbert_processor.py`) reads them.

```json
{
  "payload_text":              "<the user's chat message>",
  "source_platform":           "YouTube",
  "env_domain":                "Gaming",
  "env_domain_raw":            "esports tournament",
  "env_domain_match":          "alias",
  "env_subgenre":              "Dota 2 Major",
  "env_strictness":            "low",
  "env_strictness_reasoning":  "Live esports tournament — banter expected.",
  "platform_metadata": {
    "video_id":      "abcDEF123",
    "video_title":   "Dota 2 — Grand Final",
    "channel_name":  "ESL Esports",
    "tweet_id":      "<platform-specific message id>",
    "author_id":     "UC...",
    "author_name":   "JohnDoe",
    "is_moderator":  false,
    "is_sponsor":    false
  }
}
```

### Field contract

| Field | Type | Required | Closed values | Notes |
|---|---|---|---|---|
| `payload_text` | string | yes | — | The actual content the Tier-1 model classifies. |
| `source_platform` | string | yes | `YouTube` (Stage 0). Future: `Twitter`, `Reddit`, `Twitch`. | |
| `env_domain` | string | yes | seed list in `config/taxonomy.yaml` (extensible) | Canonical analytics key — output of `taxonomy.normalise_domain()`. The seed is operator-extensible; new categories appear on disk, not in code. |
| `env_domain_raw` | string | yes | free text | The LLM's original proposal before normalisation. Preserved verbatim so thesis analysis can count agentic discovery beyond the seed taxonomy. |
| `env_domain_match` | string | yes | `exact` \| `alias` \| `fuzzy` \| `unknown` | How `env_domain_raw` matched the taxonomy. `unknown` flags off-seed discoveries (logged to `data/pending_taxonomy.log` by default). |
| `env_subgenre` | string | yes | free-text | May be `""`. Carries refinement (e.g. "Survival", "Esports") without polluting the canonical key. |
| `env_strictness` | string | yes | `low` \| `medium` \| `high` | LLM-reasoned per stream. Falls back to the canonical's `default_strictness` in `taxonomy.yaml` only if the LLM output is malformed. |
| `env_strictness_reasoning` | string | yes | free-text | One-sentence justification from the LLM. Kept for thesis-level explainability. |
| `platform_metadata` | object | yes | — | Nested bag of platform-specific fields. Safe to extend per platform. |

The Universal Schema's job is to guarantee the processor never crashes on a missing key. Anything unknown lives inside `platform_metadata`.

## 2. Elasticsearch document (Layer 3 → Layer 4 → Layer 5)

This is what the processor writes to the `real_time_analysis` index. Tier-2 agents overlay additional fields onto the same document later.

```json
{
  "message_id":          "ChwKGkNQ...",
  "text":                "<the message>",
  "timestamp":           "2026-06-03T11:21:36.234420",

  "source_platform":     "YouTube",
  "env_domain":          "Gaming",
  "env_subgenre":        "Esports",
  "env_strictness":      "low",
  "thread_id":           "abcDEF123",
  "thread_title":        "Dota 2 — Grand Final",
  "has_media":           false,

  "author_id":           "UC...",
  "author_name":         "JohnDoe",
  "is_moderator":        false,
  "is_sponsor":          false,

  "model_prediction":    0,
  "model_label":         "HATE",
  "model_confidence":    0.74,
  "processing_time_ms":  36.10,

  "agent_reviewed":      false,
  "agent_model_used":    null,
  "agent_final_decision":null,
  "agent_explanation":   null,
  "agent_latency_seconds": null
}
```

### Field provenance

| Block | Fields | Written by |
|---|---|---|
| Identity | `message_id`, `timestamp` | Processor |
| Source context | `source_platform`, `env_domain`, `env_domain_raw`, `env_domain_match`, `env_subgenre`, `env_strictness`, `env_strictness_reasoning`, `thread_id`, `thread_title`, `has_media` | Producer → relayed by processor |
| Author | `author_id`, `author_name`, `is_moderator`, `is_sponsor` | Producer → relayed by processor |
| Tier-1 prediction | `model_prediction`, `model_label`, `model_confidence`, `processing_time_ms` | Processor (DistilBERT) |
| Tier-2 overlay (Stage 0) | `agent_reviewed`, `agent_model_used`, `agent_final_decision`, `agent_explanation`, `agent_latency_seconds` | `xai_batch_judge.py` or `xai_judge_tool.py` |
| Tier-2 memory overlay (Stage 2) | `agent_memory_used`, `agent_memory_user_msgs`, `agent_memory_thread_msgs`, `agent_memory_user_profile` | `xai_batch_judge.py` / `xai_judge_tool.py` when `MEMORY_ENABLED`, OR `scripts/replay_with_memory.py` |
| Tier-2 replay overlay (memory-augmented) | `agent_final_decision_with_memory`, `agent_explanation_with_memory` | `scripts/replay_with_memory.py` only — never overwrites the live `agent_final_decision` |

### Closed-value fields

| Field | Allowed values |
|---|---|
| `model_label` | `HATE` \| `OFFENSIVE` \| `Normal` |
| `env_domain` | Operator-extensible seed list in `config/taxonomy.yaml` |
| `env_domain_match` | `exact` \| `alias` \| `fuzzy` \| `unknown` |
| `env_strictness` | `low` \| `medium` \| `high` |
| `agent_final_decision` | `Correct` \| `False Positive` \| `False Negative` \| `Parsing Error` |

All Kibana aggregations and the `stats_tool` rely on `env_domain` being a small, stable set of strings — but unlike a hardcoded enum, the set is **discovered + curated** rather than pre-declared. The LLM proposes freely; `taxonomy.normalise_domain()` maps proposals onto the canonical seed; off-seed proposals are surfaced in `data/pending_taxonomy.log` for operator review.

### Field type cheatsheet (post-`config/es_index_template.json`)

The new explicit mapping changes how to query each field. **Pure keyword** fields are queried bare; **text + keyword multi-field** fields use the `.keyword` suffix for exact match.

| Bucket | Fields | Query as |
|---|---|---|
| Pure `keyword` | `message_id`, `source_platform`, `env_domain`, `env_domain_match`, `env_subgenre`, `env_strictness`, `thread_id`, `author_id`, `model_label`, `agent_model_used`, `agent_final_decision`, `agent_final_decision_with_memory` | bare field name (e.g. `model_label`) |
| `text` + `keyword` multi-field | `text`, `env_domain_raw`, `thread_title`, `author_name` | `.keyword` for exact (e.g. `author_name.keyword`); base field for tokenised |
| Pure `text` (no aggregation) | `env_strictness_reasoning`, `agent_explanation`, `agent_memory_user_profile`, `agent_explanation_with_memory` | full-text search only |
| Numeric / date / boolean | `timestamp`, `model_prediction`, `model_confidence`, `processing_time_ms`, `agent_reviewed`, `agent_latency_seconds`, `agent_memory_used`, `agent_memory_user_msgs`, `agent_memory_thread_msgs`, `has_media`, `is_moderator`, `is_sponsor` | direct (`term`, `range`, `avg`, `percentiles`) |

If you write a new ES query against this index, use this table — querying `.keyword` on a pure-keyword field silently returns zero buckets (not an error), which is the bug that caused the analytics dashboard's "0 records" panels in the first runs of the new schema.

## 2a. Per-variant verdict columns

To keep variant-vs-variant comparison clean, the index uses **named slots** rather than overwriting verdicts as the pipeline evolves:

| Slot | Populated by | When |
|---|---|---|
| `agent_final_decision` | Live pipeline (`xai_batch_judge.py` / `xai_judge_tool.py`) | Always — this is the current production verdict. When `MEMORY_ENABLED=True` it carries memory-augmented verdicts for fresh ingestions. |
| `agent_final_decision_with_memory` | `scripts/replay_with_memory.py` only | Retroactively labels the pre-memory historical records with the memory-augmented verdict so the eval notebook can compare. |
| `agent_final_decision_with_rag` | `scripts/replay_with_rag.py` — leave-one-out against the benchmark CSV. | Measures the RAG contribution in isolation (no memory). Companion columns written by the same script: `agent_explanation_with_rag`, `agent_retrieved_precedent_ids` (comma-separated list of point IDs that were injected as precedents), `agent_retrieval_count`. |
| `agent_final_decision_with_memory_and_rag` | Future `scripts/replay_with_memory_and_rag.py` | Same pattern for the combined memory + RAG variant. Will be written once both Stage 2 and Stage 3 are validated and we want to measure their joint contribution. |
| `agent_final_decision_with_multi_agent` | Future `scripts/replay_with_multi_agent.py` | Same pattern when the multi-agent decomposition lands. |

The replay scripts never touch the live `agent_final_decision` slot. This guarantees the original internship baseline numbers stay reproducible forever, no matter how many variants we layer on.

## 3. Why two schemas?

The Universal Kafka payload is the producer/processor contract. The ES document is the analyst/dashboard contract. Keeping them separate means:

- Producers don't have to know about Tier-2 overlay fields (which they shouldn't).
- The Tier-2 batch judge can add new overlay fields (e.g. `agent_confidence` in Stage 5) without touching producers.
- The dashboard's field list is exactly what is in ES, never a leaked Kafka internal.

## 4. Audit CSV (`data/stream_log.csv`)

The processor also appends to a CSV for offline reproducibility. Columns:

```
timestamp, source_platform, env_domain, env_subgenre, thread_id, text, model_label, model_confidence, latency_ms
```

Tier-2 overlay fields are intentionally **not** in the CSV — the CSV captures Tier-1's raw judgement so a later auditor can re-run the Tier-2 sweep against the historical data without prior verdicts contaminating it.
