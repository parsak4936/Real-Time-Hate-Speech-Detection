# Real-Time Hate Speech Detection

**Big Data Management's Project — Parsa Kazemi**
**University of Messina · FCRLAB**

A scalable, real-time moderation pipeline for live social-media chat. A Tier-1 DistilBERT static classifier (~36 ms inference, 79.4% validation accuracy) provides high-throughput labelling; a Tier-2 LLM-based agentic auditor (`gpt-oss:120b-cloud` via Ollama) asynchronously resolves low-confidence edge cases. On the 459-record manual benchmark the hybrid system reaches **93.5 % accuracy vs human ground truth** (vs 71.0 % for the static classifier alone).

The full architectural rationale lives in `Internship_report_Draft_1 (1).pdf`. This README is the operator's quick-start. For thesis-level documentation see [`docs/`](docs/).

## Documentation index

**Start here.** If you've never seen this codebase, read these in order:

| Order | File | Purpose |
|---|---|---|
| 1 | [`docs/PROJECT_REFERENCE.md`](docs/PROJECT_REFERENCE.md) | **Single-page everything** — every file's purpose, full tree, all citations, quick-lookups. Keep open while writing thesis. |
| 2 | [`docs/STATUS.md`](docs/STATUS.md) | Current state — what's built, what's pending, whether to commit. |
| 3 | [`docs/CODEBASE_TOUR.md`](docs/CODEBASE_TOUR.md) | Sequenced reading path for studying the project from scratch (~3-4 hours). |
| 3 | [`docs/GLOSSARY.md`](docs/GLOSSARY.md) | Every tool + concept + alternative, thesis-citable. |
| 4 | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 5-layer figure → folder structure. |
| 5 | [`docs/SCHEMA.md`](docs/SCHEMA.md) | Universal payload + ES doc schema, full field contract. |
| 6 | [`docs/PROMPTS.md`](docs/PROMPTS.md) | Canonical text of every LLM prompt. |
| 7 | [`docs/EVAL.md`](docs/EVAL.md) | How to reproduce the report's 93.5%. |
| 8 | [`docs/RUNBOOK.md`](docs/RUNBOOK.md) | Two end-to-end recipes — Path A (RAG without labels, 30 min) and Path B (full live data collection). |
| 9 | [`docs/MONITORING.md`](docs/MONITORING.md) | Every visibility surface (Kibana, Qdrant dashboard, operator dashboard). |
| 10 | [`docs/AUDIT_GUIDE.md`](docs/AUDIT_GUIDE.md) | Per-file checklist for reviewing the codebase. |
| 11 | [`docs/MIGRATION.md`](docs/MIGRATION.md) | Should I wipe ES? Per-step audit checklist for in-place vs fresh-start migration. |
| 12 | [`docs/SOURCES.md`](docs/SOURCES.md) | Free ingestion APIs (YouTube, Twitch, Reddit, Hacker News, Mastodon, Bluesky, ...) + setup. |
| 13 | [`docs/THESIS_DELIVERABLES.md`](docs/THESIS_DELIVERABLES.md) | Complete checklist of everything you need to produce for the thesis report. |
| 14 | [`docs/IMPROVEMENTS.md`](docs/IMPROVEMENTS.md) | Prioritised list of robustness / agentic / methodology / supervisor-management improvements. |
| 15 | [`docs/ROADMAP.md`](docs/ROADMAP.md) | Stage 0 → Stage 7 plan, planning lens only. |

## Datasets

- **Davidson et al. (2017)** — [Repository](https://github.com/t-davidson/hate-speech-and-offensive-language)
- **HateXplain** — [Repository](https://github.com/hate-alert/HateXplain)
- **ToxiGen** — [HuggingFace](https://huggingface.co/datasets/toxigen/toxigen-data)

## Setup

### Prerequisites

- Docker Desktop installed and running.
- Python 3.9+.
- [Ollama](https://ollama.com) installed locally and the configured model (`gpt-oss:120b-cloud` by default) available.

### Assets

- **Datasets:** [OneDrive link](https://unimeit-my.sharepoint.com/:u:/g/personal/kzmprs99h12z224y_studenti_unime_it/IQALdCPwnEgERaCJu7DbUNOTAfZ656fGZeJzMy4RAtntCXI?e=yLHFRa) — extract into `data/`.
- **Trained DistilBERT:** [OneDrive link](https://unimeit-my.sharepoint.com/:u:/g/personal/kzmprs99h12z224y_studenti_unime_it/IQCbk51AuA3DQoF0l4almQK4AQW3uwICBwxVIqRSceczPec?e=bBY8vE) — extract the `bert_final` folder into `models/`.

### Install Python deps

```bash
python -m venv Hate_speach_env
Hate_speach_env\Scripts\activate    # Windows
pip install -r requirements.txt
```

### Bring up the infrastructure (Kafka, Zookeeper, Spark, Elasticsearch, Kibana)

```bash
docker-compose up -d
```

Kibana will be available at <http://localhost:5601> once the cluster is healthy.

## Running the pipeline

Three independent processes need to run for an end-to-end live session. Open three terminals:

### Terminal 1 — Tier-1 Processor

```bash
python src/static_classifier/distilbert_processor.py
```

Consumes the Kafka topic `universal_stream`, runs DistilBERT, writes labelled records to the `real_time_analysis` Elasticsearch index and to `data/stream_log.csv`.

### Terminal 2 — Producer (YouTube live chat)

```bash
python src/ingestion/omni_ingest.py
```

Prompts for a YouTube live URL (Enter accepts a default test stream). Scrapes the page metadata, calls the Context Agent to assign `env_domain` / `env_subgenre` / `env_strictness`, then publishes chat messages to Kafka.

### Terminal 3 — Tier-2 Async Auditor (run on a cadence)

```bash
python src/agents/xai_batch_judge.py
```

Sweeps unreviewed records with confidence `< 0.80`, asks the LLM to validate, writes the verdict overlay back to Elasticsearch. Re-run periodically — every few minutes is plenty.

### Analyst console (on-demand)

```bash
python src/agents/leader_agent.py
```

Natural-language interface to the pipeline. Routes to search, stats, per-user audit, or weather tools. See `docs/PROMPTS.md` §3 for the supported analyst vocabulary.

## Kibana dashboard

1. Open <http://localhost:5601>.
2. Stack Management → Saved Objects → Import.
3. Pick `dashboard.ndjson` in this repo.
4. Open the new "Real-Time Analysis" dashboard.

## Other scripts

| Script | Purpose |
|---|---|
| `src/calculate_thesis_metrics.py` | Aggregate metrics over `thesis_final_benchmark.csv`. |
| `src/export_subset.py` | Pull reviewed records out of ES into `thesis_final_benchmark.csv`. |
| `src/agents/check_db_size.py` | Inspect a sample ES record to view the live schema. |
| `src/reset_db.py --yes` | **Destructive.** Wipes the configured ES index. |
| `scripts/normalize_domains.py` | Backfill legacy compound `env_domain` values into the closed taxonomy. Dry-run by default; pass `--apply` to write. |

## Training notebook

`src/Hate_speach_Project.ipynb` contains the DistilBERT fine-tuning code that produced `models/bert_final/`. It is preserved for reproducibility but is not part of the runtime pipeline.

## Project status

This is the codebase as of the end of the internship phase. The roadmap for the thesis extension — RAG, temporal memory, multi-agent, advanced XAI, edge optimisation, FL — lives in [`docs/ROADMAP.md`](docs/ROADMAP.md).
