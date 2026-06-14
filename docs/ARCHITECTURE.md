# Architecture

This document maps the paper's 5-layer figure (Internship_report §3, Fig. 1) onto the actual `src/` folder structure, so a reviewer can move between the report and the code without guessing.

## Layer map

```
+--------------------------------------------------------------+
|  Layer 5 — Analyst Surface                                   |
|  src/agents/leader_agent.py              (orchestrator)      |
|  src/agents/tools/*.py                   (tool registry)     |
+--------------------------------------------------------------+
|  Layer 4 — Storage & Visualisation                           |
|  Elasticsearch  (index: real_time_analysis)                  |
|  Kibana         (dashboard.ndjson)                           |
+--------------------------------------------------------------+
|  Layer 3 — Tier-1 Static Classifier                          |
|  src/static_classifier/distilbert_processor.py               |
|  src/agents/xai_batch_judge.py          (async Tier-2)       |
+--------------------------------------------------------------+
|  Layer 2 — Streaming Backbone                                |
|  Kafka 7.5.0 + Zookeeper 3.9 + Spark 3.4.1                   |
|  docker-compose.yml                                          |
+--------------------------------------------------------------+
|  Layer 1 — Producers + Context Agent                         |
|  src/ingestion/omni_ingest.py                   (router)     |
|  src/ingestion/adapters/youtube_adapter.py                   |
|  src/ingestion/adapters/context_agent.py                     |
+--------------------------------------------------------------+
```

## Flow diagram (data path)

```mermaid
flowchart TD
    A[YouTube live chat] -->|pytchat| B[youtube_adapter.py]
    B -->|raw HTML metadata| C[context_agent.py]
    C -->|LLM: env_domain + env_subgenre + env_strictness| B
    B -->|Universal Schema JSON| K[Kafka topic: universal_stream]
    K -->|KafkaConsumer| P[distilbert_processor.py]
    P -->|DistilBERT inference| E[(Elasticsearch index: real_time_analysis)]
    E --> KB[Kibana dashboard]
    E -.->|low-confidence sweep| J[xai_batch_judge.py]
    M[memory.py: user history + thread context] -.->|injected into prompt| J
    E -.->|memory queries| M
    Q[(Qdrant vector DB: moderation_records)] -.->|k=5 nearest precedents| R[rag.py]
    R -.->|injected into prompt when RAG_ENABLED| J
    E -.->|build_rag_index.py bulk-embeds| Q
    J -->|LLM verdict + memory + precedent metadata| E
    AN[Analyst] --> L[leader_agent.py]
    L --> R{Tool Router}
    R --> S1[search_tool]
    R --> S2[stats_tool]
    R --> S3[xai_judge_tool]
    R --> S4[weather_tool]
    S1 --> E
    S2 --> E
    S3 --> E
```

## Folder map

