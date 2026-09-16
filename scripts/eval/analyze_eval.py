"""
Read-only analysis of the final evaluation set (thesis_benchmark_eval.csv):

  1. Toxic-class precision/recall/F1 for every variant  (verifies Table 5.1).
  2. Tier-1 and Tier-2 latency percentiles + escalation rate.
  3. Toxic-class-size scaling: metrics on the first-stage subset (up to the
     44th toxic message, ~the initial dataset) vs the full 80-toxic benchmark.

Touches nothing. Just prints numbers.  python scripts/eval/analyze_eval.py
"""
import statistics
import sys
from pathlib import Path
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CSV = Path(__file__).resolve().parents[2] / "thesis_benchmark_eval.csv"
TOXIC = {"OFFENSIVE", "HATE"}

VARIANTS = {
    "Tier-1 (static)":     None,                                  # use model_label directly
    "Tier-2 baseline":     "agent_final_decision",
    "+ memory":            "agent_final_decision_with_memory",
    "+ RAG":               "agent_final_decision_with_rag",
    "+ LLM-Wiki":          "agent_final_decision_with_wiki",
    "multi-agent":         "agent_final_decision_with_multi_agent",
}


def pred_toxic(row, col):
    ml = str(row["model_label"]).strip().upper()
    t1 = ml in TOXIC
    if col is None:
        return t1
    d = str(row[col]).strip().lower()
    if d == "false positive":
        return False          # Tier-2 corrects a wrong flag to normal
    if d == "false negative":
        return True           # Tier-2 corrects a miss to toxic
    return t1                 # "correct" (or parse error) keeps Tier-1's call


def prf(df, col):
    tp = fp = fn = 0
    for _, r in df.iterrows():
        p = pred_toxic(r, col)
        a = str(r["human_ground_truth"]).strip().upper() in TOXIC
        if p and a: tp += 1
        elif p and not a: fp += 1
        elif (not p) and a: fn += 1
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return prec, rec, f1


def pct(xs, p):
    xs = sorted(xs); k = (len(xs) - 1) * p / 100
    lo = int(k); hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def table(df, title):
    print(f"\n{title}  (n={len(df)}, toxic={sum(df['human_ground_truth'].str.upper().isin(TOXIC))})")
    print(f"  {'variant':<18} {'P':>6} {'R':>6} {'F1':>6}")
    out = {}
    for name, col in VARIANTS.items():
        prec, rec, f1 = prf(df, col)
        out[name] = f1
        print(f"  {name:<18} {prec:6.2f} {rec:6.2f} {f1:6.2f}")
    return out


def main():
    df = pd.read_csv(CSV)
    df["human_ground_truth"] = df["human_ground_truth"].fillna("Normal").astype(str)

    # --- 1. full-set metrics (verify Table 5.1) ---
    full = table(df, "FULL BENCHMARK")

    # --- 2. latency + escalation ---
    print("\nLATENCY & COST")
    t1 = pd.to_numeric(df["processing_time_ms"], errors="coerce").dropna().tolist()
    print(f"  Tier-1 ms : mean {statistics.mean(t1):.1f} | p50 {pct(t1,50):.1f} | "
          f"p95 {pct(t1,95):.1f} | p99 {pct(t1,99):.1f}")
    if "agent_latency_seconds" in df:
        t2 = pd.to_numeric(df["agent_latency_seconds"], errors="coerce").dropna()
        t2 = [x for x in t2 if x > 0]
        if t2:
            print(f"  Tier-2 s  : mean {statistics.mean(t2):.2f} | p50 {pct(t2,50):.2f} | "
                  f"p95 {pct(t2,95):.2f} | p99 {pct(t2,99):.2f}")
    conf = pd.to_numeric(df["model_confidence"], errors="coerce").dropna()
    esc = (conf < 0.80).sum()
    print(f"  Escalated to Tier-2 (<0.80): {esc}/{len(conf)} = {100*esc/len(conf):.1f}%")

    # --- 3. toxic-class-size scaling: first-stage (44 toxic) vs full (80) ---
    d = df.sort_values("timestamp").reset_index(drop=True)
    d["is_tox"] = d["human_ground_truth"].str.upper().isin(TOXIC)
    d["cum_tox"] = d["is_tox"].cumsum()
    cut = d[d["cum_tox"] == 44].index
    if len(cut):
        sub = d.iloc[: cut.max() + 1]
        stage = table(sub, "FIRST-STAGE SUBSET (up to 44th toxic)")
        print(f"\nSCALING 44-toxic -> 80-toxic (F1 delta):")
        for name in VARIANTS:
            print(f"  {name:<18} {stage[name]:.2f} -> {full[name]:.2f}   "
                  f"(Δ {full[name]-stage[name]:+.2f})")
    else:
        print("\n[!] Could not locate the 44th toxic by timestamp order.")


if __name__ == "__main__":
    main()
