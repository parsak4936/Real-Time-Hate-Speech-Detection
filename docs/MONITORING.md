# Monitoring — how to see the pipeline working

You asked: "should I have a UI control panel, or just multiple terminals? Prof said no chat UI." This document answers that question and explains every visibility surface you have.

---

## The Chat UI vs Monitoring UI distinction

**Your prof's "no chat UI" rule applies to a chat-style end-user interface** — a ChatGPT-like surface where the *end user* talks to the system. That's a different product (a moderation chatbot) from the one you're building (a moderation pipeline).

A **monitoring / operator dashboard** is something else entirely. It's the equivalent of a power-plant control room: numbers, charts, "is the boiler at 380°C?". It's for the **operator**, not the end user. Trust & Safety teams universally use these — without one, a moderator has to SSH into a server and read logs.

**The thesis-defensible position is**: "I do not expose a chat UI to end users. I expose a monitoring dashboard to operators, consistent with industry practice for Trust & Safety systems."

That's defensible and aligns with what your prof asked for. So yes — build one.

---

## What you already have (use these first)

### Kibana — http://localhost:5601
**What.** Elasticsearch's official dashboard. The `dashboard.ndjson` file in the repo root imports a pre-configured layout once you load it through *Stack Management → Saved Objects → Import*.

**What you can see.**
- Volume of records over time per platform / domain.
- Tier-1 (DistilBERT) label distribution per domain.
- Tier-2 (Agent) override breakdown.
- Top users by message count.
- Recent records (table view).
- Free-form full-text search across the entire `real_time_analysis` index.

**Use this for.** "Is data flowing into Elasticsearch?" "What does the long-tail of weird records look like?" "Which domains am I getting?"

### Qdrant Dashboard — http://localhost:6333/dashboard
**What.** Qdrant's built-in web UI, ships with the Docker image.

**What you can see.**
- How many points are in the `moderation_records` collection.
- Collection settings (vector dim, distance metric).
- Free-form similarity queries (paste text → get top-k matches).

**Use this for.** "Is RAG working? Are precedents getting indexed? What does a similarity search look like?"

### Process terminals
**What.** Your three / four python processes (producer, processor, batch judge, optionally leader agent).

**What you can see.**
- Live console of each step: scraped metadata, BERT inference timings, LLM verdicts, parsing errors.

