"""
One-shot generator for notebooks/evaluation.ipynb.

This file exists only because hand-crafting a 27-cell .ipynb JSON blob is
error-prone. After running it once, the generated notebook is the artefact
the user maintains; this script can safely be deleted or kept as a
regenerator if a large structural change is needed later.

Usage:
    python scripts/_build_eval_notebook.py
"""

import json
import pathlib
import textwrap

cells = []


def md(text: str) -> None:
    cells.append({"cell_type": "markdown", "metadata": {}, "source": textwrap.dedent(text).strip()})


def code(text: str) -> None:
    cells.append(
        {
            "cell_type": "code",
            "metadata": {},
            "execution_count": None,
            "outputs": [],
            "source": textwrap.dedent(text).strip(),
        }
    )


# ============================================================================
md("""
    # Pipeline Evaluation Notebook

    Living notebook that tracks how each Stage of the pipeline performs against
    the frozen baseline. Re-run after every Stage and append a new section. The
    cross-stage comparison at the bottom shows whether the new work moved the
    needle.

    **No Docker / no Ollama / no Elasticsearch are required for the Stage 0
    baseline cells below.** `thesis_final_benchmark.csv` already contains the
    frozen Tier-1 (`model_label`) and Tier-2 (`agent_final_decision`) verdicts
    from the internship benchmark, plus the manually-labelled
    `human_ground_truth`. Everything in §1 runs purely offline.

    Live-infra requirements only appear when a future Stage needs to *generate*
    new benchmark data — those cells will carry a `[LIVE INFRA]` tag in their
    header.

    ## How to extend this notebook

    1. When a Stage lands, append a new top-level section
       (e.g. `## 4. Stage 2 — Temporal Memory`).
    2. Reuse the helpers defined in §0
       (`load_benchmark`, `agent_effective_label`, `compute_three_class_accuracy`, …).
    3. Add the resulting metrics dict to `RESULTS_REGISTRY` near the end.
    4. The cross-stage comparison table picks it up automatically.

    Related docs: [`docs/ROADMAP.md`](../docs/ROADMAP.md),
    [`docs/EVAL.md`](../docs/EVAL.md), [`docs/PROMPTS.md`](../docs/PROMPTS.md).
""")

# ============================================================================
md("## 0. Setup")

code("""
    import os
    from collections import OrderedDict

    import numpy as np
    import pandas as pd


    # Path resolution — works whether the notebook is opened from the repo root
    # or from notebooks/.
    def _find_benchmark():
        for candidate in ("thesis_final_benchmark.csv", "../thesis_final_benchmark.csv"):
            if os.path.exists(candidate):
                return candidate
        raise FileNotFoundError(
            "Could not find thesis_final_benchmark.csv — run this notebook from the "
            "repo root or from notebooks/."
        )


    BENCHMARK_CSV = _find_benchmark()
    print(f"Benchmark: {BENCHMARK_CSV}")

    # Closed taxonomy (mirrors src/shared_utils/prompts.py::ENV_DOMAINS).
    ENV_DOMAINS = [
        "Gaming", "Politics", "News", "Music", "Sports",
        "Education", "Entertainment", "Technology", "Lifestyle", "General",
    ]

    # Tier-1 label space.
    LABEL_CLASSES = ["NORMAL", "OFFENSIVE", "HATE"]
""")

