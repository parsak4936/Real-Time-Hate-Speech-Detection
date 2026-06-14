"""
seed_rag_from_csv.py — populate the Qdrant collection directly from a labelled CSV.

Purpose:
    Stage 3 RAG can be evaluated WITHOUT live ES data, using the existing
    internship benchmark CSV as the retrieval corpus. This script reads
    a CSV, embeds the `text` column, and upserts the resulting vectors
    into the configured Qdrant collection — with each row's Tier-1 label,
    Tier-2 baseline verdict, and env_domain stored as payload.

    `human_ground_truth` is deliberately NOT included in the payload so
    that leave-one-out evaluation (replay_with_rag.py) cannot accidentally
    leak labels back through the retrieval channel.

Usage:
    # Preview only — DEFAULT — no writes:
    python scripts/seed_rag_from_csv.py thesis_final_benchmark.csv

    # Actually populate Qdrant:
    python scripts/seed_rag_from_csv.py thesis_final_benchmark.csv --apply

    # Smoke test on first N rows:
    python scripts/seed_rag_from_csv.py thesis_final_benchmark.csv --apply --limit 50

Idempotent — re-running overwrites existing points by stable hash of message_id
(or row index if the CSV has no message_id column).

Requires:
    Docker stack up (Qdrant reachable) and sentence-transformers installed
    (first run downloads the embedding model ~80 MB).
"""

import argparse
import os
import sys
import time

import pandas as pd

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from shared_utils.config import QDRANT_COLLECTION


def _csv_rows_to_records(df: pd.DataFrame):
    """Turn each CSV row into a dict shaped like the ES doc that rag.py expects."""
    has_message_id = "message_id" in df.columns
    for idx, row in df.iterrows():
        text = str(row.get("text", "") or "").strip()
        if not text:
            continue

        # Synthesise a stable id when the CSV pre-dates the message_id column.
        message_id = str(row["message_id"]) if has_message_id and pd.notna(row["message_id"]) else f"csv-row-{idx}"
        if message_id in ("", "nan", "UNKNOWN"):
            message_id = f"csv-row-{idx}"

        yield {
            "message_id":            message_id,
            "text":                  text,
            "timestamp":             str(row.get("timestamp", "") or ""),
            "author_id":             str(row.get("author_id", "") or ""),
            "author_name":           str(row.get("author_name", "") or ""),
            "env_domain":            str(row.get("env_domain", "") or ""),
            "env_subgenre":          str(row.get("env_subgenre", "") or ""),
            "env_strictness":        str(row.get("env_strictness", "") or ""),
            "model_label":           str(row.get("model_label", "") or ""),
            "model_confidence":      float(row.get("model_confidence", 0) or 0),
            "agent_final_decision":  str(row.get("agent_final_decision", "") or ""),
            # IMPORTANT: human_ground_truth deliberately omitted from payload
            # so leave-one-out replay cannot leak labels through retrieval.
        }


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("csv", help="Path to the benchmark CSV (e.g. thesis_final_benchmark.csv).")
    parser.add_argument("--apply", action="store_true", help="Actually upsert vectors (default: dry run).")
    parser.add_argument("--limit", type=int, default=None, help="Cap the number of rows to process.")
    args = parser.parse_args()

    if not os.path.exists(args.csv):
        print(f"[ERROR] CSV not found: {args.csv}")
        sys.exit(1)

    df = pd.read_csv(args.csv)
    if args.limit is not None:
        df = df.head(args.limit)

    print(f"-> CSV: {args.csv} ({len(df)} rows)")
    print(f"-> Qdrant collection: {QDRANT_COLLECTION}")
    print(f"-> Mode: {'APPLY (writing vectors)' if args.apply else 'DRY RUN (no writes)'}")
    print()

    if args.apply:
        from shared_utils.rag import index_records_bulk, get_client
        get_client()  # ensure collection exists

        start = time.time()
        records = list(_csv_rows_to_records(df))
        print(f"-> Embedding {len(records)} records...")
        indexed = index_records_bulk(records)
        elapsed = time.time() - start
        print(f"\n[OK] Indexed {indexed}/{len(records)} records into Qdrant in {elapsed:.1f}s.")
    else:
        count = sum(1 for _ in _csv_rows_to_records(df))
        print(f"Would index: {count} records")
        if count:
            print("\nRe-run with --apply to actually populate Qdrant.")


if __name__ == "__main__":
    main()
