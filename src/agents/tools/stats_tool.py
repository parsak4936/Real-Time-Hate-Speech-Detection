"""
Statistics tool — runs Elasticsearch aggregations for the Leader Agent.

Filter / aggregation semantics (post-index-template):
  - Pure keyword fields (env_domain, model_label, source_platform, etc.)
    use the bare field name. NO `.keyword` suffix.
  - Text + keyword multi-fields (author_name, env_domain_raw, thread_title,
    text) use `.keyword` for exact-match aggregation / filter.
  - Booleans use `term`.
"""

from elasticsearch import Elasticsearch

from shared_utils.config import ES_HOST, INDEX_NAME

es = Elasticsearch(ES_HOST)

_TEXT_KEYWORD_FIELDS = {"text", "author_name", "env_domain_raw", "thread_title"}


def _filter_clause(column_name, value):
    """Build a single ES bool-must clause for one (field, value) filter."""
    if isinstance(value, bool):
        return {"term": {column_name: value}}
    if isinstance(value, (int, float)):
        return {"term": {column_name: value}}
    if isinstance(value, str):
        if column_name == "author_name":
            value = value.replace("@", "")
        if column_name in _TEXT_KEYWORD_FIELDS:
            return {"term": {f"{column_name}.keyword": value}}
        return {"term": {column_name: value}}
    return {"match": {column_name: value}}


def execute_statistics(params):
    print(f"-> [Stats Agent] Running aggregations with params: {params}")
    try:
        filters = params.get("filters", {}) or {}
        must_clauses = []
        context_str = []

        for column_name, value in filters.items():
            context_str.append(f"{column_name} = {value}")
            must_clauses.append(_filter_clause(column_name, value))

        res = es.search(
            index=INDEX_NAME,
            size=0,
            track_total_hits=True,
            query={"bool": {"must": must_clauses}} if must_clauses else {"match_all": {}},
            aggregations={
                "platform_breakdown":    {"terms": {"field": "source_platform"}},
                "domain_breakdown":      {"terms": {"field": "env_domain"}},
                "subgenre_breakdown":    {"terms": {"field": "env_subgenre"}},
                "label_breakdown":       {"terms": {"field": "model_label"}},
                "xai_override_breakdown":{"terms": {"field": "agent_final_decision"}},
                "top_users":             {"terms": {"field": "author_name.keyword", "size": 10}},
                "avg_tier1_speed":       {"avg":   {"field": "processing_time_ms"}},
                "avg_tier2_speed":       {"avg":   {"field": "agent_latency_seconds"}},
            },
        )

        total = res["hits"]["total"]["value"]
        aggs = res["aggregations"]

        header = f"--- Data Context: {' | '.join(context_str) if context_str else 'Global Database'} ---\n"
        stats = f"{header}Total Records matching criteria: {total}\n"

        stats += "\n--- Performance Metrics ---\n"
        t1_avg = aggs.get("avg_tier1_speed", {}).get("value")
        t2_avg = aggs.get("avg_tier2_speed", {}).get("value")
        if t1_avg is not None:
            stats += f"- Average Tier-1 Latency: {t1_avg:.2f} ms\n"
        if t2_avg is not None:
            stats += f"- Average Tier-2 Latency: {t2_avg:.2f} seconds\n"

        stats += "\n--- Platforms ---\n"
        for b in aggs.get("platform_breakdown", {}).get("buckets", []):
            stats += f"- {b['key']}: {b['doc_count']}\n"

        stats += "\n--- Domains ---\n"
        for b in aggs.get("domain_breakdown", {}).get("buckets", []):
            stats += f"- {b['key']}: {b['doc_count']}\n"

        sub_buckets = aggs.get("subgenre_breakdown", {}).get("buckets", [])
        if sub_buckets:
            stats += "\n--- Subgenres ---\n"
            for b in sub_buckets:
                if b["key"]:
                    stats += f"- {b['key']}: {b['doc_count']}\n"

        stats += "\n--- AI Labels (Tier-1 DistilBERT) ---\n"
        for b in aggs.get("label_breakdown", {}).get("buckets", []):
            stats += f"- {b['key']}: {b['doc_count']}\n"

        stats += "\n--- XAI Overrides (Tier-2 Judge) ---\n"
        override_buckets = aggs.get("xai_override_breakdown", {}).get("buckets", [])
        if override_buckets:
            for b in override_buckets:
                stats += f"- {b['key']}: {b['doc_count']}\n"
        else:
            stats += "- 0 records matching this criteria have XAI Overrides.\n"

        stats += "\n--- Top Users in this Dataset ---\n"
        for b in aggs.get("top_users", {}).get("buckets", []):
            stats += f"- {b['key']}: {b['doc_count']} msgs\n"

        return stats
    except Exception as e:
        return f"Statistics failed: {e}"
