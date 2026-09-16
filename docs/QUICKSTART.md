# Quick Start — running the pipeline from a fresh clone

A short, happy-path guide for a reviewer who just wants to clone the repository and
see the system work. For the detailed version (every flag, troubleshooting), see
[`INSTALL.md`](INSTALL.md).

Two ways to run it:
- **Path A — reproduce the evaluation** (fastest; no live streams, no LLM needed).
- **Path B — run the live pipeline** (ingest a real stream end to end).

Most reviewers only need Path A.

---

## 0. What you need first

- **Docker Desktop** (running)
- **Python 3.9+**
- **Git**
- For Path B only: **[Ollama](https://ollama.com)** with the judge model pulled
  (`ollama pull gpt-oss:120b-cloud`)

## 1. Clone

```bash
git clone <REPO-URL> hate-speech-pipeline
cd hate-speech-pipeline
```

## 2. Get the model and datasets (not in git — too large)

Download from the OneDrive links in the main [`README.md`](../README.md) ("Assets"),
then place them so you have:

- `models/bert_final/`  ← the fine-tuned DistilBERT
- `data/…`              ← the datasets

The benchmark CSV (`thesis_benchmark_eval.csv`) is already in the repo, so Path A
works as soon as the Python environment is ready.

## 3. Python environment

```bash
python -m venv Hate_speach_env
Hate_speach_env\Scripts\activate      # macOS/Linux: source Hate_speach_env/bin/activate
pip install -r requirements.txt
```

---

## Path A — reproduce the evaluation (no Docker, no LLM)

```bash
python scripts/eval/check_results.py
```

You'll see the per-variant comparison table (Tier-1, Tier-2 baseline, +memory,
+RAG, **+LLM-Wiki**, multi-agent) with toxic-class precision/recall/F1. That's the
headline result of the thesis, reproduced from the labelled benchmark in one command.

For the full charts (Toxic-F1 bars, confusion matrices) and McNemar significance,
open the notebook:

```bash
jupyter notebook notebooks/evaluation.ipynb      # Kernel → Restart & Run All
```

### Switching the retrieval backend (RAG vs LLM-Wiki)

The two retrieval backends are compared offline by their own replay scripts
(`replay_with_rag.py`, `replay_with_wiki.py`), each writing its own column that the
table above compares. To switch which backend the **live** pipeline uses, set one
line in `.env` (see `.env.example`):

```dotenv
RETRIEVAL_BACKEND=rag     # or: wiki, or none
```

Nothing else changes — one flag switches the whole live judge between backends.

---

## Path B — run the live pipeline

Start the infrastructure:

```bash
docker-compose up -d          # Kafka, Zookeeper, Spark, Elasticsearch, Kibana, Qdrant
python scripts/setup/init_es_index.py --apply     # first run only
```

Then open three terminals (virtual environment active in each):

```bash
# 1) Tier-1 processor — labels messages as they arrive
python src/static_classifier/distilbert_processor.py

# 2) Producer — paste a YouTube/Twitch/Reddit link when prompted
python src/ingestion/omni_ingest.py

# 3) Tier-2 judge — reviews the low-confidence cases (needs Ollama)
python src/agents/xai_batch_judge.py
```

Watch it live:

```bash
streamlit run scripts/ui/dashboard.py             # http://localhost:8501
```

**You'll know it works when:** the dashboard's status strip shows Elasticsearch
online with a rising document count, and the Live Monitor fills with labelled
messages while a producer runs.

---

## If something goes wrong

- A script seems stuck → run it with `python -u …` (unbuffered) and one at a time.
- Dashboard panels show 0 → widen the time range, or check the processor and
  producer are both running.
- LLM steps fail → confirm `ollama list` shows the model; Path A does not need it.

Full troubleshooting: [`INSTALL.md`](INSTALL.md) and [`COMMANDS.md`](COMMANDS.md).
