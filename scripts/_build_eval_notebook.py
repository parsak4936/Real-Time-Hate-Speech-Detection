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

    Living notebook that tracks how each layer of the moderation pipeline
    performs against the original internship baseline. Every new feature
    (temporal memory, RAG, multi-agent, …) appends one new section here so
    we can see whether the change moved the needle.

    **No Docker / no Ollama / no Elasticsearch are required for the baseline
    cells in §1.** `thesis_final_benchmark.csv` already contains the frozen
    Tier-1 (`model_label`) and Tier-2 (`agent_final_decision`) verdicts from
    the internship benchmark, plus the manually-labelled `human_ground_truth`.
    Everything in §1 runs purely offline.

    Live-infra requirements only appear when a future section needs to
    *generate* new benchmark data — those cells will carry a `[LIVE INFRA]`
    tag in their header.

    ## How to extend this notebook

    1. When new pipeline work lands, append a new top-level section
       (e.g. `## 5. Retrieval-Augmented Moderation`).
    2. Reuse the helpers defined in §0
       (`load_benchmark`, `agent_effective_label`, `compute_three_class_accuracy`, …).
    3. Add the resulting metrics dict to `RESULTS_REGISTRY` near the end.
    4. The cross-stage comparison table picks it up automatically.

    Related docs: [`docs/ROADMAP.md`](../docs/ROADMAP.md) (planning lens with
    numbered stages), [`docs/EVAL.md`](../docs/EVAL.md), [`docs/PROMPTS.md`](../docs/PROMPTS.md).
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
md("## 1. Baseline — Static (Tier-1) vs Agent (Tier-2) vs Human")
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

md("### 1.8 Per-platform breakdown — multi-platform generalisation evidence")
md(
    "Splits the benchmark by `source_platform` (YouTube / Twitch / Reddit) and "
    "shows static + agent accuracy per platform. If accuracy stays consistent "
    "across platforms, that's quantitative evidence for the report's "
    "'platform-agnostic Trust & Safety pipeline' claim. If a particular "
    "platform tanks, that's also publishable — 'cross-platform transfer is "
    "weakest on Twitch due to emote density', etc."
)

code("""
    if "source_platform" in df.columns:
        def _platform_row(g):
            s_acc = compute_three_class_accuracy(g["model_label"], g["human_ground_truth"])
            a_acc = compute_three_class_accuracy(g["agent_pred"], g["human_ground_truth"])
            return pd.Series({
                "n":             len(g),
                "Static acc":    s_acc,
                "Agent acc":     a_acc,
                "Delta (pp)":    (a_acc - s_acc) * 100,
            })

        per_platform = (
            df.groupby("source_platform")
            .apply(_platform_row)
            .sort_values("n", ascending=False)
        )
        per_platform
    else:
        print("source_platform column missing — older benchmark CSV. Re-export with src/export_subset.py or scripts/sample_for_eval.py.")
""")

md("### 1.9 Tier-1 confusion matrix")

