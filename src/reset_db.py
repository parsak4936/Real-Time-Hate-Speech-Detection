"""
Wipe the configured Elasticsearch index. Destructive; requires --yes.

Usage:
    python src/reset_db.py --yes
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from elasticsearch import Elasticsearch

from shared_utils.config import ES_HOST, INDEX_NAME


def main():
    if "--yes" not in sys.argv:
        print(f"Refusing to delete index '{INDEX_NAME}' without --yes.")
        print(f"Run: python {os.path.basename(__file__)} --yes")
        sys.exit(1)

    es = Elasticsearch(ES_HOST)
    print(f"Attempting to delete index: {INDEX_NAME}...")
    try:
        es.indices.delete(index=INDEX_NAME, ignore_unavailable=True)
        print("-> Success! Database wiped clean.")
    except Exception as e:
        print(f"-> Error: {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
