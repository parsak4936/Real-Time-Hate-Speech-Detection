"""
Statistics tool — runs Elasticsearch aggregations for the Leader Agent.

Filter semantics:
  - Boolean values use a `term` query (exact match).
  - String values use a `term` query against the `.keyword` subfield so
    that e.g. {"agent_final_decision": "False Positive"} matches the
    exact phrase rather than tokenising to "false" OR "positive".
"""

from elasticsearch import Elasticsearch

from shared_utils.config import ES_HOST, INDEX_NAME

es = Elasticsearch(ES_HOST)


def _filter_clause(column_name, value):
    """Build a single ES bool-must clause for one (field, value) filter."""
    if isinstance(value, bool):
        return {"term": {column_name: value}}
    if isinstance(value, (int, float)):
        return {"term": {column_name: value}}
    if isinstance(value, str):
        if column_name == "author_name":
            value = value.replace("@", "")
        return {"term": {f"{column_name}.keyword": value}}
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
                "platform_breakdown": {"terms": {"field": "source_platform.keyword"}},
                "domain_breakdown": {"terms": {"field": "env_domain.keyword"}},
                "subgenre_breakdown": {"terms": {"field": "env_subgenre.keyword"}},
                "label_breakdown": {"terms": {"field": "model_label.keyword"}},
                "xai_override_breakdown": {"terms": {"field": "agent_final_decision.keyword"}},
                "top_users": {"terms": {"field": "author_name.keyword", "size": 10}},
                "avg_tier1_speed": {"avg": {"field": "processing_time_ms"}},
                "avg_tier2_speed": {"avg": {"field": "agent_latency_seconds"}},
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
