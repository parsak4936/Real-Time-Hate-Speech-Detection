# Installation & first run — step by step

A complete, beginner-friendly guide to get this project running on a fresh
machine, from nothing to a live dashboard. Follow it top to bottom. Commands are
PowerShell (Windows); on macOS/Linux swap the venv activate line.

If you only want the short command reference once you're set up, see
[`COMMANDS.md`](COMMANDS.md).

---

## 1. What you need first (prerequisites)

| Requirement | Why | Check it's there |
|---|---|---|
| **Python 3.9+** | Runs the whole pipeline | `python --version` |
| **Docker Desktop** | Runs Kafka, Elasticsearch, Qdrant, Kibana | `docker --version`, and Docker Desktop is *running* |
| **Ollama** + the judge model | Tier-2 LLM judge, Context Agent, multi-agent | `ollama --version`, then `ollama list` shows the model |
| **~10 GB free disk** | Model + indices + containers | — |
| **Git** | Clone the repo | `git --version` |

The default LLM is `gpt-oss:120b-cloud` (served via Ollama Cloud). It is metered by
GPU-time and has usage quotas — if you hit a cooldown, the LLM stages pause but
Tier-1 (local DistilBERT) keeps working. See [`MODELS.md`](MODELS.md).

---

## 2. Get the code

```powershell
git clone <your-repo-url> hate-speech-pipeline
cd hate-speech-pipeline
```

---

## 3. Get the large assets (not in git)

The training datasets and the fine-tuned DistilBERT model are too big for the
repo. Download them from the OneDrive links in the main [`README.md`](../README.md)
("Assets" section), then extract:

- Datasets → into `data/`
- The `bert_final` folder → into `models/`

After this you should have `models/bert_final/` and several CSVs under `data/`.

---

## 4. Python environment

```powershell
python -m venv Hate_speach_env
Hate_speach_env\Scripts\activate     # macOS/Linux: source Hate_speach_env/bin/activate
pip install -r requirements.txt
```

Leave the venv active for everything below (your prompt should show
`(Hate_speach_env)`).

---

## 5. Configuration (`.env`)

Create a `.env` file in the repo root. Minimum:

```dotenv
# Feature flags
MEMORY_ENABLED=1        # judge uses temporal memory (default on)
RAG_ENABLED=0           # live RAG off until Qdrant is seeded (see step 8)

# Reddit ingestion (OPTIONAL — only if you want the Reddit source)
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
REDDIT_USER_AGENT=hate-speech-pipeline by /u/yourname
```

YouTube, Twitch, and Trustpilot need **no keys**. Reddit needs free API keys —
the one-time setup is in [`SOURCES.md`](SOURCES.md).

---

## 6. Start the infrastructure

```powershell
docker-compose up -d        # Kafka, Zookeeper, Spark, Elasticsearch, Kibana, Qdrant
docker-compose ps           # every service should say "Up"
```

Give it a minute on first run. Health checks:

```powershell
curl http://localhost:9200/_cat/health      # Elasticsearch: line ends green/yellow
curl http://localhost:6333/collections      # Qdrant: {"result":...,"status":"ok"}
ollama list                                  # the judge model is listed
```

Create the Elasticsearch index (first run only):

```powershell
python scripts/setup/init_es_index.py --apply
```

---

## 7. First live run (3 terminals)

Open three PowerShell windows, venv active in each.

**Terminal 1 — Tier-1 processor (local DistilBERT, leave running):**
```powershell
python src/static_classifier/distilbert_processor.py
```
Wait for `BERT Model Loaded successfully.`

**Terminal 2 — producer (one source at a time):**
```powershell
python src/ingestion/omni_ingest.py
```
Paste one of:
- YouTube live link: `https://www.youtube.com/watch?v=...`
- Twitch channel: `https://www.twitch.tv/<channel>`
- Reddit: `r/<subreddit>` (needs keys)
- **Trustpilot: `https://www.trustpilot.com/review/<business-domain>`** (e.g. `.../review/www.amazon.com`)

**Terminal 3 — Tier-2 batch judge (run on a cadence; needs Ollama):**
```powershell
python src/agents/xai_batch_judge.py
```

---

## 8. (Optional) turn on RAG

```powershell
python -u scripts/setup/seed_rag_from_csv.py thesis_benchmark_eval.csv --apply
```
Then set `RAG_ENABLED=1` in `.env`. RAG is evaluated offline regardless of this
flag (the flag only controls the *live* sweep).

---

## 9. See it working

```powershell
streamlit run scripts/ui/dashboard.py                          # http://localhost:8501
streamlit run scripts/ui/analyst_chat.py --server.port 8502    # http://localhost:8502
```

**"Is it actually working?" checklist:**
- Dashboard status strip shows Elasticsearch **Online** with a non-zero doc count.
- "Data flow" shows a recent last-record age while a producer runs.
- The Live Monitor tab fills with records and label/platform breakdowns.

---

## 10. Reproduce the evaluation numbers (no live data needed)

The benchmark CSV ships with the repo, so you can score every variant immediately:

```powershell
python scripts/eval/check_results.py
```

Full charts + significance tests:
```powershell
jupyter notebook notebooks/evaluation.ipynb     # Kernel -> Restart & Run All
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| A script hangs with no output | You ran it without `-u` (buffered) or two heavy scripts at once. Use `python -u`, one at a time. |
| Dashboard panels all show 0 | No data in the window — widen the time range, or check the processor + producer are running. |
| `Qdrant errors / RAG empty` | `docker-compose restart qdrant`, then re-seed (step 8). |
| LLM stages fail / time out | Ollama quota cooldown, or the model isn't pulled. `ollama list` to confirm. Tier-1 still works without it. |
| A replay says `Processed: 0` | Those rows already have that variant filled. That's expected on resume; add `--force` only to redo. |

More background: [`RUNBOOK.md`](RUNBOOK.md), [`MIGRATION.md`](MIGRATION.md),
[`STATUS.md`](STATUS.md).
