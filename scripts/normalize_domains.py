"""
Domain-taxonomy backfill.

The Stage-0 cleanup pinned env_domain to a closed 10-value taxonomy
(see src/shared_utils/prompts.py::ENV_DOMAINS) and introduced an
env_subgenre free-text field. Existing documents indexed under the
previous open taxonomy may carry compound values like:

    env_domain = "Gaming/Survival"
    env_domain = "Gaming/Esports"
    env_domain = "Politics/News"

This script walks the live Elasticsearch index, splits those compound
values on the first "/", and rewrites each affected document:

    env_domain    = "Gaming"
    env_subgenre  = "Survival"

Usage:
    # Preview only — DEFAULT — no writes:
    python scripts/normalize_domains.py

    # Actually apply the rewrites:
    python scripts/normalize_domains.py --apply

The script processes the index in batches via the scroll API and prints
a summary at the end. It is idempotent: running it twice is harmless.
"""

import argparse
import os
import sys

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from elasticsearch import Elasticsearch
from elasticsearch.helpers import scan

from shared_utils.config import ES_HOST, INDEX_NAME
from shared_utils.prompts import ENV_DOMAINS


def normalize(raw_domain: str, existing_subgenre: str):
    """
    Returns (new_domain, new_subgenre, changed).

    - If raw_domain is already in the closed taxonomy, no change.
    - If raw_domain is "X/Y", split on the first slash. If X is in the
      taxonomy, use X as the main domain and Y as the subgenre (unless
      a subgenre already exists, in which case we keep the existing one).
    - Otherwise clamp to "General".
    """
    if raw_domain in ENV_DOMAINS:
        return raw_domain, existing_subgenre or "", False

    if "/" in raw_domain:
        head, tail = raw_domain.split("/", 1)
        head = head.strip()
        tail = tail.strip()
        if head in ENV_DOMAINS:
            new_sub = existing_subgenre if existing_subgenre else tail
            return head, new_sub, True

    # Last-resort clamp
    return "General", existing_subgenre or (raw_domain or ""), True


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Actually update ES (default is dry-run)")
    parser.add_argument("--index", default=INDEX_NAME, help=f"Index to scan (default: {INDEX_NAME})")
    args = parser.parse_args()

    es = Elasticsearch(ES_HOST)
    print(f"-> Connecting to {ES_HOST}, index '{args.index}'")
    print(f"-> Mode: {'APPLY (writing)' if args.apply else 'DRY RUN (no writes)'}")
    print()

    n_total = 0
    n_changed = 0
    samples = []

    for hit in scan(es, index=args.index, query={"query": {"match_all": {}}}, size=500):
        n_total += 1
        source = hit["_source"]
        raw_domain = source.get("env_domain", "")
        existing_sub = source.get("env_subgenre", "") or ""

        new_domain, new_sub, changed = normalize(raw_domain, existing_sub)
        if not changed:
            continue

        n_changed += 1
        if len(samples) < 10:
            samples.append((raw_domain, existing_sub, new_domain, new_sub))

        if args.apply:
            es.update(
                index=args.index,
                id=hit["_id"],
                body={"doc": {"env_domain": new_domain, "env_subgenre": new_sub}},
            )

    print(f"Scanned {n_total} docs, {n_changed} need normalisation.")
    if samples:
        print("\nSample transformations (first 10):")
        for raw_d, raw_s, new_d, new_s in samples:
            print(f"  env_domain={raw_d!r:30s} sub={raw_s!r:15s}  ->  env_domain={new_d!r:15s} sub={new_s!r}")

    if not args.apply and n_changed:
        print("\nRe-run with --apply to write these changes.")


if __name__ == "__main__":
    main()
