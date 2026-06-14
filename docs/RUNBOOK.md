# Runbook — Three evaluation paths

This is the end-to-end recipe for getting your first measured result on the new pipeline. There are **three paths**, and they answer different questions:

| Path | Measures | Needs new live data? | Needs manual labelling? | Time to first number |
|---|---|---|---|---|
| **A. Stage 3 — RAG-only (recommended first)** | Does semantic retrieval (Qdrant + sentence-transformers) help the Tier-2 judge? | **No** | **No** | ~1.5–2 hours (mostly LLM inference) |
| **B. Stage 2 — Temporal Memory** | Does user history + thread context help the Tier-2 judge? | Yes | Yes (~30 min) | ~2.5–3 hours end-to-end |
| **C. Stage 4 — Multi-Agent Decomposition** | Does a five-agent ensemble out-perform the monolithic Tier-2 judge? | **No** | **No** | ~2–3 hours (agent orchestration overhead) |

Path A and C use the 298-record internship CSV (`thesis_benchmark_eval.csv`) as both corpus and test set, via leave-one-out cross-validation. No new labelling required.

Path B genuinely requires a live stream because memory needs author history.

**Recommended sequence:** A → C → B (or A → B if time is short). Path A is fastest; C refines the same benchmark without new data collection; B is the research intensive step.

---

## Path A — Stage 3 RAG (no new labels)

### A1. Pre-flight

```bash
# Activate venv (Windows)
Hate_speach_env\Scripts\activate

# Install the new deps if you haven't yet
pip install -r requirements.txt
```

Confirm Ollama is running and `gpt-oss:120b-cloud` is reachable: `ollama list`.

### A2. Bring up Qdrant only (you don't need the rest of the stack for Path A)

```bash
docker-compose up -d qdrant
```

Verify: open http://localhost:6333/dashboard — Qdrant UI loads.

### A3. Seed Qdrant from the internship CSV

```bash
# Dry-run first to verify the CSV is well-formed:
python scripts/seed_rag_from_csv.py thesis_final_benchmark.csv

# Actually populate:
python scripts/seed_rag_from_csv.py thesis_final_benchmark.csv --apply
```

First run downloads the embedding model (~80 MB sentence-transformers/all-MiniLM-L6-v2). Subsequent runs are fast.

You should see something like `Indexed 459/459 records into Qdrant in 18.4s.`

### A4. Run leave-one-out RAG evaluation

```bash
# Smoke test on 5 rows first (no CSV write, no commitment):
python scripts/replay_with_rag.py --csv thesis_final_benchmark.csv --limit 5

# Then the full run:
python scripts/replay_with_rag.py --csv thesis_final_benchmark.csv --apply
```

Per-row output looks like:

```
[   1] csv-row-0                  baseline='False Positive' with_rag='False Positive' (5p, 5.8s)
[   2] csv-row-1                  baseline='False Positive' with_rag='Correct'        (5p, 6.4s) *DELTA*
[   3] csv-row-2                  baseline='Correct'        with_rag='Correct'        (5p, 7.1s)
```

Lines tagged `*DELTA*` are where RAG changed the verdict. The summary at the end:

```
Processed:                  459
Parse errors:               3
Baseline vs with_rag deltas: 64 (13.9%)
```

A delta rate between ~8% and ~20% is healthy. <5% means RAG had almost no effect (suspicious — check Qdrant has the seeded points); >30% means RAG is overwhelming the prompt (suspicious — likely precedents are too noisy).

Total wall-clock at default 0.5-second sleep + ~6-second LLM call per row: ~50 minutes for 459 rows. Use `--limit 100` if you just want a sample.

### A5. Open the notebook

```bash
jupyter notebook notebooks/evaluation.ipynb
# or open in VS Code
```

**Kernel → Restart & Run All.**

What to read:
- **§1** baseline still reproduces 71.0% / 93.5% — sanity check, unchanged.
- **§5.2** is the Stage 3 headline result.
- **§5.3** per-domain breakdown — where did RAG help?
- **§5.4** McNemar p-value.
- **§7** cross-pipeline comparison table — screenshot this for the supervisor.

### A6. (Optional) Share with the supervisor

A template message specifically for Path A:

> Prof. La Rosa,
>
> I implemented Retrieval-Augmented Moderation (your direction b). Qdrant + sentence-transformers (all-MiniLM-L6-v2) provide semantically-similar past cases as precedents to the Tier-2 judge. Evaluated via leave-one-out cross-validation on the 459-record internship benchmark — no new manual labels required.
>
> - **Baseline (no RAG):** X.X% 3-class accuracy
> - **With RAG:** Y.Y% 3-class accuracy
> - **Delta:** +Z.Z pp, McNemar p = P.PPPP
>
> Per-domain breakdown attached. Memory-augmented evaluation (direction a) is set up but requires a live data collection round, planned next.

