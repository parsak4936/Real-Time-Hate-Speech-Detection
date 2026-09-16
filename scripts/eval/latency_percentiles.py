"""
Tier-1 latency percentiles + escalation rate  —  READ-ONLY.

Reads the existing audit log (data/stream_log.csv) that the processor already
writes, and reports latency p50/p90/p95/p99, an implied single-process
throughput, and the Tier-2 escalation rate (share below the 0.80 gate).

Touches NOTHING: no Kafka, no Elasticsearch, no writes except an optional PNG
histogram under reports/. Safe to run any time.

    python scripts/eval/latency_percentiles.py
"""
import csv
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CSV_LOG = ROOT / "data" / "stream_log.csv"
GATE = 0.80


def pct(xs, p):
    xs = sorted(xs)
    if not xs:
        return 0.0
    k = (len(xs) - 1) * p / 100.0
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def main():
    if not CSV_LOG.exists():
        print(f"[!] {CSV_LOG} not found — run the pipeline first so it logs some records.")
        return

    lat, conf = [], []
    with open(CSV_LOG, encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            try:
                lat.append(float(row["latency_ms"]))
                conf.append(float(row["model_confidence"]))
            except (KeyError, ValueError):
                continue

    n = len(lat)
    if n == 0:
        print("[!] No usable rows in the log yet.")
        return

    mean = statistics.mean(lat)
    print(f"Records analysed:            {n}")
    print(f"Tier-1 latency (ms):  mean {mean:6.1f} | p50 {pct(lat,50):6.1f} | "
          f"p90 {pct(lat,90):6.1f} | p95 {pct(lat,95):6.1f} | p99 {pct(lat,99):6.1f} | "
          f"max {max(lat):6.1f}")
    thr = 1000.0 / mean if mean else 0
    print(f"Implied single-process rate: {thr:5.1f} msg/s  (~{thr*60:,.0f} msg/min)")

    esc = sum(1 for c in conf if c < GATE)
    print(f"Escalation to Tier-2 (<{GATE}): {esc}/{n} = {100*esc/n:.1f}%")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        cap = pct(lat, 99) * 1.5
        plt.figure(figsize=(7, 4))
        plt.hist([x for x in lat if x <= cap], bins=40, color="#4C78A8")
        plt.axvline(mean, color="crimson", ls="--", label=f"mean {mean:.0f} ms")
        plt.xlabel("Tier-1 latency (ms)")
        plt.ylabel("messages")
        plt.legend()
        out = ROOT / "reports" / "tier1_latency_hist.png"
        out.parent.mkdir(exist_ok=True)
        plt.savefig(out, dpi=120, bbox_inches="tight")
        print(f"Saved histogram -> {out}")
    except Exception as e:
        print(f"(histogram skipped: {e})")


if __name__ == "__main__":
    main()
