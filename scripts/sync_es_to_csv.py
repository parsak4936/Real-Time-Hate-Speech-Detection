"""
sync_es_to_csv.py — pull Tier-2 verdict columns from Elasticsearch into a benchmark CSV.

Why this exists:
    `replay_with_memory.py` writes the memory-augmented verdict to Elasticsearch
    (so it survives across notebook runs and operator dashboard queries). The
    CSV is left unchanged. For the evaluation notebook, we need those columns
    IN the CSV. This script bridges that gap: for each row in the CSV, it
    looks up the corresponding ES record by message_id and copies these
    fields into new columns:

        agent_final_decision_with_memory
        agent_explanation_with_memory
        agent_memory_used
        agent_memory_user_msgs
        agent_memory_thread_msgs
        agent_memory_user_profile

    Existing labels in the CSV (human_ground_truth, etc.) are preserved.

Usage:
    # Preview only
    python scripts/sync_es_to_csv.py thesis_benchmark_eval.csv

    # Actually write the merged CSV
    python scripts/sync_es_to_csv.py thesis_benchmark_eval.csv --apply
"""

import argparse
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from elasticsearch import Elasticsearch

from shared_utils.config import ES_HOST, INDEX_NAME

# Fields we want to pull from ES into the CSV.
ES_FIELDS_TO_SYNC = [
    "agent_final_decision_with_memory",
    "agent_explanation_with_memory",
    "agent_memory_used",
    "agent_memory_user_msgs",
    "agent_memory_thread_msgs",
    "agent_memory_user_profile",
    # If you've already run replay_with_rag and want to back-sync those too:
    "agent_final_decision_with_rag",
    "agent_explanation_with_rag",
    "agent_retrieved_precedent_ids",
    "agent_retrieval_count",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv", help="Path to the benchmark CSV to sync.")
    parser.add_argument("--apply", action="store_true",
                        help="Write the merged CSV. Default is dry run.")
    args = parser.parse_args()

    if not os.path.exists(args.csv):
        print(f"[ERROR] CSV not found: {args.csv}")
        sys.exit(1)

    df = pd.read_csv(args.csv)
    print(f"-> Loaded {args.csv}: {len(df)} rows.")

    if "message_id" not in df.columns:
        print("[ERROR] CSV has no message_id column — can't look up records in ES.")
        sys.exit(1)

    es = Elasticsearch(ES_HOST, request_timeout=30)

    # Initialise the target columns if missing.
    for f in ES_FIELDS_TO_SYNC:
        if f not in df.columns:
            df[f] = ""

    n_synced = 0
    n_not_found = 0
    n_skipped = 0

    for idx, row in df.iterrows():
        msg_id = str(row.get("message_id") or "").strip()
        if not msg_id or msg_id == "UNKNOWN":
            n_skipped += 1
            continue

        try:
            res = es.search(
                index=INDEX_NAME,
                body={"query": {"term": {"message_id": msg_id}}, "size": 1},
            )
            hits = res["hits"]["hits"]
        except Exception as exc:
            print(f"[warn] ES query failed for {msg_id}: {exc}")
            n_skipped += 1
            continue

        if not hits:
            n_not_found += 1
            continue

        source = hits[0]["_source"]
        for f in ES_FIELDS_TO_SYNC:
            val = source.get(f)
            if val is not None:
                df.at[idx, f] = val

        n_synced += 1

        if (idx + 1) % 50 == 0:
            print(f"  ...{idx + 1}/{len(df)} rows processed")

    print()
    print(f"Synced from ES: {n_synced}")
    print(f"Not found in ES: {n_not_found}")
    print(f"Skipped (no message_id): {n_skipped}")

    # Show per-column populated count
    print("\nPer-column populated count after sync:")
    for f in ES_FIELDS_TO_SYNC:
        if f in df.columns:
            populated = (df[f].astype(str).str.strip() != "").sum()
            print(f"  {f:<42s} {populated}")

    if args.apply:
        df.to_csv(args.csv, index=False, encoding="utf-8")
        print(f"\n[OK] Wrote {args.csv}")
    else:
        print("\nDry run. Re-run with --apply to write the CSV.")


if __name__ == "__main__":
    main()
