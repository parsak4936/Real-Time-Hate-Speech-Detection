"""
sample_for_eval.py — stratified random sample from ES for evaluation.

Pulls a representative sample of REVIEWED records (those with a Tier-2
verdict) across env_domain values, balanced so every domain contributes
something. The output CSV is what you manually label `human_ground_truth`
on, then feed to `replay_with_memory.py` and `replay_with_rag.py` for the
two-variant evaluation.

Why stratified rather than uniform random:
    A pure random sample of 300 from 70k records is dominated by whichever
    domain happens to be the most numerous (probably Gaming or whatever
    your busy YouTube stream is). Stratified gives every domain a chance
    to land in the benchmark, so the notebook's per-domain breakdown has
    enough records per domain to be meaningful.

Usage:
    # Preview the sample without writing:
    python scripts/sample_for_eval.py

    # Write the CSV:
    python scripts/sample_for_eval.py --apply

    # Target a larger sample (default 300):
    python scripts/sample_for_eval.py --apply --target-size 500

    # Cap per-domain rows (default: target_size / number_of_domains):
    python scripts/sample_for_eval.py --apply --per-domain 50

    # Custom output filename:
    python scripts/sample_for_eval.py --apply --output bench_2026_06_13.csv

Defaults:
    - Pulls only reviewed records (has agent_final_decision)
    - Up to ceil(target_size / n_domains) per domain
    - Random seed defaults to 42 for reproducibility
"""

import argparse
import math
import os
import random
import sys
from pathlib import Path

import pandas as pd
from elasticsearch import Elasticsearch
from elasticsearch.helpers import scan

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shared_utils.config import ES_HOST, INDEX_NAME


# Columns the notebook + replay scripts expect downstream.
REQUIRED_FIELDS = [
    "message_id",
    "timestamp",
    "source_platform",
    "env_domain",
    "env_domain_raw",
    "env_domain_match",
    "env_subgenre",
    "env_strictness",
    "env_strictness_reasoning",
    "text",
    "author_id",
    "author_name",
    "model_label",
    "model_confidence",
    "processing_time_ms",
    "agent_final_decision",
    "agent_explanation",
    "agent_latency_seconds",
    "agent_memory_used",
    "agent_memory_user_msgs",
    "agent_memory_thread_msgs",
    "agent_memory_user_profile",
    "human_ground_truth",   # left blank — you fill this in
]


def fetch_reviewed_records(es: Elasticsearch):
    """Stream every reviewed record from ES via scan."""
    query = {"query": {"term": {"agent_reviewed": True}}}
    for hit in scan(es, index=INDEX_NAME, query=query, size=500):
        yield hit["_source"]


def stratified_sample(records: list, target_size: int, per_domain_cap: int | None, seed: int):
    """Return up to target_size records, capped per env_domain."""
    rng = random.Random(seed)
    by_domain: dict[str, list] = {}
    for r in records:
        d = r.get("env_domain") or "Unknown"
        by_domain.setdefault(d, []).append(r)

    if not by_domain:
        return []

    if per_domain_cap is None:
        per_domain_cap = max(1, math.ceil(target_size / len(by_domain)))

    chosen = []
    for d, rs in by_domain.items():
        rng.shuffle(rs)
        chosen.extend(rs[:per_domain_cap])

    rng.shuffle(chosen)
    return chosen[:target_size]


def to_dataframe(records: list) -> pd.DataFrame:
    rows = []
    for r in records:
        row = {field: r.get(field, "") for field in REQUIRED_FIELDS}
        row["human_ground_truth"] = ""   # explicit reset — never trust ES for this
        rows.append(row)
    df = pd.DataFrame(rows)
    return df[REQUIRED_FIELDS]


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--apply", action="store_true",
                        help="Write the CSV. Default is dry-run (preview only).")
    parser.add_argument("--target-size", type=int, default=300,
                        help="Total sample size (default: 300).")
    parser.add_argument("--per-domain", type=int, default=None,
                        help="Cap per domain. Default: ceil(target_size / n_domains).")
    parser.add_argument("--output", default="thesis_benchmark_eval.csv",
                        help="Output CSV path.")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed for reproducibility (default: 42).")
    args = parser.parse_args()

    es = Elasticsearch(ES_HOST, request_timeout=30)
    print(f"-> ES: {ES_HOST} | INDEX: {INDEX_NAME}")
    print(f"-> Target sample size: {args.target_size}")
    print(f"-> Per-domain cap: {args.per_domain or 'auto'}")
    print(f"-> Random seed: {args.seed}")
    print(f"-> Output: {args.output}")
    print(f"-> Mode: {'APPLY (writing CSV)' if args.apply else 'DRY RUN (no CSV write)'}")
    print()

    print("-> Streaming reviewed records from ES...")
    records = list(fetch_reviewed_records(es))
    print(f"-> Found {len(records)} reviewed records total.")
    if not records:
        print("Nothing to sample — run the batch judge first.")
        return

    sample = stratified_sample(records, args.target_size, args.per_domain, args.seed)
    print(f"-> Sampled {len(sample)} records across {len({r.get('env_domain') for r in sample})} domains.")

    # Per-domain summary
    counts = {}
    for r in sample:
        counts[r.get("env_domain") or "Unknown"] = counts.get(r.get("env_domain") or "Unknown", 0) + 1
    print("\nPer-domain breakdown of the sample:")
    for d, n in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {d:<25s} {n}")

    df = to_dataframe(sample)
    print(f"\nCSV preview (first 3 rows, key columns):")
    preview = df[["env_domain", "env_subgenre", "model_label", "agent_final_decision", "text"]].head(3)
    print(preview.to_string(index=False))

    if args.apply:
        df.to_csv(args.output, index=False, encoding="utf-8")
        print(f"\n[OK] Wrote {args.output} ({len(df)} rows, {len(REQUIRED_FIELDS)} columns).")
        print("Next steps:")
        print(f"  1. Open {args.output}, fill in `human_ground_truth` column (NORMAL / OFFENSIVE / HATE).")
        print(f"  2. python scripts/replay_with_memory.py --csv {args.output} --apply")
        print(f"  3. python scripts/replay_with_rag.py    --csv {args.output} --apply")
        print(f"  4. In notebook: change BENCHMARK_CSV to '{args.output}' and Restart & Run All.")
    else:
        print(f"\nRe-run with --apply to write the CSV.")


if __name__ == "__main__":
    main()
