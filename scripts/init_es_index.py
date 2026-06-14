"""
init_es_index.py — create the moderation Elasticsearch index with the
canonical field mapping from config/es_index_template.json.

Run this ONCE after `src/reset_db.py --yes` to ensure every field has the
right ES type (keyword vs text vs float vs date vs boolean) before any
records are written. Without it, ES auto-detects types from the first
record and any later record with a different type causes a write rejection.

Usage:
    # Preview only — DEFAULT — no writes:
    python scripts/init_es_index.py

    # Actually create the index (fails if it exists already; use --force to drop+recreate):
    python scripts/init_es_index.py --apply

    # Drop existing index and recreate:
    python scripts/init_es_index.py --apply --force

Audit checklist after running with --apply:
    curl -s http://localhost:9200/real_time_analysis/_mapping | python -m json.tool
    # The output should match config/es_index_template.json field-for-field.
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from elasticsearch import Elasticsearch

from shared_utils.config import ES_HOST, INDEX_NAME

TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "config" / "es_index_template.json"


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--apply", action="store_true", help="Actually create the index (default: preview).")
    parser.add_argument("--force", action="store_true", help="Drop existing index first.")
    args = parser.parse_args()

    if not TEMPLATE_PATH.exists():
        print(f"[ERROR] Template not found: {TEMPLATE_PATH}")
        sys.exit(1)

    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        template = json.load(f)

    es = Elasticsearch(ES_HOST)
    exists = es.indices.exists(index=INDEX_NAME)

    print(f"-> Elasticsearch: {ES_HOST}")
    print(f"-> Target index:  {INDEX_NAME}")
    print(f"-> Index exists:  {exists}")
    print(f"-> Mode:          {'APPLY' if args.apply else 'DRY RUN'}{' + FORCE' if args.force else ''}")
    print()

    fields = template["mappings"]["properties"]
    print(f"Template defines {len(fields)} fields:")
    for name, spec in fields.items():
        print(f"  - {name:36s} {spec['type']}")
    print()

    if not args.apply:
        print("Re-run with --apply to create the index.")
        return

    if exists and not args.force:
        print(f"[BLOCKED] Index {INDEX_NAME!r} already exists. Use --force to drop and recreate.")
        sys.exit(2)

    if exists and args.force:
        print(f"-> Dropping existing index {INDEX_NAME!r}...")
        es.indices.delete(index=INDEX_NAME)

    print(f"-> Creating index {INDEX_NAME!r} with the template mapping...")
    es.indices.create(index=INDEX_NAME, body=template)
    print(f"[OK] Index {INDEX_NAME!r} created with {len(fields)} explicitly-typed fields.")
    print()
    print("Verify:")
    print(f"  curl -s http://localhost:9200/{INDEX_NAME}/_mapping | python -m json.tool")


if __name__ == "__main__":
    main()
