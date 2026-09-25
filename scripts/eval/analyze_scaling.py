"""
Scaling-run analyser  —  READ-ONLY, joins what was sent with what was processed.

Reads one run folder produced by the scaling experiments and turns it into the
numbers the thesis reports, following the protocol in
thesis/THESIS_STATE.md section 12:

  reports/scaling/<run_id>/
      manifest_producer.json   written by scripts/eval/replay_producer.py
      sent.csv                 one row per message the producer got acknowledged
      bench_*.csv              one timing log per Tier-1 processor (E1 BENCH_LOG),
                               copied here from each machine

Metrics: throughput over the steady window (first 10% dropped), end-to-end
latency and its breakdown (Kafka wait / model / Elasticsearch), balance across
processors, machines and partitions, and optional speed-up against a baseline run.

Validity checks, printed as PASS / WARN / FAIL: lost messages, duplicates,
unknown extras, clock sanity across machines, and optional label agreement with
a reference run.

Touches nothing: no Kafka, no Elasticsearch, no pipeline files. It only writes
metrics.json and summary.txt inside the run folder.

Examples:
  python scripts/eval/analyze_scaling.py --run 20260923-111323_perf_smoke
  python scripts/eval/analyze_scaling.py --run <id> --baseline <1-processor id> --reference <id>
"""
import argparse
import collections
import csv
import glob
import json
import os
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports" / "scaling"
WARMUP = 0.10  # fraction of messages dropped before measuring throughput

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass


def run_dir(run):
    p = Path(run)
    if not p.is_dir():
        p = REPORTS / run
    if not p.is_dir():
        sys.exit(f"Run folder not found: {run}")
    return p


def pct(values, p):
    if not values:
        return None
    s = sorted(values)
    k = min(len(s) - 1, max(0, int(round((p / 100.0) * (len(s) - 1)))))
    return round(s[k], 1)


def stats_block(values):
    if not values:
        return None
    return {"n": len(values), "p50": pct(values, 50), "p95": pct(values, 95),
            "p99": pct(values, 99), "max": round(max(values), 1),
            "mean": round(statistics.fmean(values), 1)}


