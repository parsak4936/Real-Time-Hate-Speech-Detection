# Commands — run everything, step by step

The single copy-paste reference, in order. PowerShell (Windows). Run each block
from the repo root `F:\hate-speech-pipeline` with the venv active.

> Rule that keeps things sane: **run one heavy script at a time**, and prefix
> long-running Python with `-u` so you see live output (`python -u ...`).

---

## 0. One-time setup

```powershell
# Activate the virtual environment
Hate_speach_env\Scripts\activate

# Install dependencies (only needed once, or after a pull)
pip install -r requirements.txt
```

Make sure **Docker Desktop** and **Ollama** are running (`ollama list` should show
`gpt-oss:120b-cloud`).

---

## 1. Bring up the infrastructure

```powershell
docker-compose up -d          # Kafka, Zookeeper, Spark, Elasticsearch, Kibana, Qdrant
docker-compose ps             # all services should say "Up"
```

Quick health check:

```powershell
curl -s http://localhost:9200/_cat/health     # ES: line ends in green/yellow
curl -s http://localhost:6333/collections     # Qdrant: {"result":...,"status":"ok"}
```

(First run only) create the Elasticsearch index with the correct field types:

```powershell
python scripts/setup/init_es_index.py            # preview
python scripts/setup/init_es_index.py --apply    # create
```

---

## 2. Run the live pipeline (3 terminals)

Open three PowerShell windows, venv active in each.

### Terminal 1 — Tier-1 processor (leave running)

```powershell
python src/static_classifier/distilbert_processor.py
```
Consumes Kafka, runs DistilBERT, writes labelled records to Elasticsearch.
Wait for `BERT Model Loaded successfully.`

### Terminal 2 — Producer / ingestor (one stream at a time)

```powershell
python src/ingestion/omni_ingest.py
```
When prompted, paste one of:
- YouTube live link: `https://www.youtube.com/watch?v=...`
- Twitch channel:    `https://www.twitch.tv/<channel>`  (or just `<channel>`)
- Reddit subreddit:  `r/<subreddit>`  (Reddit needs API keys in `.env` — see `docs/SOURCES.md`)

Run several instances (more terminals) to ingest multiple streams in parallel.
Ctrl+C stops a producer; it flushes its Kafka buffer on exit.

### Terminal 3 — Tier-2 batch judge (run on a cadence)

```powershell
# Default: audit 60 unreviewed records with confidence < 0.80
python src/agents/xai_batch_judge.py

# Audit a specific platform regardless of confidence:
python src/agents/xai_batch_judge.py --platform Twitch --confidence 1.01 --batch-size 300
python src/agents/xai_batch_judge.py --platform Reddit --confidence 1.01 --batch-size 300

# Balanced sweep across domains:
python src/agents/xai_batch_judge.py --per-domain-cap 30 --batch-size 300
```
Re-run periodically while collecting. ~6 s per record (one LLM call).

---

## 3. Monitor (the two UIs)

```powershell
# Live dashboard (health, volume, label/platform/domain breakdowns, agentic discovery)
streamlit run scripts/ui/dashboard.py

# Analyst chat (ask the pipeline questions in plain English)
streamlit run scripts/ui/analyst_chat.py --server.port 8502
```
Dashboard opens at http://localhost:8501, chat at http://localhost:8502.
Kibana is also available at http://localhost:5601 for ad-hoc exploration.

---

## 4. Build the evaluation benchmark

```powershell
# Sample reviewed records into a CSV. Use --bias toxic to oversample the rare toxic class.
python scripts/eval/sample_for_eval.py --bias toxic --target-size 300 --apply
#   -> writes thesis_benchmark_eval.csv

# To ADD more rows later without duplicating or re-labelling existing ones:
python scripts/eval/sample_for_eval.py --bias toxic --target-size 200 --append thesis_benchmark_eval.csv --apply
```

Then open `thesis_benchmark_eval.csv` and fill in the **`human_ground_truth`**
column for the blank rows: `NORMAL`, `OFFENSIVE`, or `HATE`.

---

## 5. Produce the variant verdicts

Run these one at a time. **Do not pass `--force`** unless you want to redo
already-done rows — without it, each script only processes the new/blank rows.

```powershell
# Stage 2 — memory (writes verdicts to ES, then pull them into the CSV)
python -u scripts/eval/replay_with_memory.py --csv thesis_benchmark_eval.csv --apply
python scripts/eval/sync_es_to_csv.py thesis_benchmark_eval.csv --apply

# Stage 3 — RAG (seed Qdrant from the same CSV, then leave-one-out replay)
python -u scripts/setup/seed_rag_from_csv.py thesis_benchmark_eval.csv --apply
python -u scripts/eval/replay_with_rag.py --csv thesis_benchmark_eval.csv --apply

# Stage 4 — multi-agent (test 5 rows first; full run is 4 LLM calls/row)
python -u scripts/eval/replay_with_multi_agent.py --csv thesis_benchmark_eval.csv --limit 5
python -u scripts/eval/replay_with_multi_agent.py --csv thesis_benchmark_eval.csv --apply
```

---

## 6. Read the results

```powershell
# Quick metrics table in the terminal
python scripts/eval/check_results.py

# Full evaluation with charts, McNemar tests, per-platform/domain breakdowns
jupyter notebook notebooks/evaluation.ipynb
#   -> Kernel -> Restart & Run All
#   -> screenshot §1.4 (accuracy), §6 (multi-agent), §7 (cross-pipeline table)
```

---

## Handy utilities

```powershell
# Inspect one ES record's full schema
python src/agents/check_db_size.py

# Count records per platform
curl -s "http://localhost:9200/real_time_analysis/_count?q=source_platform:Twitch"

# Backfill legacy compound env_domain values (dry-run default)
python scripts/setup/normalize_domains.py
python scripts/setup/normalize_domains.py --apply

# DESTRUCTIVE — wipe the ES index
python scripts/setup/reset_db.py --yes

# Regenerate the evaluation notebook from its builder
python scripts/eval/_build_eval_notebook.py
```

---

## Troubleshooting quick hits

- **A replay says `Processed: 0`** → the rows already have that variant's column
  filled. Add `--force` to redo, or it means there's nothing new to do.
- **A script hangs silently** → you ran it without `-u` (output buffered) or two
  heavy scripts at once. Use `python -u`, one at a time.
- **Qdrant errors / RAG empty** → `docker-compose restart qdrant`, then re-seed.
- **Dashboard shows 0 in panels** → no data in the window; widen the time range or
  check the processor is running.

Full background and recovery steps: `docs/RUNBOOK.md`, `docs/MIGRATION.md`,
`docs/STATUS.md`.
