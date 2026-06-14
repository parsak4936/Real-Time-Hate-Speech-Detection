# Migration guide — do I need to wipe Elasticsearch?

**TL;DR:** Almost certainly **no**. Use Option A (in-place migration) unless you have a specific thesis reason for Option B (fresh start).

This document is the audit reference. Read it whenever you wonder "should I wipe ES?" or "did the migration work?".

---

## 1. The fields the new code expects

Every field added since the internship phase, named so you can grep for them:

### Added to the Universal Schema (Kafka payload) + ES document

| Field | Stage | Type | Strictly required? | Written by |
|---|---|---|---|---|
| `env_subgenre` | 0.5 | string | YES — pair with canonical split | producer (Context Agent) |
| `env_domain_raw` | 0.5 | string | no — but powers agentic-discovery analysis | producer |
| `env_domain_match` | 0.5 | string (`exact`/`alias`/`fuzzy`/`unknown`) | no — derivable from raw vs canonical | producer |
| `env_strictness_reasoning` | 0.5 | string | no — XAI nice-to-have | producer |
| `agent_memory_used` | 2 | bool | YES — A/B audit | `xai_batch_judge` |
| `agent_memory_user_msgs` | 2 | int | useful, derivable | `xai_batch_judge` |
| `agent_memory_thread_msgs` | 2 | int | useful, derivable | `xai_batch_judge` |
| `agent_memory_user_profile` | 2 | string | useful for audit | `xai_batch_judge` |
| `agent_final_decision_with_memory` | 2 | string | YES — measures memory's contribution | `replay_with_memory.py` only |
| `agent_explanation_with_memory` | 2 | string | YES for audit | `replay_with_memory.py` only |

### Added to evaluation CSV only (NOT in ES)

| Field | Stage | Written by |
|---|---|---|
| `agent_final_decision_with_rag` | 3 | `replay_with_rag.py` |
| `agent_explanation_with_rag` | 3 | `replay_with_rag.py` |
| `agent_retrieved_precedent_ids` | 3 | `replay_with_rag.py` |
| `agent_retrieval_count` | 3 | `replay_with_rag.py` |

**Honest count.** Of ~14 new fields, **3 are strictly required**:
- `env_subgenre`
- `agent_final_decision_with_memory`
- `agent_final_decision_with_rag`

Everything else is XAI / audit / measurement trail. You can strip them if you want a leaner schema, but they pay their way for thesis defensibility.

---

## 2. Why wiping is (probably) NOT necessary

