# Real-Time Hate Speech Detection

**Big Data Management's Project — Parsa Kazemi**
**University of Messina · FCRLAB**

A scalable, real-time moderation pipeline for live social-media chat. A Tier-1 DistilBERT static classifier (~36 ms inference) provides high-throughput labelling; a Tier-2 LLM-based agentic auditor (`gpt-oss:120b-cloud` via Ollama) resolves contextual edge cases. Ingests from **YouTube, Twitch, Reddit, and Trustpilot** through a common schema.

> **Setting up for the first time?** Follow [`docs/INSTALL.md`](docs/INSTALL.md) — a complete step-by-step guide from a fresh machine to a live dashboard.

Beyond the internship baseline, the pipeline adds four agentic capabilities, each measured against a hand-labelled benchmark: an **agentic Context Agent** (discovers the content domain in free text), **temporal memory** (judge sees user/thread history), **retrieval-augmented moderation** (Qdrant precedents), and a **four-agent decomposition** (risk scorer + behaviour profiler + escalator + supervisor). The multi-agent variant currently leads on toxic-class F1.

The full architectural rationale lives in `Internship_report_Draft_1 (1).pdf`. This README is the operator's quick-start. For thesis-level documentation see [`docs/`](docs/). **New here? Read [`docs/PROJECT_REFERENCE.md`](docs/PROJECT_REFERENCE.md) and [`docs/STATUS.md`](docs/STATUS.md) first.**

## Documentation index

**Start here.** If you've never seen this codebase, read these in order:

| Order | File | Purpose |
|---|---|---|
| 0 | [`docs/INSTALL.md`](docs/INSTALL.md) | **Install & first run** — fresh machine to live dashboard, step by step. Start here to set up. |
| 1 | [`docs/PROJECT_REFERENCE.md`](docs/PROJECT_REFERENCE.md) | **Single-page everything** — every file's purpose, full tree, all citations, quick-lookups. Keep open while writing thesis. |
| 2 | [`docs/STATUS.md`](docs/STATUS.md) | Current state — what's built, what's pending, whether to commit. |
| 3 | [`docs/CODEBASE_TOUR.md`](docs/CODEBASE_TOUR.md) | Sequenced reading path for studying the project from scratch (~3-4 hours). |
| 3 | [`docs/GLOSSARY.md`](docs/GLOSSARY.md) | Every tool + concept + alternative, thesis-citable. |
| 4 | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 5-layer figure → folder structure. |
| 5 | [`docs/SCHEMA.md`](docs/SCHEMA.md) | Universal payload + ES doc schema, full field contract. |
| 6 | [`docs/PROMPTS.md`](docs/PROMPTS.md) | Canonical text of every LLM prompt. |
| 6b | [`docs/MODELS.md`](docs/MODELS.md) | Every model & tool (DistilBERT, the LLM, embedding model, Qdrant, Ollama) — selection rationale + alternatives, thesis-ready. |
| 7 | [`docs/EVAL.md`](docs/EVAL.md) | How to reproduce the report's 93.5%. |
| 7b | [`docs/COMMANDS.md`](docs/COMMANDS.md) | **Single step-by-step command reference** — infra → ingestion → tiers → UIs → evaluation. Copy-paste. |
| 8 | [`docs/RUNBOOK.md`](docs/RUNBOOK.md) | Two end-to-end recipes — Path A (RAG without labels) and Path B (full live data collection). |
| 9 | [`docs/MONITORING.md`](docs/MONITORING.md) | Every visibility surface (Kibana, Qdrant dashboard, the Streamlit dashboard). |
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
- **Worker bundle (scaling experiments):** [OneDrive link](https://unimeit-my.sharepoint.com/:u:/g/personal/kzmprs99h12z224y_studenti_unime_it/IQC0efg98sJfRb3EbQGlyFVRASwJOlZfTgcpdD91Q5Kj4f0?e=dBZsug) — the trained model plus `data/stream_log.csv` (the replay workload) in one ~290 MB zip, for setting up an extra machine quickly. Unzip it **at the repository root** so `models/` and `data/` land in place:

  ```bash
  curl -L "https://unimeit-my.sharepoint.com/:u:/g/personal/kzmprs99h12z224y_studenti_unime_it/IQC0efg98sJfRb3EbQGlyFVRASwJOlZfTgcpdD91Q5Kj4f0?e=dBZsug&download=1" -o worker_bundle.zip
  unzip -o worker_bundle.zip -d .
  ```

  `models/` and `data/` are git-ignored, so a clone alone does not include them.

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

### Terminal 2 — Producer (YouTube / Twitch / Reddit)

```bash
python src/ingestion/omni_ingest.py
```

Prompts for a URL. Accepts a YouTube live link, a Twitch channel (`twitch.tv/<channel>`), a subreddit (`r/<name>`), or a Trustpilot business page (`trustpilot.com/review/<domain>`). Scrapes metadata, calls the Context Agent to assign `env_domain` / `env_subgenre` / `env_strictness`, then publishes chat to Kafka. See [`docs/SOURCES.md`](docs/SOURCES.md) for each source's setup (Reddit needs free API keys in `.env`; YouTube, Twitch, and Trustpilot need none).

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

## The two UIs

Two Streamlit apps (run on different ports). Both are operator-facing, not end-user-facing.

```bash
# 1. Dashboard — sidebar toggles between "Live Pipeline" (ES monitoring) and
#    "Evaluation" (benchmark deep-dive: scoreboard, per-record decision journey
#    with the 4 multi-agent specialists, RAG retrieval, confusion matrices).
streamlit run scripts/ui/dashboard.py

# 2. Analyst chat — natural-language queries to the pipeline, with the LLM's
#    tool-call reasoning shown in expanders.
streamlit run scripts/ui/analyst_chat.py --server.port 8502
```

## Evaluation workflow

Once you have a hand-labelled benchmark CSV (`human_ground_truth` filled in), produce every variant's verdict and compare:

```bash
python -u scripts/eval/replay_with_memory.py --csv thesis_benchmark_eval.csv --apply
python scripts/eval/sync_es_to_csv.py thesis_benchmark_eval.csv --apply
python -u scripts/setup/seed_rag_from_csv.py thesis_benchmark_eval.csv --apply
python -u scripts/eval/replay_with_rag.py --csv thesis_benchmark_eval.csv --apply
python -u scripts/eval/replay_with_multi_agent.py --csv thesis_benchmark_eval.csv --apply
python scripts/eval/check_results.py            # prints the metrics table
```

To grow the benchmark with more toxic examples without re-labelling existing rows:
```bash
python scripts/eval/sample_for_eval.py --bias toxic --target-size 200 --append thesis_benchmark_eval.csv --apply
```
Full details + the rules that keep this safe (one process at a time, `python -u`, no `--force` to resume) are in [`docs/STATUS.md`](docs/STATUS.md) and [`docs/RUNBOOK.md`](docs/RUNBOOK.md).

## Other scripts

| Script | Purpose |
|---|---|
| `scripts/eval/check_results.py` | Print the per-variant metrics table from a benchmark CSV. |
| `scripts/eval/sample_for_eval.py` | Sample (random or `--bias toxic`) from ES into a benchmark CSV; `--append` merges without duplicates. |
| `scripts/setup/init_es_index.py` | Create the ES index with the explicit 32-field mapping. |
| `scripts/setup/normalize_domains.py` | Backfill legacy compound `env_domain` values. Dry-run by default. |
| `scripts/eval/export_subset.py` | Pull reviewed records out of ES into a benchmark CSV. |
| `src/agents/check_db_size.py` | Inspect a sample ES record to view the live schema. |
| `scripts/setup/reset_db.py --yes` | **Destructive.** Wipes the configured ES index. |

## Kibana

Kibana (<http://localhost:5601>) is available for ad-hoc ES exploration; import `dashboard.ndjson` via Stack Management → Saved Objects → Import. Day-to-day, the Streamlit dashboard above is the primary monitoring surface.

## Training notebook

`notebooks/Hate_speach_Project.ipynb` contains the DistilBERT fine-tuning code that produced `models/bert_final/`. Preserved for reproducibility; not part of the runtime pipeline.

## Project status

Stages 0–5 implemented (consolidation, agentic context, evaluation harness, temporal memory, RAG, multi-agent decomposition, explainability visualisation). Current state, results, and the canonical re-run flow are in [`docs/STATUS.md`](docs/STATUS.md). The full stage plan is in [`docs/ROADMAP.md`](docs/ROADMAP.md).
