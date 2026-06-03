# Data schema

Two schemas matter for this pipeline. They are deliberately decoupled so a new producer (Twitch, Reddit) can be added without touching the processor, and a schema change in the Tier-2 overlay does not affect Tier-1.

## 1. Universal Kafka payload (Layer 1 → Layer 3)

Every producer writes records of this shape to the Kafka topic `universal_stream`. The processor (`distilbert_processor.py`) reads them.

```json
{
  "payload_text":     "<the user's chat message>",
  "source_platform":  "YouTube",
  "env_domain":       "Gaming",
  "env_subgenre":     "Esports",
  "env_strictness":   "low",
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
| `env_domain` | string | yes | **Closed** — see `ENV_DOMAINS` in `src/shared_utils/prompts.py` | One of: Gaming, Politics, News, Music, Sports, Education, Entertainment, Technology, Lifestyle, General. |
| `env_subgenre` | string | yes | free-text | May be `""`. Carries the refinement that used to bloat `env_domain` (e.g. "Survival", "Esports"). |
| `env_strictness` | string | yes | `low` \| `medium` \| `high` | Drives the Tier-2 judge's leniency. |
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
| Source context | `source_platform`, `env_domain`, `env_subgenre`, `env_strictness`, `thread_id`, `thread_title`, `has_media` | Producer → relayed by processor |
| Author | `author_id`, `author_name`, `is_moderator`, `is_sponsor` | Producer → relayed by processor |
| Tier-1 prediction | `model_prediction`, `model_label`, `model_confidence`, `processing_time_ms` | Processor (DistilBERT) |
| Tier-2 overlay | `agent_reviewed`, `agent_model_used`, `agent_final_decision`, `agent_explanation`, `agent_latency_seconds` | `xai_batch_judge.py` or `xai_judge_tool.py` |

### Closed-value fields

| Field | Allowed values |
|---|---|
| `model_label` | `HATE` \| `OFFENSIVE` \| `Normal` |
| `env_domain` | See §1 above |
| `env_strictness` | `low` \| `medium` \| `high` |
| `agent_final_decision` | `Correct` \| `False Positive` \| `False Negative` \| `Parsing Error` |

All Kibana aggregations and the `stats_tool` rely on these being exact strings — that's why the closed taxonomy is enforced at the Context Agent boundary and again clamped in `resolve_environment()`.

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
