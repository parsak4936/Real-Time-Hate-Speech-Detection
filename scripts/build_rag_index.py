"""
build_rag_index.py — bootstrap the Qdrant vector index from existing ES records.

Purpose:
    Before the memory+RAG judge prompt can do useful retrieval, the Qdrant
    collection needs to contain the historical moderation corpus. This
    script walks Elasticsearch, embeds every record's text with the model
    configured in config/rag.yaml, and upserts the resulting vectors into
    the configured Qdrant collection.

    Idempotent — re-running the script overwrites existing points in place
    rather than duplicating them (point IDs are derived from message_id).

Usage:
    # Preview only — DEFAULT — no writes:
    python scripts/build_rag_index.py

    # Actually populate Qdrant:
    python scripts/build_rag_index.py --apply

    # Smoke test on the first N records:
    python scripts/build_rag_index.py --apply --limit 50

    # Restrict to records marked agent_reviewed=True (curated corpus only):
    python scripts/build_rag_index.py --apply --reviewed-only

Requires:
    - Docker stack up (Elasticsearch + Qdrant reachable).
    - sentence-transformers + qdrant-client installed (see requirements.txt).
    - First run downloads the embedding model (~80 MB by default).
"""

import argparse
import os
import sys
import time

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from elasticsearch import Elasticsearch
from elasticsearch.helpers import scan

from shared_utils.config import ES_HOST, INDEX_NAME, QDRANT_COLLECTION


def _iter_es_records(es: Elasticsearch, reviewed_only: bool, limit: int | None):
    """Yield ES source dicts for records that should be indexed."""
    query = (
        {"query": {"term": {"agent_reviewed": True}}}
        if reviewed_only
        else {"query": {"match_all": {}}}
    )
    yielded = 0
    for hit in scan(es, index=INDEX_NAME, query=query, size=500):
        yield hit["_source"]
        yielded += 1
        if limit is not None and yielded >= limit:
            return


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--apply", action="store_true", help="Actually upsert vectors into Qdrant (default: dry run).")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap the number of ES records to process.",
    )
    parser.add_argument(
        "--reviewed-only",
        action="store_true",
        help="Only index records with agent_reviewed=True (curated corpus).",
    )
    args = parser.parse_args()

    es = Elasticsearch(ES_HOST)
    print(f"-> Elasticsearch: {ES_HOST} | INDEX: {INDEX_NAME}")
    print(f"-> Qdrant collection: {QDRANT_COLLECTION}")
    print(f"-> Mode: {'APPLY (writing vectors)' if args.apply else 'DRY RUN (no writes)'}")
    if args.reviewed_only:
        print("-> Filter: agent_reviewed=True only")
    if args.limit:
        print(f"-> Limit: first {args.limit} records")
    print()

    if args.apply:
        # Lazy-import — avoids paying the sentence-transformers startup cost on a dry run.
        from shared_utils.rag import index_records_bulk, get_client
        get_client()  # initialise + create collection if needed

        start = time.time()
        records = list(_iter_es_records(es, args.reviewed_only, args.limit))
        print(f"-> Pulled {len(records)} records from Elasticsearch.")
        if not records:
            print("Nothing to index.")
            return

        indexed = index_records_bulk(records)
        elapsed = time.time() - start
        print(f"\n[OK] Indexed {indexed}/{len(records)} records into Qdrant in {elapsed:.1f}s.")
    else:
        # Dry-run: just count.
        count = 0
        skipped_no_text = 0
        skipped_no_id = 0
        for source in _iter_es_records(es, args.reviewed_only, args.limit):
            text = (source.get("text") or "").strip()
            mid = source.get("message_id") or ""
            if not text:
                skipped_no_text += 1
                continue
            if not mid or mid == "UNKNOWN":
                skipped_no_id += 1
                continue
            count += 1

        print(f"Would index:        {count} records")
        print(f"Would skip (no text): {skipped_no_text}")
        print(f"Would skip (no id):   {skipped_no_id}")
        if count:
            print("\nRe-run with --apply to actually populate Qdrant.")


if __name__ == "__main__":
    main()
