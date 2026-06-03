# Evaluation

This document records how the report's headline numbers were produced and how to reproduce them after any prompt or model change.

## Numbers cited in the report

| Metric | Value | Source |
|---|---|---|
| Tier-1 validation accuracy (Dataset A, 20% holdout) | 79.44% | DistilBERT training run (`src/Hate_speach_Project.ipynb`) |
| Tier-1 F1 (Dataset A) | 0.796 | Same |
| Classical LR baseline accuracy | 76% | Same notebook |
| Tier-1 average inference latency | 36.10 ms | `data/stream_log.csv` aggregation |
| Tier-2 average inference latency | 6951.81 ms (192.6×) | `agent_latency_seconds` in ES |
| Dataset B size | 459 low-confidence (<80%) records | `thesis_final_benchmark.csv` |
| Static vs Human accuracy (Dataset B) | 71.0% | `src/calculate_thesis_metrics.py` |
| Agent vs Human accuracy (Dataset B) | **93.5%** | Same |
| Static-Agent consensus | 68.4% | Same |
| Unanimous (all three) agreement | 67.1% | Same |

## The living evaluation notebook

The canonical way to recompute and extend these metrics is `notebooks/evaluation.ipynb`. It reproduces Tables 4, 6, 7, 8 of the report verbatim, and is structured so each future Stage appends one row to a shared results registry — the cross-stage comparison table at the bottom then shows whether the new Stage moved the needle.

Open it with any Jupyter-compatible environment (VSCode, JupyterLab, classic notebook). It needs no Docker, no Ollama, and no Elasticsearch for the Stage 0 cells — the benchmark CSV is frozen historical data.

```bash
# From the repo root:
jupyter notebook notebooks/evaluation.ipynb
# or simply open in VS Code
```

## Re-running the benchmark

### 1. Dataset B (`thesis_final_benchmark.csv`)

This file is the canonical hold-out set for Tier-2 evaluation: 459 manually-labelled low-confidence records exported from Elasticsearch.

It was produced by:

```bash
python src/export_subset.py
```

`export_subset.py` queries the live `real_time_analysis` index for records where `agent_reviewed == true` AND `agent_latency_seconds` exists, then writes the eight thesis-relevant fields to CSV. The `human_ground_truth` column is intentionally written as empty so the human auditor can label it in a spreadsheet without inheriting any AI hint.

### 2. Compute the metrics

```bash
python src/calculate_thesis_metrics.py
```

This reads the CSV, normalises label casing, prints:
- dataset composition by source domain
- label distribution per source (human / static / agent)
- examples of static hallucinations and agent failures

To get Tables 4, 6, 8 directly, the script needs to be extended (Stage 1 work — see [ROADMAP.md](ROADMAP.md)). For Stage 0 the numbers already in the report are reproducible by:

```python
import pandas as pd
df = pd.read_csv("thesis_final_benchmark.csv")
df['human_ground_truth'] = df['human_ground_truth'].fillna('NORMAL').str.strip().str.upper()
df['model_label'] = df['model_label'].str.strip().str.upper()
df['agent_final_decision'] = df['agent_final_decision'].str.strip().str.lower()

# Static accuracy
static_correct = (df['model_label'] == df['human_ground_truth']).sum()
print(f"Static vs Human: {static_correct}/{len(df)} = {static_correct/len(df):.1%}")

# Agent accuracy (decision == "correct" means agent agreed with static and was right;
# "false positive" means agent overturned static -> defaults to NORMAL;
# "false negative" means agent flagged a missed positive).
def agent_label(row):
    d = row['agent_final_decision']
    if d == 'correct':       return row['model_label']
    if d == 'false positive':return 'NORMAL'
    if d == 'false negative':return 'OFFENSIVE'  # conservative
    return row['model_label']

df['agent_pred'] = df.apply(agent_label, axis=1)
agent_correct = (df['agent_pred'] == df['human_ground_truth']).sum()
print(f"Agent vs Human: {agent_correct}/{len(df)} = {agent_correct/len(df):.1%}")
```

That snippet is the minimum reproducer for the 93.5% figure. Building it into a proper harness with confusion matrices, McNemar tests, per-domain breakdowns and ablation toggles is **Stage 1** work — do not cite new numbers in the thesis until that harness exists.

## After a prompt change

If you edit any prompt in `src/shared_utils/prompts.py`, the report's numbers no longer apply. Re-running them requires:

1. Either: replay Dataset B's raw texts back through the Tier-2 judge (faster) — needs Stage 1's harness.
2. Or: wipe `agent_*` fields in ES (`scripts/normalize_domains.py` is for taxonomy, not this — Stage 1 will add an `unreview_agent_audits.py`), rerun the live pipeline, regenerate Dataset B.

Until Stage 1 lands, the only safe statement is "the prompt change is in effect; the 93.5% figure must be re-measured before being cited."

## After a model change

Same rule. The report's numbers are bound to `gpt-oss:120b-cloud`. Swapping the model alias in `shared_utils/config.py::ACTIVE_MODEL` invalidates them.

## Per-stage target metrics

These are sketched in [ROADMAP.md](ROADMAP.md) and become the success criteria for each Stage.