code("""
    def load_benchmark(path=BENCHMARK_CSV):
        \"\"\"Load + normalise the benchmark CSV. Returns a clean DataFrame.\"\"\"
        df = pd.read_csv(path)
        df["human_ground_truth"] = (
            df["human_ground_truth"].fillna("NORMAL").astype(str).str.strip().str.upper()
        )
        df["model_label"] = df["model_label"].astype(str).str.strip().str.upper()
        df["agent_final_decision"] = (
            df["agent_final_decision"].astype(str).str.strip().str.lower()
        )
        df["env_domain"] = df["env_domain"].fillna("Unknown").astype(str)
        return df


    def main_domain(raw):
        \"\"\"Collapse the legacy open-taxonomy 'Gaming/Survival' to 'Gaming'.\"\"\"
        if pd.isna(raw):
            return "Unknown"
        return str(raw).split("/")[0].strip() or "Unknown"


    def agent_effective_label(model_label, agent_decision):
        \"\"\"
        Map (Tier-1 label, Tier-2 verdict) -> effective Tier-2 prediction.

        - 'correct'        -> keep the Tier-1 label
        - 'false positive' -> NORMAL    (Tier-2 cleared the static flag)
        - 'false negative' -> OFFENSIVE (Tier-2 says static missed; conservative
                                         choice — Report Table 4 shows only
                                         2/459 Agent-Hate predictions, so HATE
                                         is rarely the right flip.)
        - anything else (parsing errors) -> keep Tier-1 label
        \"\"\"
        if agent_decision == "correct":
            return model_label
        if agent_decision == "false positive":
            return "NORMAL"
        if agent_decision == "false negative":
            return "OFFENSIVE"
        return model_label


    def compute_three_class_accuracy(predictions, ground_truth):
        return float((predictions == ground_truth).sum()) / len(ground_truth)


    def compute_binary_accuracy(predictions, ground_truth, toxic={"HATE", "OFFENSIVE"}):
        \"\"\"Accuracy when collapsing labels to (normal vs toxic).\"\"\"
        pred_b = predictions.isin(toxic)
        gt_b = ground_truth.isin(toxic)
        return float((pred_b == gt_b).sum()) / len(ground_truth)


    def confusion_matrix(predictions, ground_truth, classes=LABEL_CLASSES):
        cm = pd.crosstab(
            ground_truth, predictions,
            rownames=["Human"], colnames=["Predicted"], dropna=False,
        )
        return cm.reindex(index=classes, columns=classes, fill_value=0)
""")

# ============================================================================
md("## 1. Stage 0 — Baseline: Static vs Agent vs Human")
md("### 1.1 Load benchmark")

code("""
    df = load_benchmark()
    print(f"Benchmark size: {len(df)} records")
    print(f"Columns: {list(df.columns)}")
    df.head(3)
""")

md("### 1.2 Class distribution — reproduces Report Table 4")

code("""
    df["agent_pred"] = df.apply(
        lambda r: agent_effective_label(r["model_label"], r["agent_final_decision"]),
        axis=1,
    )

    table4 = pd.DataFrame({
        "Static Classifier": df["model_label"].value_counts().reindex(LABEL_CLASSES, fill_value=0),
        "Agentic Auditor":   df["agent_pred"].value_counts().reindex(LABEL_CLASSES, fill_value=0),
        "Human Expert":      df["human_ground_truth"].value_counts().reindex(LABEL_CLASSES, fill_value=0),
    })
    table4
""")

md("### 1.3 Agent decision breakdown — reproduces Report Table 6")

code("""
    agent_breakdown = df["agent_final_decision"].value_counts()
    agent_breakdown.name = "Sample Count"
    print(agent_breakdown.to_string())
    print(f"\\nTotal Evaluated: {len(df)}")
""")

md("### 1.4 Three-way accuracy — reproduces Report Table 8")

code("""
    static_acc = compute_three_class_accuracy(df["model_label"], df["human_ground_truth"])
    agent_acc = compute_three_class_accuracy(df["agent_pred"], df["human_ground_truth"])
    static_agent_consensus = compute_three_class_accuracy(df["model_label"], df["agent_pred"])
    unanimous = (
        (df["model_label"] == df["agent_pred"]) &
        (df["agent_pred"] == df["human_ground_truth"])
    ).sum() / len(df)
    agent_human_static_failed = (
        (df["agent_pred"] == df["human_ground_truth"]) &
        (df["model_label"] != df["human_ground_truth"])
    ).sum() / len(df)

    agreement = pd.Series({
        "Human vs Agent  (Agent Accuracy, 3-class)":  agent_acc,
        "Human vs Static (Static Accuracy, 3-class)": static_acc,
        "Static vs Agent (AI Consensus)":             static_agent_consensus,
        "Unanimous (all 3 match)":                    unanimous,
        "Agent & Human Match (Static Failed)":        agent_human_static_failed,
    })
    agreement.apply(lambda x: f"{x:.1%}")
""")

