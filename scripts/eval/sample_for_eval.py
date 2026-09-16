"""
sample_for_eval.py — sample records from ES into a benchmark CSV.

Two sampling strategies:
  --bias none   (default)  Stratified random across env_domain. Representative,
                           but on real traffic ~93% lands NORMAL → few toxic
                           examples, which makes toxic-class metrics noisy.
  --bias toxic             Oversamples the INTERESTING records: every toxic
                           Tier-1 prediction, every Tier-1/Tier-2 disagreement,
                           and the lowest-confidence borderline cases, then tops
                           up with a little NORMAL for contrast. This is how you
                           grow the toxic class fast for a conclusive eval.

Append mode (so you never re-label or duplicate work):
  --append PATH            Merge new rows INTO an existing labelled CSV. Rows
                           already present (by message_id OR by text+author) are
                           skipped, so your existing human_ground_truth labels
                           are preserved and nothing is duplicated. New rows get
                           a blank human_ground_truth for you to fill in.

Usage:
    # First-ever toxic-biased sample of 300:
    python scripts/eval/sample_for_eval.py --bias toxic --target-size 300 --apply

    # Later: add 200 MORE toxic-biased rows to the existing labelled file:
    python scripts/eval/sample_for_eval.py --bias toxic --target-size 200 \\
        --append thesis_benchmark_eval.csv --apply

After appending, label ONLY the new blank rows, then re-run the replays WITHOUT
--force (they skip already-done rows and only process the new ones).
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

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from shared_utils.config import ES_HOST, INDEX_NAME

TOXIC_LABELS = {"HATE", "OFFENSIVE"}

REQUIRED_FIELDS = [
    "message_id", "timestamp", "source_platform",
    "env_domain", "env_domain_raw", "env_domain_match", "env_subgenre",
    "env_strictness", "env_strictness_reasoning",
    "text", "author_id", "author_name",
    "model_label", "model_confidence", "processing_time_ms",
    "agent_final_decision", "agent_explanation", "agent_latency_seconds",
    "agent_memory_used", "agent_memory_user_msgs", "agent_memory_thread_msgs",
    "agent_memory_user_profile",
    "human_ground_truth",   # left blank — you fill this in
]


def fetch_reviewed_records(es):
    query = {"query": {"term": {"agent_reviewed": True}}}
    for hit in scan(es, index=INDEX_NAME, query=query, size=500):
        yield hit["_source"]


def _interest_score(r):
    """Higher = more valuable to hand-label. Toxic + disagreement + ambiguity."""
    score = 0.0
    label = str(r.get("model_label", "")).strip().upper()
    decision = str(r.get("agent_final_decision", "")).strip().lower()
    try:
        conf = float(r.get("model_confidence", 1.0) or 1.0)
    except (TypeError, ValueError):
        conf = 1.0

    if label in TOXIC_LABELS:
        score += 3.0                      # rare toxic Tier-1 prediction
    if decision in ("false positive", "false negative"):
        score += 2.0                      # Tier-1/Tier-2 disagreement
    if conf < 0.60:
        score += 1.0                      # genuinely borderline
    elif conf < 0.80:
        score += 0.5
    return score


def stratified_sample(records, target_size, per_domain_cap, seed):
    rng = random.Random(seed)
    by_domain = {}
    for r in records:
        by_domain.setdefault(r.get("env_domain") or "Unknown", []).append(r)
    if not by_domain:
        return []
    if per_domain_cap is None:
        per_domain_cap = max(1, math.ceil(target_size / len(by_domain)))
    chosen = []
    for rs in by_domain.values():
        rng.shuffle(rs)
        chosen.extend(rs[:per_domain_cap])
    rng.shuffle(chosen)
    return chosen[:target_size]


def toxic_biased_sample(records, target_size, seed, normal_fraction=0.25):
    """
    Prioritise interesting records (toxic / disagreement / ambiguous), then
    top up with a slice of NORMAL for contrast so the labeller still sees both.
    """
    rng = random.Random(seed)
    scored = [(r, _interest_score(r)) for r in records]
    interesting = [r for r, s in scored if s > 0]
    plain = [r for r, s in scored if s == 0]

    interesting.sort(key=_interest_score, reverse=True)
    n_normal = int(target_size * normal_fraction)
    n_interesting = target_size - n_normal

    rng.shuffle(plain)
    chosen = interesting[:n_interesting] + plain[:n_normal]
    rng.shuffle(chosen)
    return chosen[:target_size]


def _existing_keys(append_path):
    """Return (message_ids set, text+author set) already present in the CSV."""
    if not append_path or not os.path.exists(append_path):
        return set(), set()
    df = pd.read_csv(append_path)
    ids = set(df.get("message_id", pd.Series([], dtype=str)).astype(str))
    ta = set(
        (str(t).strip() + "||" + str(a).strip())
        for t, a in zip(df.get("text", []), df.get("author_name", []))
    )
    return ids, ta


def to_dataframe(records):
    rows = []
    for r in records:
        row = {f: r.get(f, "") for f in REQUIRED_FIELDS}
        row["human_ground_truth"] = ""
        rows.append(row)
    return pd.DataFrame(rows)[REQUIRED_FIELDS]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--apply", action="store_true", help="Write the CSV (default: dry run).")
    p.add_argument("--bias", choices=["none", "toxic"], default="none",
                   help="Sampling strategy (default: none = stratified random).")
    p.add_argument("--target-size", type=int, default=300, help="How many NEW rows to sample.")
    p.add_argument("--per-domain", type=int, default=None, help="Per-domain cap (bias=none only).")
    p.add_argument("--append", default=None, help="Existing CSV to append into (dedupes, preserves labels).")
    p.add_argument("--output", default="thesis_benchmark_eval.csv", help="Output CSV (ignored if --append given).")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    out_path = args.append or args.output

    es = Elasticsearch(ES_HOST, request_timeout=30)
    print(f"-> ES: {ES_HOST} | INDEX: {INDEX_NAME}")
    print(f"-> Bias: {args.bias} | Target NEW rows: {args.target_size}")
    print(f"-> Append into: {args.append or '(none — fresh file)'}")
    print(f"-> Output: {out_path}")
    print(f"-> Mode: {'APPLY' if args.apply else 'DRY RUN'}")
    print()

    print("-> Streaming reviewed records from ES...")
    records = list(fetch_reviewed_records(es))
    print(f"-> {len(records)} reviewed records in ES.")
    if not records:
        print("Nothing to sample — run the batch judge first.")
        return

    # Exclude records already in the append target.
    existing_ids, existing_ta = _existing_keys(args.append)
    if existing_ids:
        before = len(records)
        records = [
            r for r in records
            if str(r.get("message_id")) not in existing_ids
            and (str(r.get("text", "")).strip() + "||" + str(r.get("author_name", "")).strip()) not in existing_ta
        ]
        print(f"-> Excluded {before - len(records)} records already in {args.append}.")

    if args.bias == "toxic":
        sample = toxic_biased_sample(records, args.target_size, args.seed)
    else:
        sample = stratified_sample(records, args.target_size, args.per_domain, args.seed)

    # Report toxic/disagreement composition of the sample.
    n_tox = sum(1 for r in sample if str(r.get("model_label", "")).strip().upper() in TOXIC_LABELS)
    n_dis = sum(1 for r in sample if str(r.get("agent_final_decision", "")).strip().lower() in ("false positive", "false negative"))
    print(f"\n-> Sampled {len(sample)} new rows: {n_tox} toxic-predicted, {n_dis} Tier-1/Tier-2 disagreements.")

    new_df = to_dataframe(sample)

    if args.append and os.path.exists(args.append):
        old_df = pd.read_csv(args.append)
        merged = pd.concat([old_df, new_df], ignore_index=True)
        merged = merged.drop_duplicates(subset=["text", "author_name"], keep="first")
        print(f"-> Merged: {len(old_df)} existing + {len(new_df)} new = {len(merged)} total (after dedup).")
        final_df = merged
    else:
        final_df = new_df

    if args.apply:
        final_df.to_csv(out_path, index=False, encoding="utf-8")
        print(f"\n[OK] Wrote {out_path} ({len(final_df)} rows).")
        blanks = (final_df["human_ground_truth"].astype(str).str.strip().replace("nan", "").str.len() == 0).sum()
        print(f"-> Rows needing a human_ground_truth label: {blanks}")
        print("\nNext:")
        print(f"  1. Label ONLY the blank human_ground_truth rows in {out_path}.")
        print(f"  2. python -u scripts/eval/replay_with_memory.py --csv {out_path} --apply   # no --force = only new rows")
        print(f"     python scripts/eval/sync_es_to_csv.py {out_path} --apply")
        print(f"  3. python -u scripts/setup/seed_rag_from_csv.py {out_path} --apply")
        print(f"     python -u scripts/eval/replay_with_rag.py --csv {out_path} --apply       # no --force = only new rows")
        print(f"  4. python -u scripts/eval/replay_with_multi_agent.py --csv {out_path} --apply  # no --force = only new rows")
        print(f"  5. python scripts/eval/check_results.py {out_path}")
    else:
        print("\nDry run. Re-run with --apply to write.")


if __name__ == "__main__":
    main()