```
F:\hate-speech-pipeline\
├── docker-compose.yml          Layer 2 stack (Kafka, Zookeeper, Spark, ES, Kibana)
├── dashboard.ndjson            Kibana dashboard import
├── data/                       Datasets (gitignored)
│   ├── Davidson_dataset.csv
│   ├── HXE_dataset.json
│   ├── ToxiGen_dataset.csv
│   ├── Final_Mega_Dataset.csv
│   ├── live_youtube_validation.csv   Dataset B (manual ground truth)
│   ├── final_results_analyzed.csv    Tri-model side-by-side
│   ├── pending_taxonomy.log          Off-seed domains the LLM proposed
│   └── stream_log.csv                CSV audit log (written by processor)
├── models/                     Pre-trained artefacts (gitignored)
│   ├── bert_final/             DistilBERT fine-tuned checkpoint
│   ├── logistic_regression.pkl Classical baseline
│   ├── svm_model.pkl           Classical baseline
│   └── tfidf_vectorizer.pkl    Feature extractor for the .pkl baselines
├── docs/                       Thesis-facing documentation
│   ├── ARCHITECTURE.md         (this file)
│   ├── SCHEMA.md               Universal payload + ES doc schema
│   ├── PROMPTS.md              Canonical text of every LLM prompt
│   ├── EVAL.md                 How to reproduce the report's 93.5%
│   └── ROADMAP.md              Planning lens with numbered stages
├── config/
│   ├── taxonomy.yaml           Operator-extensible domain seed list
│   └── rag.yaml                RAG knobs (embedding model, top_k, threshold)
├── scripts/
│   ├── normalize_domains.py    Backfill open-taxonomy domains to closed taxonomy
│   ├── replay_with_memory.py   Re-judge ES records with memory-augmented prompt
│   ├── build_rag_index.py      Bootstrap Qdrant vector index from ES corpus
│   └── _build_eval_notebook.py Generator for notebooks/evaluation.ipynb
├── notebooks/
│   └── evaluation.ipynb        Living per-pipeline-variant evaluation
├── src/
│   ├── ingestion/              Layer 1 — producers + Context Agent
│   │   ├── omni_ingest.py      YouTube ingestion entry point
│   │   └── adapters/
│   │       ├── youtube_adapter.py
│   │       └── context_agent.py
│   ├── static_classifier/      Layer 3 — Tier-1 static classifier
│   │   └── distilbert_processor.py
│   ├── agents/                 Layer 5 — Tier-2 agents + analyst console
│   │   ├── leader_agent.py     Orchestrator
│   │   ├── xai_batch_judge.py  Async Tier-2 sweep (uses memory when MEMORY_ENABLED)
│   │   ├── check_db_size.py    Schema inspector
│   │   └── tools/
│   │       ├── search_tool.py
│   │       ├── stats_tool.py
│   │       ├── xai_judge_tool.py
│   │       └── weather_tool.py
│   ├── shared_utils/           Cross-cutting helpers
│   │   ├── config.py           Env-driven configuration (incl. MEMORY_*)
│   │   ├── prompts.py          Canonical LLM prompts (single source of truth)
│   │   ├── llm.py              Thin Ollama wrapper (temp=0, format=json, 1 retry)
│   │   ├── taxonomy.py         Domain-taxonomy normaliser (config/taxonomy.yaml)
│   │   ├── memory.py           Temporal memory (ES-backed user/thread history)
│   │   └── rag.py              Semantic retrieval (Qdrant + sentence-transformers)
│   ├── calculate_thesis_metrics.py
│   ├── export_subset.py
│   ├── reset_db.py             Destructive — requires --yes
│   └── Hate_speach_Project.ipynb   Training notebook for DistilBERT
├── README.md
├── requirements.txt
└── Internship_report_Draft_1 (1).pdf   Authoritative spec / report
```

## Process boundaries

Five independent processes once Stage 3 (RAG) is activated:

| # | Process | Command | What it does |
|---|---------|---------|--------------|
| 1 | Producer | `python src/ingestion/omni_ingest.py` | Asks for a YouTube URL, scrapes metadata, runs the Context Agent, pushes chat messages to Kafka. |
| 2 | Processor | `python src/static_classifier/distilbert_processor.py` | Consumes the Kafka topic, runs DistilBERT, writes to Elasticsearch + CSV log. |
| 3 | Tier-2 sweep | `python src/agents/xai_batch_judge.py` | Periodically audits low-confidence ES records and overlays the LLM verdict. Run on a cadence. |
| 4 | RAG bootstrap | `python scripts/build_rag_index.py --apply` | One-off (or periodic) — walks ES, embeds, populates Qdrant. Idempotent; safe to re-run. Required before `RAG_ENABLED` can do anything useful. |
| 5 | Leader (analyst console) | `python src/agents/leader_agent.py` | On-demand. The analyst opens this when they want to query the pipeline. |

Stage 3 (RAG) is currently **scaffolded but not wired into the live judge** — see [`docs/ROADMAP.md`](ROADMAP.md). Setting `RAG_ENABLED=True` while the agents still call `build_judge_prompt_with_memory` is a no-op; the activation step (one-line change in `xai_batch_judge.py` to pick the `_with_memory_and_rag` variant when both flags are on) lands together with `scripts/replay_with_memory_and_rag.py` when the user is ready to evaluate Stage 3.