md("### 1.5 Per-domain accuracy")
md(
    "Uses `main_domain()` to collapse the legacy open-taxonomy values "
    "(`Gaming/Survival` → `Gaming`) so the breakdown matches the closed "
    "taxonomy introduced in Stage 0."
)

code("""
    df["main_domain"] = df["env_domain"].apply(main_domain)

    def _row(g):
        s_acc = compute_three_class_accuracy(g["model_label"], g["human_ground_truth"])
        a_acc = compute_three_class_accuracy(g["agent_pred"], g["human_ground_truth"])
        return pd.Series({
            "n": len(g),
            "Static acc": s_acc,
            "Agent acc":  a_acc,
            "Delta (Agent - Static)": a_acc - s_acc,
        })

    per_domain = (
        df.groupby("main_domain")
        .apply(_row)
        .sort_values("n", ascending=False)
    )
    per_domain
""")

md("### 1.6 Confusion matrices")

code("""
    print("Static (Tier-1 DistilBERT) vs Human:")
    print(confusion_matrix(df["model_label"], df["human_ground_truth"]).to_string())

    print("\\nAgent (Tier-2) vs Human:")
    print(confusion_matrix(df["agent_pred"], df["human_ground_truth"]).to_string())
""")

md("### 1.7 Latency — reproduces Report Table 7")
md(
    "Both numbers are means over the benchmark records. The 192.6× overhead "
    "the report cites is the per-record cost the asynchronous Tier-2 sweep "
    "incurs — it does not affect the user-facing Tier-1 throughput since "
    "Tier-2 runs offline."
)

code("""
    t1_ms = df["processing_time_ms"].dropna().mean()
    t2_ms = (df["agent_latency_seconds"].dropna() * 1000).mean()

    latency = pd.Series({
        "Tier-1 (Static) — mean ms":  f"{t1_ms:.2f} ms",
        "Tier-2 (Agent) — mean ms":   f"{t2_ms:.2f} ms",
        "Overhead (Tier-2 / Tier-1)": f"{t2_ms / t1_ms:.1f}x",
    })
    print(latency.to_string())
""")

# ============================================================================
md("## 2. DistilBERT training reference")
md(
    "Numbers below come from `src/Hate_speach_Project.ipynb` and Internship "
    "Report §4.1–4.2. They describe Tier-1 itself — independent of this "
    "notebook's CSV — and are kept here as documented constants so the "
    "thesis can cite a single source. **Do not** re-run training from this "
    "notebook; the GPU run is hours-long and the artefact is already in "
    "`models/bert_final/`."
)

code("""
    DISTILBERT_TRAINING = {
        "dataset_size_total":         52972,
        "dataset_train_subset":       43000,
        "train_val_split":            "80/20",
        "epochs":                     2,
        "learning_rate":              5e-5,
        "weight_decay":               0.01,
        "warmup_steps":               100,
        "max_token_length":           128,
        "train_batch_size":           8,
        "eval_batch_size":            16,
        "optimizer":                  "AdamW",
        "val_accuracy":               0.7944,
        "val_f1":                     0.796,
        "classical_lr_accuracy":      0.76,
        "classical_lr_hate_f1":       0.66,
        "gpu":                        "NVIDIA GTX 1650 (4GB VRAM)",
    }
    pd.Series(DISTILBERT_TRAINING)
""")

# ============================================================================
md("## 3. Stage results registry")
md(
    "Every Stage appends one row here. Stage 0 has two: the static baseline "
    "(Tier-1 only) and the hybrid (Tier-1 + Tier-2 internship verdicts). "
    "Future stages mutate `RESULTS_REGISTRY` in their own cell, then the "
    "cross-stage table at the bottom picks the new row up automatically."
)