code("""
    print("Static (Tier-1 DistilBERT) confusion matrix:")
    print(confusion_matrix(df["model_label"], df["human_ground_truth"]).to_string())
    print()
    print("Agent (Tier-2 baseline) confusion matrix:")
    print(confusion_matrix(df["agent_pred"], df["human_ground_truth"]).to_string())
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
md("## 3. Pipeline results registry")
md(
    "Each pipeline variant we evaluate appends one row here. The baseline has "
    "two: Tier-1 alone (DistilBERT) and the hybrid (Tier-1 + Tier-2 internship "
    "verdicts). Future sections — Temporal Memory in §4, then Retrieval-Augmented "
    "Moderation, Multi-Agent, etc. — mutate `RESULTS_REGISTRY` in their own cell. "
    "The cross-stage table at the bottom of the notebook picks new rows up "
    "automatically."
)

code("""
    RESULTS_REGISTRY = OrderedDict()

    RESULTS_REGISTRY["Tier-1 baseline (DistilBERT only)"] = {
        "accuracy_3class":  static_acc,
        "accuracy_binary":  compute_binary_accuracy(df["model_label"], df["human_ground_truth"]),
        "mean_latency_ms":  t1_ms,
        "n_records":        len(df),
        "notes":            "DistilBERT alone, no Tier-2 overlay",
    }

    RESULTS_REGISTRY["Tier-1 + Tier-2 baseline (no memory)"] = {
        "accuracy_3class":  agent_acc,
        "accuracy_binary":  compute_binary_accuracy(df["agent_pred"], df["human_ground_truth"]),
        "mean_latency_ms":  t1_ms + t2_ms,
        "n_records":        len(df),
        "notes":            "Hybrid pipeline, frozen internship verdicts (gpt-oss:120b-cloud)",
    }

    # ----------------------------------------------------------------------
    # Future pipeline variants append entries below this line. Example:
    #
    # RESULTS_REGISTRY["Tier-1 + Tier-2 with memory"]      = {...}
    # RESULTS_REGISTRY["Tier-1 + Tier-2 with memory + RAG"] = {...}
    # ----------------------------------------------------------------------

    pd.DataFrame(RESULTS_REGISTRY).T
""")

# ============================================================================
md("## 4. Temporal Memory (Tier-2 with conversational context)")
md(
    "This section evaluates the memory-augmented Tier-2 judge: instead of "
    "scoring each message in isolation, the judge sees the author's recent "
    "history, the same thread's last few messages, and a one-line "
    "behavioural fingerprint. The hypothesis is that this context lets the "
    "judge distinguish a normally-Normal user posting one suspicious-looking "
    "message (likely sarcasm) from a user with a pattern of toxic posts "
    "(likely genuine hostility), addressing the implicit-bias blindness "
    "failure mode flagged in Report §6.3.\n\n"
    "**Prerequisite — populate `agent_final_decision_with_memory` first.** "
    "This section reads that column from the same benchmark CSV. Generate it "
    "by running:\n"
    "```bash\n"
    "python scripts/replay_with_memory.py --csv thesis_final_benchmark.csv --apply\n"
    "python src/export_subset.py thesis_final_benchmark.csv\n"
    "```\n"
    "If you have not run the replay yet, the cells below print a friendly "
    "message and skip — the §1 baseline numbers stay valid regardless."
)

md("### 4.1 Re-load benchmark and check for memory-augmented verdicts")

code("""
    df_eval = load_benchmark()
    has_memory_verdicts = (
        "agent_final_decision_with_memory" in df_eval.columns
        and df_eval["agent_final_decision_with_memory"].astype(str).str.strip().ne("").any()
    )

    if not has_memory_verdicts:
        print("Memory-augmented verdicts NOT FOUND in the benchmark CSV.")
        print("Run `python scripts/replay_with_memory.py --csv thesis_final_benchmark.csv --apply`")
        print("then `python src/export_subset.py thesis_final_benchmark.csv` to populate them.")
    else:
        df_eval["agent_final_decision_with_memory"] = (
            df_eval["agent_final_decision_with_memory"].astype(str).str.strip().str.lower()
        )
        df_eval["agent_pred_baseline"] = df_eval.apply(
            lambda r: agent_effective_label(r["model_label"], r["agent_final_decision"]),
            axis=1,
        )
        df_eval["agent_pred_with_memory"] = df_eval.apply(
            lambda r: agent_effective_label(r["model_label"], r["agent_final_decision_with_memory"]),
            axis=1,
        )
        print(f"Memory-augmented verdicts present on {len(df_eval)} records. Comparison ready.")
""")

md("### 4.2 Accuracy delta — baseline vs with-memory vs Human")

code("""
    if has_memory_verdicts:
        baseline_acc_3class = compute_three_class_accuracy(df_eval["agent_pred_baseline"],   df_eval["human_ground_truth"])
        memory_acc_3class   = compute_three_class_accuracy(df_eval["agent_pred_with_memory"], df_eval["human_ground_truth"])

        baseline_acc_binary = compute_binary_accuracy(df_eval["agent_pred_baseline"],   df_eval["human_ground_truth"])
        memory_acc_binary   = compute_binary_accuracy(df_eval["agent_pred_with_memory"], df_eval["human_ground_truth"])

        delta_summary = pd.Series({
            "Baseline agent (no memory) — 3-class":             f"{baseline_acc_3class:.1%}",
            "With-memory agent — 3-class":                      f"{memory_acc_3class:.1%}",
            "Delta (with_memory - baseline) — 3-class":         f"{(memory_acc_3class - baseline_acc_3class) * 100:+.2f} pp",
            "Baseline agent — binary (toxic vs normal)":        f"{baseline_acc_binary:.1%}",
            "With-memory agent — binary":                       f"{memory_acc_binary:.1%}",
            "Delta (with_memory - baseline) — binary":          f"{(memory_acc_binary - baseline_acc_binary) * 100:+.2f} pp",
        })
        print(delta_summary.to_string())
    else:
        print("Skipped — see §4.1.")
""")

md("### 4.3 Per-domain delta — where did memory help most?")

code("""
    if has_memory_verdicts:
        df_eval["main_domain"] = df_eval["env_domain"].apply(main_domain)

        def _row(g):
            baseline = compute_three_class_accuracy(g["agent_pred_baseline"],    g["human_ground_truth"])
            with_mem = compute_three_class_accuracy(g["agent_pred_with_memory"], g["human_ground_truth"])
            return pd.Series({
                "n":                   len(g),
                "baseline acc":        baseline,
                "with-memory acc":     with_mem,
                "Delta (pp)":          (with_mem - baseline) * 100,
            })

        per_domain_eval = (
            df_eval.groupby("main_domain")
            .apply(_row)
            .sort_values("Delta (pp)", ascending=False)
        )
        per_domain_eval
    else:
        print("Skipped — see §4.1.")
""")

md("### 4.4 McNemar's test — is the delta statistically significant?")
md(
    "Paired binary outcomes (correct vs wrong against human ground truth).\n"
    "- `memory_hurt`   = baseline was right but with-memory got it wrong.\n"
    "- `memory_helped` = baseline was wrong but with-memory got it right.\n\n"
    "Under the null hypothesis (memory has no effect), the two counts should "
    "be roughly equal in expectation. A small McNemar p-value means the "
    "observed imbalance is unlikely to be chance."
)

code("""
    if has_memory_verdicts:
        baseline_correct = df_eval["agent_pred_baseline"]    == df_eval["human_ground_truth"]
        memory_correct   = df_eval["agent_pred_with_memory"] == df_eval["human_ground_truth"]

        memory_hurt   = int((baseline_correct & ~memory_correct).sum())
        memory_helped = int((~baseline_correct & memory_correct).sum())

        print(f"memory_hurt:   {memory_hurt}")
        print(f"memory_helped: {memory_helped}")

        if memory_hurt + memory_helped == 0:
            print("No discordant pairs — verdicts identical. p-value undefined.")
        else:
            try:
                from scipy.stats import chi2
                chi2_stat = (abs(memory_helped - memory_hurt) - 1) ** 2 / (memory_helped + memory_hurt)
                p_value = float(chi2.sf(chi2_stat, df=1))
                print(f"\\nMcNemar chi^2 = {chi2_stat:.3f}, df=1, p = {p_value:.4f}")
                if p_value < 0.05:
                    print("=> statistically significant at alpha=0.05.")
                else:
                    print("=> NOT statistically significant at alpha=0.05.")
            except ImportError:
                print("scipy not available — install it (`pip install scipy`) for an exact p-value.")
    else:
        print("Skipped — see §4.1.")
""")

md("### 4.5 Memory usage distribution")
md("How much context did the judge actually have to work with?")

code("""
    if has_memory_verdicts and "agent_memory_user_msgs" in df_eval.columns:
        usage = pd.DataFrame({
            "User-history msgs":   df_eval["agent_memory_user_msgs"].astype(float).describe(),
            "Thread-context msgs": df_eval["agent_memory_thread_msgs"].astype(float).describe(),
        })
        usage
    else:
        print("Skipped — memory usage columns not in CSV.")
""")

md("### 4.6 Register the with-memory variant in the cross-pipeline table")

code("""
    if has_memory_verdicts:
        # Latency ≈ baseline hybrid latency + small ES memory-query overhead.
        t1_eval = df_eval["processing_time_ms"].dropna().mean()
        t2_eval = (df_eval["agent_latency_seconds"].dropna() * 1000).mean()

        RESULTS_REGISTRY["Tier-1 + Tier-2 with memory"] = {
            "accuracy_3class":  memory_acc_3class,
            "accuracy_binary":  memory_acc_binary,
            "mean_latency_ms":  t1_eval + t2_eval,
            "n_records":        len(df_eval),
            "notes":            "Memory-augmented judge prompt (user history + thread context + fingerprint)",
        }
        pd.DataFrame(RESULTS_REGISTRY).T
    else:
        print("Skipped — see §4.1.")
""")

# ============================================================================
md("## 5. RAG (Tier-2 with semantic retrieval) — leave-one-out on the internship CSV")
md(
    "This section evaluates RAG-augmented Tier-2 judging: the prompt is "
    "enriched with k semantically similar past cases (retrieved from Qdrant), "
    "but NO user history or thread context — that isolates the RAG "
    "contribution from the Stage-2 temporal-memory contribution.\n\n"
    "Unlike §4 (temporal memory) this evaluation requires **no new manual "
    "labelling**. The benchmark CSV itself is used as both the corpus and "
    "the test set, via leave-one-out cross-validation: when judging each "
    "row, Qdrant returns the top-k most similar OTHER rows as precedents.\n\n"
    "**Prerequisite — populate the `agent_final_decision_with_rag` column.** "
    "Run:\n"
    "```bash\n"
    "docker-compose up -d qdrant\n"
    "python scripts/seed_rag_from_csv.py thesis_final_benchmark.csv --apply\n"
    "python scripts/replay_with_rag.py --csv thesis_final_benchmark.csv --apply\n"
    "```\n"
    "Until that runs the cells below print a friendly skip message — §1-§4 "
    "stay valid regardless."
)

md("### 5.1 Re-load benchmark and check for RAG verdicts")

code("""
    df_rag = load_benchmark()
    has_rag_verdicts = (
        "agent_final_decision_with_rag" in df_rag.columns
        and df_rag["agent_final_decision_with_rag"].astype(str).str.strip().ne("").any()
    )

    if not has_rag_verdicts:
        print("RAG verdicts NOT FOUND in the benchmark CSV.")
        print("Run the three commands in the §5 prerequisite, then re-run this cell.")
    else:
        df_rag["agent_final_decision_with_rag"] = (
            df_rag["agent_final_decision_with_rag"].astype(str).str.strip().str.lower()
        )
        df_rag["agent_pred_baseline"] = df_rag.apply(
            lambda r: agent_effective_label(r["model_label"], r["agent_final_decision"]),
            axis=1,
        )
        df_rag["agent_pred_with_rag"] = df_rag.apply(
            lambda r: agent_effective_label(r["model_label"], r["agent_final_decision_with_rag"]),
            axis=1,
        )
        print(f"RAG verdicts present on {len(df_rag)} records. Comparison ready.")
""")

md("### 5.2 Accuracy delta — baseline vs with-RAG vs Human")

code("""
    if has_rag_verdicts:
        baseline_acc_3class = compute_three_class_accuracy(df_rag["agent_pred_baseline"], df_rag["human_ground_truth"])
        rag_acc_3class      = compute_three_class_accuracy(df_rag["agent_pred_with_rag"], df_rag["human_ground_truth"])

        baseline_acc_binary = compute_binary_accuracy(df_rag["agent_pred_baseline"], df_rag["human_ground_truth"])
        rag_acc_binary      = compute_binary_accuracy(df_rag["agent_pred_with_rag"], df_rag["human_ground_truth"])

        delta_summary = pd.Series({
            "Baseline agent (no RAG) — 3-class":           f"{baseline_acc_3class:.1%}",
            "With-RAG agent — 3-class":                    f"{rag_acc_3class:.1%}",
            "Delta (with_rag - baseline) — 3-class":       f"{(rag_acc_3class - baseline_acc_3class) * 100:+.2f} pp",
            "Baseline agent — binary (toxic vs normal)":   f"{baseline_acc_binary:.1%}",
            "With-RAG agent — binary":                     f"{rag_acc_binary:.1%}",
            "Delta (with_rag - baseline) — binary":        f"{(rag_acc_binary - baseline_acc_binary) * 100:+.2f} pp",
        })
        print(delta_summary.to_string())
    else:
        print("Skipped — see §5.1.")
""")

md("### 5.3 Per-domain delta — where did RAG help most?")

code("""
    if has_rag_verdicts:
        df_rag["main_domain"] = df_rag["env_domain"].apply(main_domain)

        def _row(g):
            baseline = compute_three_class_accuracy(g["agent_pred_baseline"], g["human_ground_truth"])
            with_rag = compute_three_class_accuracy(g["agent_pred_with_rag"], g["human_ground_truth"])
            return pd.Series({
                "n":           len(g),
                "baseline acc": baseline,
                "with-RAG acc": with_rag,
                "Delta (pp)":  (with_rag - baseline) * 100,
            })

        per_domain_rag = (
            df_rag.groupby("main_domain")
            .apply(_row)
            .sort_values("Delta (pp)", ascending=False)
        )
        per_domain_rag
    else:
        print("Skipped — see §5.1.")
""")

md("### 5.4 McNemar's test — is the RAG delta significant?")

code("""
    if has_rag_verdicts:
        baseline_correct = df_rag["agent_pred_baseline"] == df_rag["human_ground_truth"]
        rag_correct      = df_rag["agent_pred_with_rag"] == df_rag["human_ground_truth"]

        rag_hurt   = int((baseline_correct & ~rag_correct).sum())
        rag_helped = int((~baseline_correct & rag_correct).sum())

        print(f"rag_hurt:   {rag_hurt}")
        print(f"rag_helped: {rag_helped}")

        if rag_hurt + rag_helped == 0:
            print("No discordant pairs — verdicts identical. p-value undefined.")
        else:
            try:
                from scipy.stats import chi2
                chi2_stat = (abs(rag_helped - rag_hurt) - 1) ** 2 / (rag_helped + rag_hurt)
                p_value = float(chi2.sf(chi2_stat, df=1))
                print(f"\\nMcNemar chi^2 = {chi2_stat:.3f}, df=1, p = {p_value:.4f}")
                if p_value < 0.05:
                    print("=> statistically significant at alpha=0.05.")
                else:
                    print("=> NOT statistically significant at alpha=0.05.")
            except ImportError:
                print("scipy not available — install it (`pip install scipy`) for an exact p-value.")
    else:
        print("Skipped — see §5.1.")
""")

md("### 5.5 Precedent-retrieval distribution — how many cases did Qdrant return?")

code("""
    if has_rag_verdicts and "agent_retrieval_count" in df_rag.columns:
        usage = df_rag["agent_retrieval_count"].astype(float).describe()
        print("Precedents returned per query:")
        print(usage.to_string())
    else:
        print("Skipped — agent_retrieval_count not in CSV.")
""")

md("### 5.6 Register the with-RAG variant in the cross-pipeline table")

code("""
    if has_rag_verdicts:
        t1_rag = df_rag["processing_time_ms"].dropna().mean()
        t2_rag = (df_rag["agent_latency_seconds"].dropna() * 1000).mean()

        RESULTS_REGISTRY["Tier-1 + Tier-2 with RAG (no memory)"] = {
            "accuracy_3class":  rag_acc_3class,
            "accuracy_binary":  rag_acc_binary,
            "mean_latency_ms":  t1_rag + t2_rag,
            "n_records":        len(df_rag),
            "notes":            "RAG-only prompt; semantic precedents from Qdrant, no temporal memory",
        }
        pd.DataFrame(RESULTS_REGISTRY).T
    else:
        print("Skipped — see §5.1.")
""")

# ============================================================================
md("## 5b. Template — adding a future pipeline variant")
md(
    "Copy the cell below into a new section when a new pipeline variant lands "
    "(e.g. Retrieval-Augmented Moderation, Multi-Agent, Edge-quantised, ...). "
    "The comments mark exactly what each new section needs to change."
)

code("""
    # ----------------------------------------------------------------------
    # TEMPLATE — duplicate this cell into its own section for each
    # new pipeline variant you want to evaluate.
    # ----------------------------------------------------------------------
    #
    # # <Variant name> — e.g. "Retrieval-Augmented Moderation"
    #
    # # 1. Load the variant's benchmark CSV.
    # #    - If the variant only modifies the agent verdict (prompt / model
    # #      / context change), re-run the live pipeline (or its replay
    # #      script) against the SAME texts as the baseline and export with:
    # #          python src/export_subset.py <variant_benchmark>.csv
    # #    - If the variant adds new data, export a fresh CSV with a
    # #      descriptive suffix.
    # #
    # # [LIVE INFRA] needed only when generating the new CSV; not when reading it.
    # df_variant = load_benchmark("<variant_benchmark>.csv")
    #
    # # 2. Compute the agent's effective prediction.
    # df_variant["agent_pred"] = df_variant.apply(
    #     lambda r: agent_effective_label(r["model_label"], r["agent_final_decision"]),
    #     axis=1,
    # )
    #
    # # 3. Compute metrics.
    # acc_3 = compute_three_class_accuracy(df_variant["agent_pred"], df_variant["human_ground_truth"])
    # acc_b = compute_binary_accuracy(df_variant["agent_pred"],     df_variant["human_ground_truth"])
    # t1    = df_variant["processing_time_ms"].dropna().mean()
    # t2    = (df_variant["agent_latency_seconds"].dropna() * 1000).mean()
    #
    # # 4. Register.
    # RESULTS_REGISTRY["<Variant name>"] = {
    #     "accuracy_3class":  acc_3,
    #     "accuracy_binary":  acc_b,
    #     "mean_latency_ms":  t1 + t2,
    #     "n_records":        len(df_variant),
    #     "notes":            "<what changed since the previous variant>",
    # }
    #
    # pd.DataFrame(RESULTS_REGISTRY).T
""")

# ============================================================================
md("## 7. Cross-pipeline comparison")
md(
    "Final readout. Re-render after any section appends to `RESULTS_REGISTRY`. "
    "When a variant's row appears here, the thesis can cite the delta from "
    "the previous row as that variant's contribution."
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
