"""
export_report.py — Export evaluation results to reports/ folder in CSV/JSON/Markdown.

Usage:
    python scripts/export_report.py --stage 3 --csv thesis_benchmark_eval.csv
    python scripts/export_report.py --stage 4 --csv thesis_benchmark_eval.csv

Each run:
1. Reads the benchmark CSV with all verdicts (baseline, memory, RAG, multi-agent)
2. Computes RESULTS_REGISTRY (same as notebook §3)
3. Exports to reports/stage<N>/latest/ in CSV, JSON, Markdown
4. Archives previous run to reports/stage<N>/archive/<timestamp>/
"""

import argparse
import datetime
import json
import os
import shutil
import sys
from collections import OrderedDict
from pathlib import Path

import pandas as pd

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))


def load_benchmark(csv_path):
    """Load + normalise the benchmark CSV."""
    df = pd.read_csv(csv_path)
    df["human_ground_truth"] = (
        df["human_ground_truth"].fillna("NORMAL").astype(str).str.strip().str.upper()
    )
    df["model_label"] = df["model_label"].astype(str).str.strip().str.upper()
    df["agent_final_decision"] = (
        df["agent_final_decision"].astype(str).str.strip().str.lower()
    )
    return df


def agent_effective_label(model_label, agent_decision):
    """Map (Tier-1, Tier-2 verdict) -> effective prediction."""
    if agent_decision == "correct":
        return model_label
    if agent_decision == "false positive":
        return "NORMAL"
    if agent_decision == "false negative":
        return "OFFENSIVE"
    return model_label


def compute_accuracy(predictions, ground_truth):
    return float((predictions == ground_truth).sum()) / len(ground_truth)


def build_results_registry(df):
    """Build the RESULTS_REGISTRY dict from the benchmark CSV."""
    registry = OrderedDict()

    # Baseline: Tier-1 only
    df["model_pred"] = df["model_label"]
    t1_acc = compute_accuracy(df["model_pred"], df["human_ground_truth"])
    t1_latency = df["processing_time_ms"].dropna().mean() if "processing_time_ms" in df.columns else 0
    
    registry["Tier-1 baseline (DistilBERT only)"] = {
        "accuracy_3class": f"{t1_acc:.1%}",
        "n_records": len(df),
        "latency_ms": f"{t1_latency:.1f}",
        "notes": "Static classifier, no Tier-2 overlay",
    }

    # Baseline: Tier-1 + Tier-2 (no memory, no RAG)
    df["agent_pred_baseline"] = df.apply(
        lambda r: agent_effective_label(r["model_label"], r["agent_final_decision"]),
        axis=1,
    )
    t2_acc = compute_accuracy(df["agent_pred_baseline"], df["human_ground_truth"])
    t2_latency = (
        (df["agent_latency_seconds"].dropna() * 1000).mean()
        if "agent_latency_seconds" in df.columns
        else 0
    )
    
    registry["Tier-1 + Tier-2 baseline (no memory, no RAG)"] = {
        "accuracy_3class": f"{t2_acc:.1%}",
        "n_records": len(df),
        "latency_ms": f"{t1_latency + t2_latency:.1f}",
        "notes": "Hybrid pipeline, frozen internship verdicts",
    }

    # Memory variant
    if "agent_final_decision_with_memory" in df.columns:
        has_memory = df["agent_final_decision_with_memory"].astype(str).str.strip().ne("").any()
        if has_memory:
            df["agent_final_decision_with_memory"] = (
                df["agent_final_decision_with_memory"].astype(str).str.strip().str.lower()
            )
            df["agent_pred_memory"] = df.apply(
                lambda r: agent_effective_label(r["model_label"], r["agent_final_decision_with_memory"]),
                axis=1,
            )
            memory_acc = compute_accuracy(df["agent_pred_memory"], df["human_ground_truth"])
            registry["Tier-1 + Tier-2 with memory"] = {
                "accuracy_3class": f"{memory_acc:.1%}",
                "delta_vs_baseline": f"{(memory_acc - t2_acc) * 100:+.2f} pp",
                "n_records": len(df),
                "latency_ms": f"{t1_latency + t2_latency:.1f}",
                "notes": "Memory-augmented prompt (user history + thread context)",
            }

    # RAG variant
    if "agent_final_decision_with_rag" in df.columns:
        has_rag = df["agent_final_decision_with_rag"].astype(str).str.strip().ne("").any()
        if has_rag:
            df["agent_final_decision_with_rag"] = (
                df["agent_final_decision_with_rag"].astype(str).str.strip().str.lower()
            )
            df["agent_pred_rag"] = df.apply(
                lambda r: agent_effective_label(r["model_label"], r["agent_final_decision_with_rag"]),
                axis=1,
            )
            rag_acc = compute_accuracy(df["agent_pred_rag"], df["human_ground_truth"])
            registry["Tier-1 + Tier-2 with RAG (no memory)"] = {
                "accuracy_3class": f"{rag_acc:.1%}",
                "delta_vs_baseline": f"{(rag_acc - t2_acc) * 100:+.2f} pp",
                "n_records": len(df),
                "latency_ms": f"{t1_latency + t2_latency:.1f}",
                "notes": "RAG-only prompt; semantic precedents from Qdrant",
            }

    # Multi-agent variant (if present)
    if "multi_agent_verdict" in df.columns:
        has_multi = df["multi_agent_verdict"].astype(str).str.strip().ne("").any()
        if has_multi:
            df["multi_agent_verdict"] = (
                df["multi_agent_verdict"].astype(str).str.strip().str.lower()
            )
            df["agent_pred_multi"] = df.apply(
                lambda r: agent_effective_label(r["model_label"], r["multi_agent_verdict"]),
                axis=1,
            )
            multi_acc = compute_accuracy(df["agent_pred_multi"], df["human_ground_truth"])
            registry["Tier-1 + Tier-2 multi-agent"] = {
                "accuracy_3class": f"{multi_acc:.1%}",
                "delta_vs_baseline": f"{(multi_acc - t2_acc) * 100:+.2f} pp",
                "n_records": len(df),
                "latency_ms": f"{t1_latency + t2_latency:.1f}",
                "notes": "Multi-agent ensemble (Risk Scorer, Profiler, Escalator, Supervisor)",
            }

    return registry


