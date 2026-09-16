"""
check_results.py — quick results table for a benchmark CSV (read-only).

Prints, for every pipeline variant present in the CSV, the metrics that
matter — including toxic-class precision/recall/F1, which is the honest
metric to lead with given the heavy NORMAL-class imbalance.

Usage:
    python scripts/eval/check_results.py                          # default CSV
    python scripts/eval/check_results.py thesis_benchmark_eval.csv
"""

import sys

import pandas as pd

TOXIC = {"HATE", "OFFENSIVE"}

VARIANTS = [
    ("Tier-2 baseline", "agent_final_decision"),
    ("Tier-2 + memory", "agent_final_decision_with_memory"),
    ("Tier-2 + RAG", "agent_final_decision_with_rag"),
    ("Tier-2 + LLM-Wiki", "agent_final_decision_with_wiki"),
    ("Tier-2 multi-agent (Stage 4)", "agent_final_decision_with_multi_agent"),
]


def effective_label(model_label, decision):
    d = str(decision).strip().lower()
    if d == "correct":
        return model_label
    if d == "false positive":
        return "NORMAL"
    if d == "false negative":
        return "OFFENSIVE"
    return model_label


def metrics(pred, gt):
    acc = (pred == gt).mean()
    pb, gb = pred.isin(TOXIC), gt.isin(TOXIC)
    bacc = (pb == gb).mean()
    tp = (pb & gb).sum()
    fp = (pb & ~gb).sum()
    fn = (~pb & gb).sum()
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return acc, bacc, prec, rec, f1


def main():
    csv = sys.argv[1] if len(sys.argv) > 1 else "thesis_benchmark_eval.csv"
    df = pd.read_csv(csv)
    df["human_ground_truth"] = df["human_ground_truth"].fillna("").astype(str).str.strip().str.upper()
    df["model_label"] = df["model_label"].astype(str).str.strip().str.upper()
    df = df[df["human_ground_truth"].isin(["NORMAL", "OFFENSIVE", "HATE"])]

    n_toxic = df["human_ground_truth"].isin(TOXIC).sum()
    print(f"CSV: {csv}")
    print(f"Labelled rows: {len(df)}  |  toxic (HATE+OFFENSIVE): {n_toxic}  |  normal: {len(df) - n_toxic}")
    print()
    print(f"{'Variant':<32s} {'n':>4s} {'3cls':>6s} {'bin':>6s} {'ToxP':>6s} {'ToxR':>6s} {'ToxF1':>6s}")
    print("-" * 72)

    a, b, p, r, f = metrics(df["model_label"], df["human_ground_truth"])
    print(f"{'Tier-1 DistilBERT':<32s} {len(df):>4d} {a:>6.1%} {b:>6.1%} {p:>6.2f} {r:>6.2f} {f:>6.2f}")

    for name, col in VARIANTS:
        if col not in df.columns:
            continue
        sub = df[df[col].astype(str).str.strip().replace("nan", "").str.len() > 0]
        if sub.empty:
            continue
        pred = sub.apply(lambda x: effective_label(x["model_label"], x[col]), axis=1)
        a, b, p, r, f = metrics(pred, sub["human_ground_truth"])
        print(f"{name:<32s} {len(sub):>4d} {a:>6.1%} {b:>6.1%} {p:>6.2f} {r:>6.2f} {f:>6.2f}")

    print()
    print("3cls = 3-class accuracy | bin = toxic-vs-normal accuracy")
    print("ToxP/ToxR/ToxF1 = precision / recall / F1 on the TOXIC class (lead with this)")


if __name__ == "__main__":
    main()