---

## Path B — Stage 2 Temporal Memory (needs live data + labels)

You will:
1. Boot the infrastructure.
2. Boot the three pipeline processes.
3. Point the ingestion at a live YouTube stream.
4. Let it run, monitor in Kibana.
5. Stop, export to CSV, label `human_ground_truth` by hand.
6. Run `replay_with_memory.py` to populate the memory-augmented column.
7. Re-export + open the notebook + interpret.
8. Send the supervisor a result.

There is a troubleshooting appendix at the bottom of this file.

The steps below are numbered §0 → §11 for clarity within Path B.

---

## 0. Pre-flight checklist

Run these once before you start:

```bash
# Activate the venv (Windows)
Hate_speach_env\Scripts\activate

# Confirm Python sees the deps that landed in Stage 0.5 + Stage 2 + Stage 3 scaffolding
python -c "import pyyaml, ollama, kafka, elasticsearch, pytchat, sentence_transformers, qdrant_client, scipy; print('OK')"

# If anything is missing
pip install -r requirements.txt
```

Make sure:
- Docker Desktop is running.
- Ollama is running locally and `gpt-oss:120b-cloud` is reachable: `ollama list`.

---

## 1. Bring up the infrastructure

```bash
docker-compose up -d
```

This starts Kafka + Zookeeper + Spark + Elasticsearch + Kibana + Qdrant. Wait ~20 seconds for the cluster to settle.

Verify each component:

| Component | URL / command | What "healthy" looks like |
|---|---|---|
| Kibana | http://localhost:5601 | Page loads (might say "Index pattern not found" — that's fine). |
| Elasticsearch | `curl http://localhost:9200/_cat/health` | A line ending in `green` or `yellow`. |
| Qdrant | http://localhost:6333/dashboard | Qdrant UI loads. |
| Kafka | `docker exec kafka kafka-topics --bootstrap-server localhost:9093 --list` | Empty or `universal_stream`. |

---

## 2. (Optional but recommended) Import the Kibana dashboard

Once Kibana is up:

1. Stack Management → Saved Objects → Import.
2. Pick `dashboard.ndjson` in the repo root.
3. Open the new **Real-Time Analysis** dashboard. It will be empty until §4 produces records.

---

## 3. Boot the three pipeline processes

Open three terminals. Leave them running until §5.

### Terminal 1 — Tier-1 processor (DistilBERT)

```bash
python src/static_classifier/distilbert_processor.py
```

You should see `BERT Model Loaded successfully.` followed by a header line waiting for records.

### Terminal 2 — Producer (YouTube live chat)

```bash
python src/ingestion/omni_ingest.py
```

You will be prompted for a YouTube URL. See §4 for picking a good stream.

### Terminal 3 — Tier-2 batch judge (sweep)

Run periodically — every 1–5 minutes is plenty during data collection. With `MEMORY_ENABLED=True` (the default after Stage 2) the batch judge will use the memory-augmented prompt directly:

```bash
python src/agents/xai_batch_judge.py
```

This sweeps unreviewed records with `model_confidence < 0.80` and writes verdicts. Each record takes ~7 seconds (one LLM call). Stop it with Ctrl+C between sweeps.

---

## 4. Pick a stream and run it

Criteria for a useful live stream:
- **Open Live Chat** (no Members-Only, no Age-Restricted).
- **Active chat** — at least one message every few seconds.
- **Useful domain** — Gaming/Esports gives you sarcasm and slang; Politics/News gives you genuine toxicity; a Music DJ stream gives you mostly Normal records (useful as a control).

You'll want **at least three streams** spread across domains to get a meaningful Stage 2 evaluation. Aim for ~150–300 records per stream. 20-minute runs work well.

### How to run