def load_sent(folder):
    f = folder / "sent.csv"
    if not f.exists():
        sys.exit(f"sent.csv missing in {folder}")
    out = {}
    with open(f, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out[int(r["seq"])] = {"partition": int(r["partition"]),
                                  "kafka_ts_ms": float(r["kafka_ts_ms"]),
                                  "t_call_ms": float(r["t_call_ms"])}
    return out


def load_bench(folder, run_id):
    """Processor timing rows for this run only (one log may span several runs)."""
    rows, files = [], sorted(glob.glob(str(folder / "bench*.csv")))
    for path in files:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for r in csv.DictReader(fh):
                if run_id and (r.get("run_id") or "") != run_id:
                    continue
                if not (r.get("seq") or "").strip():
                    continue
                try:
                    rows.append({
                        "node": r["node"], "pid": r["pid"], "seq": int(r["seq"]),
                        "partition": int(r["partition"]),
                        "kafka_ts_ms": float(r["kafka_ts_ms"]),
                        "t_recv_ms": float(r["t_recv_ms"]), "infer_ms": float(r["infer_ms"]),
                        "es_ms": float(r["es_ms"]), "t_done_ms": float(r["t_done_ms"]),
                        "label": r["label"], "source_file": os.path.basename(path),
                    })
                except (KeyError, ValueError):
                    continue
    return rows, [os.path.basename(p) for p in files]


def throughput(rows):
    """Messages per second over the steady window (first WARMUP fraction dropped)."""
    if len(rows) < 3:
        return None
    done = sorted(r["t_done_ms"] for r in rows)
    steady = done[int(len(done) * WARMUP):]
    span = (steady[-1] - steady[0]) / 1000.0
    if span <= 0:
        return None
    return {"messages_steady": len(steady), "window_seconds": round(span, 3),
            "msgs_per_sec": round((len(steady) - 1) / span, 2)}


def main():
    ap = argparse.ArgumentParser(description="Analyse one scaling run (read-only).")
    ap.add_argument("--run", required=True, help="run id or folder under reports/scaling/")
    ap.add_argument("--baseline", default="", help="run id of the 1-processor run, for speed-up")
    ap.add_argument("--reference", default="", help="run id whose labels are the reference")
    ap.add_argument("--run-id", default="", help="override the run id used to filter bench rows")
    ap.add_argument("--warmup-seconds", type=float, default=0.0,
                    help="also drop messages sent in the first N seconds (rate runs: the consumer "
                         "group needs a few seconds to be assigned its partitions)")
    a = ap.parse_args()

    folder = run_dir(a.run)
    manifest = {}
    mp = folder / "manifest_producer.json"
    if mp.exists():
        manifest = json.loads(mp.read_text(encoding="utf-8"))
    run_id = a.run_id or manifest.get("run_id") or folder.name
    mode = manifest.get("mode", "unknown")

    sent = load_sent(folder)
    rows, bench_files = load_bench(folder, run_id)

    lines = [f"Run {run_id}", f"  mode={mode}  partitions={manifest.get('partitions')}  "
             f"sent={len(sent)}  processed_rows={len(rows)}  bench files={bench_files or 'NONE'}"]

    if not rows:
        lines += ["", "No processor timing rows for this run.",
                  "  Copy each machine's BENCH_LOG file into this folder as bench_<node>.csv,",
                  f"  and check its run_id column equals {run_id!r}.",
                  f"FAIL delivery: 0 of {len(sent)} messages processed."]
        print("\n".join(lines))
        (folder / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return

    first = {}
    dup_counts = collections.Counter()
    for r in rows:
        dup_counts[r["seq"]] += 1
        if r["seq"] not in first or r["t_done_ms"] < first[r["seq"]]["t_done_ms"]:
            first[r["seq"]] = r
    missing = sorted(set(sent) - set(first))
    extras = sorted(set(first) - set(sent))
    dups = {s: c for s, c in dup_counts.items() if c > 1}

    uniq = list(first.values())
    # Latency is reported over the same steady window as throughput: the first
    # WARMUP fraction is dropped, because while the consumer group is still being
    # assigned its partitions the early messages wait in the queue, which says
    # nothing about steady-state behaviour. The figures including that warm-up are
    # reported alongside, so nothing is hidden.
    by_done = sorted(uniq, key=lambda r: r["t_done_ms"])
    steady = by_done[int(len(by_done) * WARMUP):]
    if a.warmup_seconds > 0 and uniq:
        t0 = min(r["kafka_ts_ms"] for r in uniq)
        cutoff = t0 + a.warmup_seconds * 1000
        steady = [r for r in steady if r["kafka_ts_ms"] >= cutoff]

    def lat(rows_):
        return ([r["t_done_ms"] - r["kafka_ts_ms"] for r in rows_],
                [r["t_recv_ms"] - r["kafka_ts_ms"] for r in rows_],
                [r["infer_ms"] for r in rows_], [r["es_ms"] for r in rows_])

    e2e, wait, infer, es = lat(steady)
    e2e_all, wait_all, infer_all, es_all = lat(uniq)

    per_node = collections.Counter(r["node"] for r in uniq)
    per_proc = collections.Counter(f"{r['node']}#{r['pid']}" for r in uniq)
    per_part = collections.Counter(r["partition"] for r in uniq)
    node_wait_min = {n: round(min(r["t_recv_ms"] - r["kafka_ts_ms"] for r in uniq if r["node"] == n), 1)
                     for n in per_node}
    skewed = [n for n, w in node_wait_min.items() if w < 0]

    total = throughput(uniq)
    by_node = {n: throughput([r for r in uniq if r["node"] == n]) for n in per_node}

    metrics = {
        "run_id": run_id, "mode": mode, "partitions": manifest.get("partitions"),
        "warmup": {"fraction_dropped": WARMUP, "seconds_dropped": a.warmup_seconds,
                   "messages_in_steady_window": len(steady)},
        "sent": len(sent), "processed_unique": len(uniq), "processed_rows": len(rows),
        "missing": len(missing), "duplicates": len(dups), "extras": len(extras),
        "throughput": total, "throughput_by_node": by_node,
        "latency_ms": {"end_to_end": stats_block(e2e), "kafka_wait": stats_block(wait),
                       "inference": stats_block(infer), "elasticsearch": stats_block(es)},
        "latency_ms_including_warmup": {
            "end_to_end": stats_block(e2e_all), "kafka_wait": stats_block(wait_all),
            "inference": stats_block(infer_all), "elasticsearch": stats_block(es_all)},
        "balance": {"per_node": dict(per_node), "per_processor": dict(per_proc),
                    "per_partition": dict(sorted(per_part.items())),
                    "processor_max_min_ratio": round(max(per_proc.values()) / min(per_proc.values()), 2)
                    if len(per_proc) > 1 else 1.0},
        "clock": {"min_kafka_wait_ms_by_node": node_wait_min, "skewed_nodes": skewed},
    }

    lines.append("")
    lines.append(f"Throughput (steady, first {int(WARMUP*100)}% dropped): "
                 f"{total['msgs_per_sec'] if total else 'n/a'} msg/s "
                 f"over {total['window_seconds'] if total else 0}s")
    for n, t in by_node.items():
        lines.append(f"  {n}: {t['msgs_per_sec'] if t else 'n/a'} msg/s ({per_node[n]} messages)")

    if a.baseline:
        bfile = run_dir(a.baseline) / "metrics.json"
        if not bfile.exists():
            lines.append(f"  speed-up: analyse the baseline run first ({bfile} missing)")
        else:
            base = json.loads(bfile.read_text(encoding="utf-8")).get("throughput") or {}
            if base.get("msgs_per_sec") and total:
                n_proc = len(per_proc)
                s = total["msgs_per_sec"] / base["msgs_per_sec"]
                metrics["speedup"] = {"baseline_run": a.baseline,
                                      "baseline_msgs_per_sec": base["msgs_per_sec"],
                                      "speedup": round(s, 2), "processors": n_proc,
                                      "efficiency": round(s / n_proc, 2) if n_proc else None}
                lines.append(f"  speed-up vs {a.baseline}: {s:.2f}x on {n_proc} processor(s) "
                             f"(efficiency {s/n_proc:.2f})")

    lines.append("")
    if mode == "preload":
        lines.append("Latency (preload mode: end-to-end includes backlog wait, so only the")
        lines.append("  model and Elasticsearch columns are meaningful; use a rate run for latency)")
    else:
        lines.append(f"Latency in ms (steady window, first {int(WARMUP*100)}% dropped)")
    for name, block in metrics["latency_ms"].items():
        if block:
            lines.append(f"  {name:<14} p50 {block['p50']:>9} | p95 {block['p95']:>9} | "
                         f"p99 {block['p99']:>9} | max {block['max']:>9}")
    warm = metrics["latency_ms_including_warmup"]["end_to_end"]
    if warm and metrics["latency_ms"]["end_to_end"]:
        lines.append(f"  (including the warm-up, end-to-end p95 would be {warm['p95']} ms "
                     f"and p99 {warm['p99']} ms: the consumer group is still being assigned)")

    lines.append("")
    lines.append(f"Balance: per processor {dict(per_proc)} (max/min "
                 f"{metrics['balance']['processor_max_min_ratio']})")
    lines.append(f"         per partition {metrics['balance']['per_partition']}")

    lines.append("")
    lines.append(f"{'PASS' if not missing else 'FAIL'} delivery: {len(uniq)}/{len(sent)} processed"
                 + (f", missing {missing[:10]}{'…' if len(missing) > 10 else ''}" if missing else ""))
    lines.append(f"{'PASS' if not dups else 'WARN'} duplicates: {len(dups)}"
                 + (f" (Kafka at-least-once; e.g. {list(dups)[:5]})" if dups else ""))
    lines.append(f"{'PASS' if not extras else 'FAIL'} no unknown extras: {len(extras)}")
    if len(per_node) > 1:
        lines.append(f"{'PASS' if not skewed else 'WARN'} clock sanity across machines: "
                     f"min Kafka wait per node {node_wait_min}"
                     + (" — negative means that clock is behind; cross-machine latency invalid"
                        if skewed else ""))
    else:
        lines.append("n/a  clock sanity: single machine")

    if a.reference:
        ref_rows, _ = load_bench(run_dir(a.reference), "")
        ref = {}
        for r in ref_rows:
            ref.setdefault(r["seq"], r["label"])
        common = [s for s in first if s in ref]
        if not common:
            lines.append("WARN label agreement: no shared messages with the reference run")
        else:
            bad = [s for s in common if first[s]["label"] != ref[s]]
            agree = 100.0 * (len(common) - len(bad)) / len(common)
            metrics["label_agreement"] = {"reference_run": a.reference, "compared": len(common),
                                          "mismatches": len(bad), "agreement_pct": round(agree, 2)}
            lines.append(f"{'PASS' if not bad else 'WARN'} label agreement with {a.reference}: "
                         f"{agree:.2f}% over {len(common)} messages"
                         + (f", mismatches e.g. {bad[:5]}" if bad else ""))

    text = "\n".join(lines)
    print(text)
    (folder / "summary.txt").write_text(text + "\n", encoding="utf-8")
    (folder / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(f"\n-> Saved: {folder / 'metrics.json'} and summary.txt")


if __name__ == "__main__":
    main()