def export_formats(registry, stage, output_dir):
    """Export registry to CSV, JSON, Markdown."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # CSV
    df = pd.DataFrame(registry).T
    csv_path = output_dir / "results.csv"
    df.to_csv(csv_path)
    print(f"✓ Exported {csv_path}")

    # JSON
    json_path = output_dir / "results.json"
    with open(json_path, "w") as f:
        json.dump(registry, f, indent=2)
    print(f"✓ Exported {json_path}")

    # Markdown
    md_path = output_dir / "results.md"
    with open(md_path, "w") as f:
        f.write(f"# Stage {stage} Evaluation Results\n\n")
        f.write(f"**Generated:** {datetime.datetime.now().isoformat()}\n\n")
        f.write("## Cross-Pipeline Comparison\n\n")
        f.write(df.to_markdown())
        f.write("\n\n## Row Details\n\n")
        for variant, metrics in registry.items():
            f.write(f"### {variant}\n\n")
            for key, val in metrics.items():
                f.write(f"- **{key}:** {val}\n")
            f.write("\n")
    print(f"✓ Exported {md_path}")

    return csv_path, json_path, md_path


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--stage", type=int, required=True, help="Stage number (3 or 4).")
    parser.add_argument(
        "--csv",
        required=True,
        help="Path to benchmark CSV (e.g., thesis_benchmark_eval.csv).",
    )
    args = parser.parse_args()

    if not os.path.exists(args.csv):
        print(f"[ERROR] CSV not found: {args.csv}")
        sys.exit(1)

    # Load benchmark
    print(f"Loading {args.csv}...")
    df = load_benchmark(args.csv)
    print(f"  → {len(df)} records")

    # Build registry
    print("\nBuilding results registry...")
    registry = build_results_registry(df)

    # Export to latest/
    latest_dir = Path(f"reports/stage{args.stage}/latest")
    print(f"\nExporting to {latest_dir}...")
    export_formats(registry, args.stage, latest_dir)

    # Archive previous run (if latest/ exists with results)
    archive_dir = Path(f"reports/stage{args.stage}/archive")
    if (latest_dir / "results.csv").exists():
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        archive_ts_dir = archive_dir / timestamp
        print(f"\nArchiving previous run to {archive_ts_dir}...")
        shutil.copytree(latest_dir, archive_ts_dir, dirs_exist_ok=True)
        print(f"✓ Archived")

    print(f"\n[OK] Stage {args.stage} results exported to {latest_dir}")
    print(f"\nShare with supervisor:")
    print(f"  - CSV for Excel: {latest_dir / 'results.csv'}")
    print(f"  - JSON for code: {latest_dir / 'results.json'}")
    print(f"  - Markdown for pasting: {latest_dir / 'results.md'}")


if __name__ == "__main__":
    main()
