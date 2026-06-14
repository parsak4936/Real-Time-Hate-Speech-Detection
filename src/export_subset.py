"""
Export a benchmark CSV from the live Elasticsearch index.

The CSV is the immutable record of one evaluation moment. It must carry
enough metadata for downstream replay scripts (e.g. replay_with_memory.py) to
map each row back to its ES document by exact ID, AND for the evaluation
notebook to compare verdicts across pipeline stages.
"""

import os
import sys

import pandas as pd
from elasticsearch import Elasticsearch

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared_utils.config import ES_HOST, INDEX_NAME

es = Elasticsearch(ES_HOST)

# Order matters — this is the column order that lands in the CSV.
REQUIRED_FIELDS = [
    # Identity / replay keys (added Stage 2 — let replay_with_memory match by exact ID)
    "message_id",
    "timestamp",

    # Context
    "env_domain",
    "env_domain_raw",
    "env_domain_match",
    "env_subgenre",
    "env_strictness",
    "env_strictness_reasoning",

    # Content
    "text",
    "author_id",
    "author_name",

    # Tier-1 verdict
    "model_label",
    "model_confidence",
    "processing_time_ms",

    # Tier-2 verdict — current live pipeline result
    "agent_final_decision",
    "agent_explanation",
    "agent_latency_seconds",

    # Tier-2 verdict — memory-augmented retroactive verdict from replay_with_memory.py
    "agent_final_decision_with_memory",
    "agent_explanation_with_memory",
    "agent_memory_used",
    "agent_memory_user_msgs",
    "agent_memory_thread_msgs",
    "agent_memory_user_profile",

    # Manual ground truth (filled in afterwards by the analyst)
    "human_ground_truth",
]


def export_comprehensive_benchmark(output_file: str = "thesis_final_benchmark.csv"):
    print("-> Connecting to Elasticsearch...")

    query = {
        "query": {
            "bool": {
                "must": [
                    {"term": {"agent_reviewed": True}},
                    {"exists": {"field": "agent_latency_seconds"}},
                ]
            }
        },
        "size": 1000,
        "sort": [{"timestamp": {"order": "desc"}}],
    }

    try:
        res = es.search(index=INDEX_NAME, body=query)
        hits = res["hits"]["hits"]

        if not hits:
            print("No reviewed records with latency found!")
            return

        print(f"-> Successfully pulled {len(hits)} records. Formatting...")

        data_list = []
        for hit in hits:
            source = hit["_source"]
            row = {field: source.get(field, "") for field in REQUIRED_FIELDS}
            # human_ground_truth is filled in manually afterwards — never
            # carry whatever stale value happens to be in ES.
            row["human_ground_truth"] = ""
            data_list.append(row)

        df = pd.DataFrame(data_list)
        df = df[df["agent_latency_seconds"].notna() & (df["agent_latency_seconds"].astype(float) > 0)]
        df = df[REQUIRED_FIELDS]

        df.to_csv(output_file, index=False, encoding="utf-8")

        print(f"\n[OK] Exported filtered dataset to {output_file}")
        print(f"-> {len(df)} rows, {len(REQUIRED_FIELDS)} columns.")
        print("-> message_id + timestamp included so replay_with_memory can match by exact ID.")

    except Exception as e:
        print(f"Extraction failed: {e}")


if __name__ == "__main__":
    output_file = sys.argv[1] if len(sys.argv) > 1 else "thesis_final_benchmark.csv"
    export_comprehensive_benchmark(output_file)