**Use this for.** Real-time debugging. When something's wrong, the terminal that's silent (when it shouldn't be) usually tells you which component died.

### `data/stream_log.csv`
**What.** An append-only audit log written by `distilbert_processor.py` with every Tier-1 verdict.

**What you can see.**
- Offline reproducibility of every Tier-1 decision (open in Excel).
- Compare a Tier-1 column to Tier-2 verdicts in ES via `message_id`.

### `data/pending_taxonomy.log`
**What.** The tab-separated log written by `taxonomy.normalise_domain()` whenever the LLM proposes a domain not in the seed list.

**What you can see.** Live evidence of agentic discovery beyond the seed taxonomy — itself a thesis-publishable signal.

```bash
# Quick stats:
wc -l data/pending_taxonomy.log
sort -u -k2 data/pending_taxonomy.log | head -20
```

---

## The new piece — `scripts/operator_dashboard.py`

Run with:
```bash
streamlit run scripts/operator_dashboard.py
```

Opens at http://localhost:8501.

A single-page Streamlit dashboard that unifies the views above:

| Panel | What it shows | Refreshes |
|---|---|---|
| **Health** | Are ES, Kafka (via ES record write timestamps), Qdrant, Ollama reachable? | Every 5s |
| **Volume** | Records per minute over the last hour. | Every 10s |
| **Tier-1 label distribution** | HATE / OFFENSIVE / Normal counts in the last hour. | Every 10s |
| **Tier-2 verdicts** | Correct / False Positive / False Negative since the last batch sweep. | Every 10s |
| **Recent records (last 20)** | Text + author + Tier-1 verdict + Tier-2 verdict. | Every 5s |
| **Domain agentic discovery** | How many domains has the LLM proposed off-seed? Count and the latest 10. | Every 15s |
| **RAG status** | Points in the Qdrant collection. | On click |
| **Memory metadata** | For records reviewed in the last hour: average user-history messages, average thread-context messages. | Every 15s |

**Why Streamlit specifically.** One file, no front-end build step, hot-reload on save. Examiner-friendly: "I built a small Streamlit operator dashboard" is a normal sentence; building React would be overkill.

**Alternatives** (mentioned in case the examiner asks):
- **Grafana** — more powerful for time-series; needs an additional service.
- **Custom Flask/FastAPI + React** — production-grade but disproportionate to a thesis project.
- **Plotly Dash** — similar to Streamlit, more code per panel.
- **Just Kibana** — no extra code, but no unified view of ES + Qdrant + Ollama health.

**Note on chat UI.** This dashboard is explicitly **read-only**. There is no input box where a user can type queries.

A companion file, [`scripts/analyst_chat.py`](../scripts/analyst_chat.py), provides a Streamlit chat interface to the Leader Agent for moderator use. It is also operator-facing (not end-user-facing). Run with:

```bash
streamlit run scripts/analyst_chat.py --server.port 8502
```

The dashboard (8501) and the chat (8502) can run side by side. The chat shows the LLM's tool-call decomposition in expanders, which is itself a thesis-worthy artefact: examiners can see exactly how the agent reasoned per query.

---

## A "verify each component is working" runbook

Five quick checks. Each takes <1 minute:

### 1. Kafka is reachable
```bash
docker exec kafka kafka-topics --bootstrap-server localhost:9093 --list
# Expect: universal_stream  (or empty list before first run)
```

### 2. Elasticsearch is reachable and has records
```bash
curl -s http://localhost:9200/_cat/indices/real_time_analysis
# Expect: a line with doc count
```

### 3. Recent records in ES
```bash
python src/agents/check_db_size.py
# Expect: prints schema fields for one row
```

### 4. Qdrant has points
```bash
curl -s http://localhost:6333/collections/moderation_records
# Expect: {"result": {"vectors_count": N, ...}, "status": "ok"}
```

### 5. Ollama can serve the model
```bash
ollama list
# Expect: gpt-oss:120b-cloud appears in the list
ollama run gpt-oss:120b-cloud "ping" --format=json
# Expect: a JSON response (or at least no connection error)
```

If ALL five pass, the pipeline is alive end-to-end. Run the operator dashboard to confirm live updates.

---

## What to monitor during a live stream

When `omni_ingest.py` is feeding a stream, watch for:

| Signal | Healthy | Warning sign |
|---|---|---|
| Records/sec in Kibana | 0.5 – 5 | 0 (producer disconnected) or > 20 (rate-limit risk) |
| Tier-1 latency | 25 – 60 ms | > 200 ms (CPU contention) |
| Tier-2 latency | 4 – 10 s | > 15 s (Ollama overload) |
| `agent_memory_user_msgs` average | 0 – 8 | always 0 (memory disabled or `author_id.keyword` broken) |
| `env_domain_match` distribution | mostly `alias`/`exact`/`fuzzy` | mostly `unknown` (LLM proposing wild categories) |
| `pending_taxonomy.log` growth | a few unique entries per stream | hundreds of unique entries (LLM not converging) |

---

## "If I see X, do Y" cheat-sheet

| Symptom | Likely cause | Fix |
|---|---|---|
| Kibana empty | Producer not running OR Kafka unreachable | Check Terminal 2; restart `docker-compose restart kafka` |
| Producer prints `[BLOCKED]` | Stream isn't live | Pick a different URL |
| Processor crashes on start | DistilBERT weights missing | Re-download `models/bert_final/` from the OneDrive link in README |
| Batch judge prints `0 records to audit` | All current records have confidence ≥ 0.80 OR all are already reviewed | Lower `TARGET_CONFIDENCE_BELOW`, or wait for new low-confidence records |
| All `agent_final_decision` are `Parsing Error` | Ollama returning malformed JSON | Check Ollama logs; bump retry count in `llm.py`; reduce prompt length |
| `replay_with_rag.py` returns identical baseline = with_rag for every row | Qdrant empty OR threshold too high | `python scripts/seed_rag_from_csv.py thesis_final_benchmark.csv --apply`; lower `similarity_threshold` in `config/rag.yaml` |
| Operator dashboard panel "Qdrant" red | Container not running | `docker-compose up -d qdrant` |
| `pending_taxonomy.log` exploding | LLM proposing very specific subcategories | Raise `fuzzy_match_threshold` or expand `config/taxonomy.yaml` aliases |