| Concern | Reality |
|---|---|
| Old records have `env_domain="Gaming/Survival"` compound values | `scripts/normalize_domains.py --apply` fixes them in place — splits into `env_domain=Gaming` + `env_subgenre=Survival`. |
| Old records don't have `env_domain_raw` / `env_strictness_reasoning` | Missing fields don't break anything. ES aggregations skip them. New records will have them. |
| Will `replay_with_memory.py` overwrite the internship Tier-2 verdicts? | **No** — it writes to `agent_final_decision_with_memory` (new column). The original `agent_final_decision` is never touched. |
| Will `xai_batch_judge.py` re-judge old reviewed records with memory? | **No** — its ES query has `must_not: [{term: {agent_reviewed: true}}]`. Already-reviewed records are skipped. |
| Does Stage 3 RAG need fresh ES data? | **No** — RAG eval uses the CSV directly via `seed_rag_from_csv.py`. ES is bypassed. |
| Will the Leader Agent break on old records? | **No** — `search_tool` and `stats_tool` use `term` on `.keyword` which gracefully handles missing fields (records without `env_domain_raw` just don't appear in `env_domain_raw` aggregations). |

The only reason to wipe is **thesis purity**: you want every ES record to have been through the new agentic Context Agent prompt (so the agentic-discovery analysis covers all 18k records, not just new ones). That's a quality choice, not a correctness requirement.

---

## 3. Decision tree

```
Do you want every record under the new agentic Context Agent prompt?
├─ NO   → Option A: In-place migration (recommended)
└─ YES  → Option B: Wipe + re-collect

Are you in a hurry / running low on time before defence?
├─ YES  → Option A
└─ NO   → Either, but A is safer

Do you have the bandwidth to re-collect 18k records?
├─ NO   → Option A
└─ YES  → Either

Is your supervisor specifically asking for "full agentic discovery data"?
├─ NO   → Option A
└─ YES  → Option B
```

---

## Option A — In-place migration (recommended)

### Step 1 — Pre-flight (5 minutes)

```bash
# Verify the services are up
docker-compose ps                                   # Kafka, ES, Kibana, Qdrant all "Up"
curl -s http://localhost:9200/_cat/health           # green or yellow
ollama list                                         # gpt-oss:120b-cloud appears
```

**Audit checkpoint:**
- ES is reachable, returns a non-empty cluster health
- Ollama serves the model name in `shared_utils/config.py::ACTIVE_MODEL`

### Step 2 — Inspect current state

```bash
# How many records exist?
curl -s http://localhost:9200/real_time_analysis/_count

# What does one record look like?
python src/agents/check_db_size.py

# How many already-reviewed records (these have agent_final_decision)?
curl -s -X GET "http://localhost:9200/real_time_analysis/_count" \
    -H 'Content-Type: application/json' \
    -d '{"query": {"term": {"agent_reviewed": true}}}'
```

**Audit checkpoint:**
- Total count matches your expectation (~18k)
- Reviewed count is in the range you remember (~459 manually labeled + whatever else)
- Sample record has the OLD schema (no `env_domain_raw`, possibly compound `env_domain`)

### Step 3 — Migrate compound domains in place

```bash
# Preview only — see what would change without writing
python scripts/normalize_domains.py

# Read the output carefully. You'll see lines like:
#   env_domain='Gaming/Survival'   sub=''   ->  env_domain='Gaming' sub='Survival'

# If the preview looks right, write:
python scripts/normalize_domains.py --apply
```

**Audit checkpoint after this step:**
- No records have `/` in `env_domain` anymore: `curl -s "http://localhost:9200/real_time_analysis/_search?q=env_domain:*\\/*&size=0"` → `hits.total.value` should be 0
- Aggregating on `env_domain.keyword` returns a small clean set (Gaming, Politics, News, etc.) — not 50 fragmented buckets

### Step 4 — Verify the live pipeline can ingest new data with the new schema

```bash
# In one terminal:
python src/static_classifier/distilbert_processor.py

# In another terminal, point at any live YouTube stream:
python src/ingestion/omni_ingest.py
# (the Context Agent runs. Look for: "LLM raw proposal: '...'" in the output)
```

Let it run for 1-2 minutes. Stop both with Ctrl+C.

**Audit checkpoint:**
- The producer logs `Context Locked: [Gaming/...]` style line — the agentic Context Agent fired.
- ES has a few new records with all the new fields:
  ```bash
  curl -s "http://localhost:9200/real_time_analysis/_search?q=env_domain_raw:*&size=1&sort=timestamp:desc"
  ```
  Should return a record whose `_source` includes `env_domain_raw`, `env_domain_match`, `env_strictness_reasoning`.

If this works, the live pipeline is healthy under the new schema. Continue.

### Step 5 — Run Stage 2 evaluation against existing reviewed records

Your 459-record internship benchmark CSV is still labeled. `replay_with_memory.py` re-judges them with memory and writes to the new `_with_memory` column (NEVER overwrites the original):

```bash
# Smoke test on 5 records
python scripts/replay_with_memory.py --csv thesis_final_benchmark.csv --limit 5

# If sane, full run
python scripts/replay_with_memory.py --csv thesis_final_benchmark.csv --apply
```

**Audit checkpoint after this step:**
- ES records corresponding to the CSV now have `agent_final_decision_with_memory` populated.
- Verify one:
  ```bash
  curl -s "http://localhost:9200/real_time_analysis/_search?q=_exists_:agent_final_decision_with_memory&size=1"
  ```
- Re-export the CSV: `python src/export_subset.py thesis_final_benchmark.csv` — open it, confirm the new column appears.
- Open `notebooks/evaluation.ipynb` → Restart & Run All → §4 produces real numbers instead of "Skipped".

### Step 6 — Run Stage 3 RAG evaluation (no ES dependency)

```bash
# 1. Make sure Qdrant is up
docker-compose up -d qdrant

# 2. Seed Qdrant from the labelled CSV
python scripts/seed_rag_from_csv.py thesis_final_benchmark.csv --apply

# 3. Leave-one-out replay
python scripts/replay_with_rag.py --csv thesis_final_benchmark.csv --apply
```

**Audit checkpoint after this step:**
- Qdrant dashboard at http://localhost:6333/dashboard shows ~459 points in `moderation_records`.
- CSV has `agent_final_decision_with_rag` populated.
- Notebook §5 produces real numbers.

### Step 7 — Cross-check the cross-pipeline table

In the notebook §7 ("Cross-pipeline comparison"), you should see 4 rows now:

| Variant | Expected ballpark |
|---|---|
| Tier-1 baseline (DistilBERT only) | 71.0% |
| Tier-1 + Tier-2 baseline (no memory) | 93.5% |
| Tier-1 + Tier-2 with memory | new measurement |
| Tier-1 + Tier-2 with RAG (no memory) | new measurement |

If the first two reproduce 71.0% and 93.5%, the historical baseline is intact. If the next two move the needle one way or the other, that's your new finding.

---

## Option B — Wipe and start fresh

Use only if you specifically want every ES record under the new agentic schema.

### Step 1 — Safety backup of the labelled benchmark

```bash
# Your 459 manually labelled records live in thesis_final_benchmark.csv
# Verify it's labeled:
python -c "
import pandas as pd
df = pd.read_csv('thesis_final_benchmark.csv')
labeled = df['human_ground_truth'].astype(str).str.strip().ne('').sum()
print(f'{labeled}/{len(df)} records have human_ground_truth')
"
# Should print: 459/459 records have human_ground_truth
```

**Do NOT proceed if the count is wrong.** Restore from a backup first.

### Step 2 — Wipe the ES index

```bash
python src/reset_db.py --yes
```

**Audit checkpoint:**
- `curl -s http://localhost:9200/_cat/indices/real_time_analysis` returns nothing (or 404).
- Kibana dashboards go blank — expected.

### Step 3 — (Optional) wipe the Qdrant collection too

```bash
curl -X DELETE "http://localhost:6333/collections/moderation_records"
```

### Step 4 — Re-ingest live data under the new agentic Context Agent

Run the producer against multiple streams to rebuild your corpus. Aim for at least 2,000 records across 3+ domains.

```bash
# Process
python src/static_classifier/distilbert_processor.py

# Producer (run multiple times, one per stream)
python src/ingestion/omni_ingest.py
```

**Audit checkpoint:**
- Spot-check Kibana — records flowing in.
- New records have `env_domain_raw` populated. Open one in Kibana Discover and verify the new agentic fields exist.

### Step 5 — Re-run the Tier-2 batch judge to populate verdicts

```bash
python src/agents/xai_batch_judge.py
```

This will iterate the 60 most recent unreviewed records under confidence 0.80 and judge each one with memory (since `MEMORY_ENABLED=True`).

### Step 6 — Export a NEW benchmark CSV

```bash
python src/export_subset.py thesis_final_benchmark_v2.csv
```

This pulls all reviewed records into a CSV. **The `human_ground_truth` column will be empty** — that's the work you have to do manually for a fresh evaluation. Path B's cost.

### Step 7 — Label, then run Stage 2 and Stage 3 evaluations

This is just Path B of `docs/RUNBOOK.md` from §6 onwards. Manually label, run `replay_with_memory.py` on the new CSV, then `seed_rag_from_csv.py` + `replay_with_rag.py` on the new CSV.

**Caveat:** Your old 93.5% baseline (from the internship report) was measured on the OLD 459 records. After wiping you don't have those records' history any more. The new baseline number won't be directly comparable to the report.

---

## Recommendation

**Use Option A unless the prof specifically asks for the full-agentic-corpus story.** Option A:
- preserves your 18k records and the 459 labels
- gives you a measured Stage 2 result (memory delta vs internship baseline)
- gives you a measured Stage 3 result (RAG delta on the same labels)
- keeps the internship report's 93.5% reproducible forever
- takes ~1 hour of LLM runtime vs Option B's days of labeling

Option B has one (real) advantage: every record in the corpus will have an `env_domain_raw` populated by the new agentic LLM, so the "we measured agentic discovery on N records" claim in the thesis can use N=18k+ instead of N=(only new records since the change).

If that statistic matters for your defence, take Option B. Otherwise, take Option A.

---

## Final sanity checks (run these after either option)

```bash
# 1. Every Python file compiles
python -m py_compile $(find src scripts -name "*.py")

# 2. Schema-aware: dump one ES record and read its keys
python src/agents/check_db_size.py

# 3. Taxonomy: 16 canonicals, no broken fuzzy threshold
python -c "
import sys; sys.path.insert(0, 'src')
import shared_utils.taxonomy as t
t._CACHED_TAXONOMY = None
print(len(t.canonical_names()), 'canonicals')
"

# 4. Notebook regenerates from build script
python scripts/_build_eval_notebook.py

# 5. Operator dashboard launches
streamlit run scripts/operator_dashboard.py
# (open http://localhost:8501, verify all three health indicators are green)
```

If all five pass, your pipeline is healthy under whichever option you chose.