code("""
    RESULTS_REGISTRY = OrderedDict()

    RESULTS_REGISTRY["Stage 0 — Static (Tier-1)"] = {
        "accuracy_3class":  static_acc,
        "accuracy_binary":  compute_binary_accuracy(df["model_label"], df["human_ground_truth"]),
        "mean_latency_ms":  t1_ms,
        "n_records":        len(df),
        "notes":            "DistilBERT alone, no Tier-2 overlay",
    }

    RESULTS_REGISTRY["Stage 0 — Static + Agent (Tier-1 + Tier-2)"] = {
        "accuracy_3class":  agent_acc,
        "accuracy_binary":  compute_binary_accuracy(df["agent_pred"], df["human_ground_truth"]),
        "mean_latency_ms":  t1_ms + t2_ms,
        "n_records":        len(df),
        "notes":            "Hybrid pipeline, frozen internship verdicts (gpt-oss:120b-cloud)",
    }

    # ----------------------------------------------------------------------
    # Future stages append entries below this line. Example:
    #
    # RESULTS_REGISTRY["Stage 2 — + Temporal Memory"] = {...}
    # RESULTS_REGISTRY["Stage 3 — + RAG"]              = {...}
    # ----------------------------------------------------------------------

    pd.DataFrame(RESULTS_REGISTRY).T
""")

# ============================================================================
md("## 4. Template — adding a future Stage")
md(
    "Copy the cell below into a new section when a Stage lands. The "
    "comments mark exactly what each subsequent Stage needs to change."
)

code("""
    # ----------------------------------------------------------------------
    # TEMPLATE — duplicate this cell into its own section for each Stage.
    # ----------------------------------------------------------------------
    #
    # # Stage N — <name>
    #
    # # 1. Load the Stage-N CSV.
    # #    - If the Stage only modifies the agent verdict (prompt/model change),
    # #      re-run the live pipeline against the SAME texts and export with:
    # #          python src/export_subset.py
    # #    - If the Stage adds new data, export a fresh CSV with a stage suffix.
    # #
    # # [LIVE INFRA] needed only when generating the new CSV; not when reading it.
    # stage_n_df = load_benchmark("stage_N_benchmark.csv")
    #
    # # 2. Compute the agent's effective prediction.
    # stage_n_df["agent_pred"] = stage_n_df.apply(
    #     lambda r: agent_effective_label(r["model_label"], r["agent_final_decision"]),
    #     axis=1,
    # )
    #
    # # 3. Compute metrics.
    # acc_3 = compute_three_class_accuracy(stage_n_df["agent_pred"], stage_n_df["human_ground_truth"])
    # acc_b = compute_binary_accuracy(stage_n_df["agent_pred"], stage_n_df["human_ground_truth"])
    # t1 = stage_n_df["processing_time_ms"].dropna().mean()
    # t2 = (stage_n_df["agent_latency_seconds"].dropna() * 1000).mean()
    #
    # # 4. Register.
    # RESULTS_REGISTRY["Stage N — <name>"] = {
    #     "accuracy_3class":  acc_3,
    #     "accuracy_binary":  acc_b,
    #     "mean_latency_ms":  t1 + t2,
    #     "n_records":        len(stage_n_df),
    #     "notes":            "<what changed since the previous Stage>",
    # }
    #
    # pd.DataFrame(RESULTS_REGISTRY).T
""")

# ============================================================================
md("## 5. Cross-stage comparison")
md(
    "Final readout. Re-render after any Stage appends to `RESULTS_REGISTRY`. "
    "When a Stage's row appears here, the thesis can cite the delta from the "
    "previous row as that Stage's contribution."
)

code("""
    comparison = pd.DataFrame(RESULTS_REGISTRY).T.copy()
    comparison["accuracy_3class"] = comparison["accuracy_3class"].astype(float).apply(lambda x: f"{x:.1%}")
    comparison["accuracy_binary"] = comparison["accuracy_binary"].astype(float).apply(lambda x: f"{x:.1%}")
    comparison["mean_latency_ms"] = comparison["mean_latency_ms"].astype(float).apply(lambda x: f"{x:.1f} ms")
    comparison
""")

# ============================================================================
notebook = {
    "cells": cells,
    "metadata": {
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3",
        },
        "language_info": {
            "name": "python",
            "version": "3.10",
        },
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

out_path = pathlib.Path(__file__).resolve().parents[1] / "notebooks" / "evaluation.ipynb"
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(json.dumps(notebook, indent=1, ensure_ascii=False), encoding="utf-8")
print(f"Wrote {out_path} ({len(cells)} cells)")