In Terminal 2, paste the URL when prompted. The Context Agent will scrape the page, propose an `env_domain` (you'll see the raw LLM proposal printed), and start streaming chat messages into Kafka. You'll see lines like:

```
[GAMING/Esports] some_user: gg wp
[GAMING/Esports] some_other_user: that play was clean
```

Meanwhile Terminal 1 prints each Tier-1 verdict; Kibana's dashboard fills in real-time.

When you've collected enough, Ctrl+C the producer (Terminal 2). Leave Terminal 1 running until the Kafka backlog drains (the prints will slow to a stop).

---

## 5. Run the Tier-2 sweep

Now drain the low-confidence records:

```bash
python src/agents/xai_batch_judge.py
```

By default it processes 60 records per run. If you collected more, re-run a few times. You should see lines like:

```
--- RECORD 1/60 ---
USER: SomeUser | DOMAIN: Gaming (low strictness)
TEXT: "that ranger is so dead bruh"
DISTILBERT: HATE (Conf: 0.58)
-> Memory: 6 user msgs, 4 thread msgs
-> Fingerprint: Last 6 msgs: 6 Normal / 0 OFFENSIVE / 0 HATE. No flagged events in lookback window.
-> Thinking...
-> Agent Inference Time: 6.41 seconds
VERDICT: False Positive
REASON: ...
-> [SAVED TO DATABASE]
```

Stop with Ctrl+C when there's nothing left to review (or when you have enough — 200–300 reviewed records is plenty for a benchmark).

---

## 6. Export to CSV

```bash
python src/export_subset.py thesis_final_benchmark.csv
```

This writes a CSV in the repo root with one row per reviewed record and all the columns the notebook needs (including `message_id` and `timestamp` so `replay_with_memory.py` can match by exact ID later).

The `human_ground_truth` column is intentionally blank — you fill it in manually next.

---

## 7. Label `human_ground_truth` by hand

Open `thesis_final_benchmark.csv` in Excel, VS Code with the CSV-viewer extension, Google Sheets, or any spreadsheet tool. For each row, fill `human_ground_truth` with one of:

- `NORMAL`
- `OFFENSIVE`
- `HATE`

Tips to make this less painful:
- Sort by `env_domain` then by `text`. Same-domain records are easier to label in a flow.
- Trust the `model_label` column for obvious cases (long chains of `Normal` predictions are usually correct — spot-check a sample).
- Focus your attention on records where `agent_final_decision != "Correct"` — those are the cases the Stage 2 evaluation actually cares about.
- 200 records, ~10 seconds each = ~30 minutes of work.

Save the CSV when done.

---

## 8. Run the memory replay against the existing baseline

This step re-judges the records you just labelled, with the memory-augmented prompt, writing the verdicts to `agent_final_decision_with_memory` (not touching `agent_final_decision`):

```bash
# Smoke test first (no writes):
python scripts/replay_with_memory.py --csv thesis_final_benchmark.csv --limit 5

# Then for real:
python scripts/replay_with_memory.py --csv thesis_final_benchmark.csv --apply
```

You'll see per-record output like:

```
[   1] ChwKGkNQ-pOaV1Y8DFdbH... baseline='Correct'      with_memory='Correct'      (6u/4t, 5.2s)
[   2] ChwKGkNQa-pOaV1Y9CGdb... baseline='False Positive' with_memory='Correct'      (8u/5t, 6.1s) *DELTA*
```

Lines tagged `*DELTA*` are the records where the memory-augmented judge changed its mind vs the baseline — those are exactly the rows the notebook's §4.4 McNemar test will use.

At the end you'll see something like:

```
Processed:                     247
Parse errors:                  1
Baseline vs with-memory deltas: 38 (15.4%)
```

15% deltas is healthy. <5% means memory had little effect (suspicious — check that ES has enough history for the queries to find anything). >30% means memory dominated (also suspicious — likely the prompt is over-relying on context).

---

## 9. Re-export to include the new columns

```bash
python src/export_subset.py thesis_final_benchmark.csv
```

Open the CSV briefly — confirm `agent_final_decision_with_memory` is now populated. Note: this overwrites the file you hand-labelled, but the `human_ground_truth` column survives because the export reads it from ES (it was indexed when the live pipeline ran).

> If `human_ground_truth` comes back blank: you skipped writing it to ES. The simplest fix is to keep the labelled CSV from §7 as `thesis_final_benchmark_labeled.csv`, run the export to a different filename like `thesis_final_benchmark_v2.csv`, then `pandas.merge` the two on `message_id`. Future runs should use a Python script to push your labels back to ES — happy to write one when you hit this.

---

## 10. Open the notebook and evaluate

```bash
jupyter notebook notebooks/evaluation.ipynb
# or just open in VS Code
```

**Kernel → Restart & Run All.**

What to look for:
- **§1 baseline numbers** should still match the 71.0% / 93.5% from the internship report — they're computed from the same CSV columns the baseline used.
- **§4.2** is the headline result. Positive delta = memory helped.
- **§4.3** per-domain breakdown shows whether memory helped in Gaming (sarcasm), Politics (cumulative toxicity), or both.
- **§4.4** McNemar p-value. < 0.05 means the delta is unlikely to be chance.
- **§6** cross-pipeline comparison table is what you screenshot for the supervisor.

---

## 11. Share with the supervisor

A template message:

> Prof. La Rosa,
>
> Following the directions in your email I built the temporal-memory layer (RAM/conversational context, your point a) on top of the internship pipeline. The implementation enriches the Tier-2 judge prompt with the last 10 messages from the same author across all streams, the last 5 messages in the same chat thread, and a one-line behavioural fingerprint of the user's recent labelling pattern.
>
> I evaluated it on a new manually-labelled benchmark of N records collected across three domains (Gaming, Politics, Music). Result:
>
> - **Baseline (no memory):** X.X% 3-class accuracy
> - **With memory:** Y.Y% 3-class accuracy
> - **Delta:** +Z.Z pp, McNemar p = P.PPPP
>
> Per-domain breakdown: Gaming +A.A pp, Politics +B.B pp, Music +C.C pp.
>
> Full notebook + benchmark CSV are in the repo. Happy to walk through the methodology if useful.
>
> Next step on the roadmap is Retrieval-Augmented Moderation (your point b) — the Qdrant + sentence-transformers scaffolding is already in place, awaiting the same evaluation methodology.

Fill in N / X.X / Y.Y / Z.Z / P.PPPP / A.A / B.B / C.C from the notebook output.

---

## Path C — Stage 4 Multi-Agent Decomposition (optional follow-up)

**One monolithic Tier-2 judge → five specialist agents working in concert.**

This is the **advanced next step** after Stage 3 RAG proves its value. Decomposes the judge into:
- **Risk Scorer** — numeric 0–1 risk from retrieved precedents
- **Behavior Profiler** — user fingerprint + behavioral flags
- **Escalator** — decides human escalation vs auto-action
- **Supervisor** — reconciles Risk Scorer ↔ Profiler disagreement
- **Leader Agent** — orchestrator over the four specialists

Success criterion: multi-agent system out-performs Stage 3 monolith on precision (HATE class), recall (False Negatives), or escalation efficiency.

### C1. Prerequisites

Stages 1–3 must be complete:
- RAG corpus seeded into Qdrant (from Path A step 2)
- Memory enabled in `shared_utils/config.py` (`MEMORY_ENABLED="1"`)
- Benchmark CSV with `agent_final_decision_with_rag` already populated (from Path A step 4 or the eval notebook)

### C2. Build the specialist agents

Implement five new files in `src/agents/`:

```
src/agents/
  ├── risk_scorer.py                # scores 0-1 based on precedent similarity
  ├── behavior_profiler.py           # extracts user fingerprint from ES
  ├── escalator.py                   # human-review decision logic
  ├── supervisor.py                  # reconciliation when Risk ≠ Behavior
  └── leader_agent.py (refactored)   # orchestrator, not tool router
```

Each agent:
- Takes ES record + retrieved precedents + user history as input
- Returns structured JSON with `score`, `reasoning`, `confidence`
- Logs to ES document new fields: `agent_risk_score`, `agent_behavior_profile`, `agent_escalation_flag`, `agent_supervisor_note`

Pseudocode for `Risk Scorer`:

```python
def score_risk(record: dict, precedents: list[dict]) -> dict:
    """
    Input: the current moderation record + top-5 retrieved precedents (from RAG)
    Output: { "risk_score": 0-1, "precedent_matches": [...], "reasoning": "..." }
    
    Logic:
    - If precedent_label == "HATE" and text is similar (>0.7 cosine): risk += 0.3
    - If precedent had user escalation: risk += 0.2
    - Normalize to [0, 1]
    """
```

### C3. Refactor Leader Agent as orchestrator

Move from tool-call routing to agent orchestration:

```python
def orchestrate_multi_agent(record: dict) -> dict:
    """
    Phase 1: In parallel, call three specialist agents
      - risk_scorer.score_risk(record, precedents)
      - behavior_profiler.profile_user(record, user_history)
      - escalator.decide_escalation(record, risk_score, behavior_profile)
    
    Phase 2: If Risk Score and Behavior Profile disagree (>0.2 delta):
      - supervisor.reconcile(record, risk_output, behavior_output)
      - return supervisor's tiebreaker
    
    Phase 3: Synthesize final verdict + confidence
      - combine the four specialist outputs into structured JSON
      - write to ES with all reasoning chains
    """
```

### C4. Add Stage 4 evaluation to the notebook

In `notebooks/evaluation.ipynb`, add a new §6 section:

```python
# §6. Stage 4 Multi-Agent vs Stage 3 baseline
agent_final_decision = df['agent_final_decision_with_rag']  # baseline (monolith)
multi_agent_decision = df['multi_agent_verdict']              # new column
human_ground_truth = df['human_ground_truth']

# Compare
accuracy_monolith = (agent_final_decision == human_ground_truth).mean()
accuracy_multi_agent = (multi_agent_decision == human_ground_truth).mean()
delta = accuracy_multi_agent - accuracy_monolith

# McNemar test
from scipy.stats import mcnemar
table = confusion_matrix(agent_final_decision == human_ground_truth,
                         multi_agent_decision == human_ground_truth)
chi2, p_value = mcnemar(table)

print(f"Stage 3 (monolith):    {accuracy_monolith:.1%}")
print(f"Stage 4 (multi-agent): {accuracy_multi_agent:.1%}")
print(f"Delta: {delta:+.1pp}, McNemar p = {p_value:.4f}")
```

### C5. Replay Stage 4 against the benchmark

```bash
# Create a multi_agent_verdict column by running orchestrator on each row
python scripts/replay_with_multi_agent.py --csv thesis_benchmark_eval.csv --apply --force
```

Expected per-row output:

```
[   1] ChwK...  monolith='Correct' multi_agent='Correct' (risk=0.15, behav=0.12, escal=False, 8.2s)
[   2] ChwK...  monolith='False Positive' multi_agent='Correct' (risk=0.72, behav=0.68, escal=False, 9.1s) *DELTA*
```

### C6. Evaluate and report

```bash
jupyter notebook notebooks/evaluation.ipynb
# Kernel → Restart & Run All
# Screenshot §6 (multi-agent accuracy + McNemar p-value)
```

If multi-agent achieves p < 0.05 improvement, share this template message with your supervisor:

> Prof. La Rosa,
>
> I decomposed the monolithic Tier-2 judge from Stage 3 into a five-agent ensemble (Risk Scorer, Behavior Profiler, Escalator, Supervisor, Leader Orchestrator). The specialist agents coordinate on per-message risk assessment, behavioral flagging, and escalation routing.
>
> Evaluated on the 298-record benchmark via leave-one-out cross-validation:
>
> - **Stage 3 (monolith):** X.X% 3-class accuracy
> - **Stage 4 (multi-agent):** Y.Y% 3-class accuracy
> - **Delta:** +Z.Z pp, McNemar p = P.PPPP
>
> Per-agent reasoning is now traceable in the ES document; the Leader logs which specialist contributed the final verdict. Full implementation in `src/agents/{risk_scorer, behavior_profiler, escalator, supervisor}.py`.

---

## Troubleshooting

### "ImportError: No module named X"
`pip install -r requirements.txt`. The Stage 3 scaffolding added `sentence-transformers`, `qdrant-client`, `scipy`, `pyyaml` — easy to miss in an old venv.

### Producer crashes immediately with "Chat connection failed"
The YouTube stream has Live Chat disabled, restricted, or the URL is wrong. Pick a different stream — chat must be public.

### Tier-1 processor doesn't see any records
Producer is on the wrong topic or Kafka isn't running. Confirm Kafka with `docker exec kafka kafka-topics --bootstrap-server localhost:9093 --list`. You should see `universal_stream`.

### Kibana shows no records
Elasticsearch is unreachable or the processor failed to write. Look in Terminal 1 for `Kibana Error:` lines. Usually it's a network blip — restart `docker-compose restart elasticsearch`.

### Batch judge prints `LLM produced unparseable JSON twice in a row.`
The `gpt-oss:120b-cloud` model occasionally returns malformed JSON despite `format="json"`. The Stage 0 wrapper retries once; if it still fails the record is marked `Parsing Error`. Expected to be <2% of records.

### `replay_with_memory.py` says `message_id=... not found in ES`
Your CSV refers to records that no longer exist in ES (you wiped the index, or this CSV is from an older pipeline run). Re-export with §6 to get a CSV synced to current ES contents.

### `human_ground_truth` is blank after re-export in §9
Expected — the export pulls from ES, which doesn't have your manual labels. Either (a) write a tiny script that pushes your CSV labels back into ES via `es.update`, or (b) merge your labelled CSV with the re-exported CSV via `pd.merge` on `message_id`. Easiest is to keep the labelled CSV around forever and never let the export overwrite it.

### Qdrant doesn't start (Stage 3 scaffolding artefact)
Stage 2 evaluation does not need Qdrant. If `docker-compose up -d` fails on the Qdrant service specifically, you can ignore it for Stage 2 — `RAG_ENABLED` defaults to False and no agent will try to reach it.
