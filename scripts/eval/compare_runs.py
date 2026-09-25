"""
Collect every scaling run into one table  —  READ-ONLY.

Walks reports/scaling/*/ and merges what each run recorded:
    manifest_producer.json    topic, partitions, messages, mode, rate, host
    manifest_processors.json  device, model, processors, threads   (runs from G1 on)
    metrics.json              throughput, latency, balance, checks

and writes two files next to them:
    reports/scaling/comparison.csv   one row per run, for a spreadsheet
    reports/scaling/comparison.md    the same, plus a median-per-configuration
                                     table ready to paste into the thesis

Nothing is typed by hand, so the thesis numbers cannot drift from the runs that
produced them. Runs from other machines merge in as soon as their folders are
copied into reports/scaling/.

Examples:
    python scripts/eval/compare_runs.py
    python scripts/eval/compare_runs.py --min-n 5000      # ignore smoke tests
    python scripts/eval/compare_runs.py --only-valid      # drop runs that lost messages
"""
import argparse
import csv
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports" / "scaling"

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass


def load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def collect(min_n, only_valid):
    rows = []
    for folder in sorted(REPORTS.iterdir() if REPORTS.is_dir() else []):
        if not folder.is_dir():
            continue
        # A run is kept on disk but excluded from the tables if it carries an
        # INVALID file (its first line says why).
        if (folder / "INVALID").exists() or (folder / "INVALID.txt").exists():
            continue
        met = load(folder / "metrics.json")
        if not met:
            continue  # run never analysed (crashed or still going)
        prod = load(folder / "manifest_producer.json")
        proc = load(folder / "manifest_processors.json")
        n = met.get("sent") or prod.get("n") or 0
        if n < min_n:
            continue
        lost, dup = met.get("missing", 0), met.get("duplicates", 0)
        if only_valid and (lost or dup):
            continue
        thr = met.get("throughput") or {}
        lat = met.get("latency_ms") or {}
        e2e, wait = lat.get("end_to_end") or {}, lat.get("kafka_wait") or {}
        inf, es = lat.get("inference") or {}, lat.get("elasticsearch") or {}
        procs = len(met.get("balance", {}).get("per_processor", {})) or proc.get("processors")
        rows.append({
            "run": folder.name,
            "device": proc.get("device", "cpu"),
            "model": proc.get("model_dir", "models/bert_final (default)"),
            "processors": procs,
            "partitions": met.get("partitions") or prod.get("partitions"),
            "threads": proc.get("threads_per_process"),
            "messages": n,
            "mode": met.get("mode") or prod.get("mode"),
            "rate": prod.get("rate"),
            "hosts": "+".join(sorted(met.get("balance", {}).get("per_node", {}))) or prod.get("host"),
            "msgs_per_sec": thr.get("msgs_per_sec"),
            "e2e_p50_ms": e2e.get("p50"), "e2e_p95_ms": e2e.get("p95"),
            "kafka_wait_p50_ms": wait.get("p50"),
            "inference_p50_ms": inf.get("p50"), "inference_p95_ms": inf.get("p95"),
            "elasticsearch_p50_ms": es.get("p50"),
            "lost": lost, "duplicates": dup,
            "balance_ratio": met.get("balance", {}).get("processor_max_min_ratio"),
        })
    return rows


def medians(rows):
    """Median throughput per (device, processors, mode, rate), the thesis view."""
    groups = {}
    for r in rows:
        key = (r["device"], r["processors"], r["mode"], r["rate"])
        groups.setdefault(key, []).append(r)
    out = []
    for (device, procs, mode, rate), rs in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][2], kv[0][1] or 0)):
        thr = [r["msgs_per_sec"] for r in rs if r["msgs_per_sec"]]
        e2e = [r["e2e_p50_ms"] for r in rs if r["e2e_p50_ms"] is not None]
        inf = [r["inference_p50_ms"] for r in rs if r["inference_p50_ms"] is not None]
        es = [r["elasticsearch_p50_ms"] for r in rs if r["elasticsearch_p50_ms"] is not None]
        out.append({
            "device": device, "processors": procs, "mode": mode, "rate": rate, "runs": len(rs),
            "throughput_median": round(statistics.median(thr), 2) if thr else None,
            "throughput_min": round(min(thr), 2) if thr else None,
            "throughput_max": round(max(thr), 2) if thr else None,
            "inference_p50_median": round(statistics.median(inf), 1) if inf else None,
            "elasticsearch_p50_median": round(statistics.median(es), 1) if es else None,
            "e2e_p50_median": round(statistics.median(e2e), 1) if e2e else None,
            "lost_total": sum(r["lost"] for r in rs), "duplicates_total": sum(r["duplicates"] for r in rs),
        })
    # speed-up against the 1-processor run of the same device and mode
    for row in out:
        base = next((o["throughput_median"] for o in out
                     if o["device"] == row["device"] and o["mode"] == row["mode"]
                     and o["rate"] == row["rate"] and o["processors"] == 1), None)
        if base and row["throughput_median"]:
            row["speedup"] = round(row["throughput_median"] / base, 2)
            row["efficiency"] = round(row["speedup"] / row["processors"], 2) if row["processors"] else None
        else:
            row["speedup"] = row["efficiency"] = None
    return out


def md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for r in rows:
        out.append("| " + " | ".join("" if r.get(h) is None else str(r.get(h)) for h in headers) + " |")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="Merge all scaling runs into one table (read-only).")
    ap.add_argument("--min-n", type=int, default=1000, help="ignore runs smaller than this (default 1000)")
    ap.add_argument("--only-valid", action="store_true", help="drop runs with lost or duplicated messages")
    a = ap.parse_args()

    rows = collect(a.min_n, a.only_valid)
    if not rows:
        sys.exit(f"No analysed runs found in {REPORTS}")
    med = medians(rows)

    csv_path, md_path = REPORTS / "comparison.csv", REPORTS / "comparison.md"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    per_cfg = ["device", "processors", "mode", "rate", "runs", "throughput_median",
               "throughput_min", "throughput_max", "speedup", "efficiency",
               "inference_p50_median", "elasticsearch_p50_median", "e2e_p50_median",
               "lost_total", "duplicates_total"]
    per_run = ["run", "device", "processors", "partitions", "messages", "mode", "rate",
               "hosts", "msgs_per_sec", "inference_p50_ms", "elasticsearch_p50_ms",
               "e2e_p50_ms", "lost", "duplicates", "balance_ratio"]

    text = ("# Scaling runs\n\n## Median per configuration\n\n" + md_table(per_cfg, med)
            + "\n\n## Every run\n\n" + md_table(per_run, rows)
            + f"\n\n_{len(rows)} runs, generated by scripts/eval/compare_runs.py_\n")
    md_path.write_text(text, encoding="utf-8")

    print(md_table(per_cfg, med))
    print(f"\n{len(rows)} runs -> {csv_path}\n{' ' * len(str(len(rows)))}    -> {md_path}")
    bad = [r["run"] for r in rows if r["lost"] or r["duplicates"]]
    if bad:
        print(f"\nRuns with lost or duplicated messages: {bad}")


if __name__ == "__main__":
    main()
