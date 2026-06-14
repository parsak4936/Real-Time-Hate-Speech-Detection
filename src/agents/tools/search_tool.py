"""
Universal Search tool — full-text + filtered retrieval from Elasticsearch
for the Leader Agent.

Filter semantics (post-index-template):
  - Pure keyword fields (env_domain, model_label, source_platform, etc.)
    use `term` directly. NO `.keyword` suffix — those subfields don't
    exist with the explicit mapping.
  - Text + keyword multi-fields (text, author_name, env_domain_raw,
    thread_title) use `.keyword` for exact match, base field for tokenised.
  - Booleans use `term`.
"""

from elasticsearch import Elasticsearch

from shared_utils.config import ES_HOST, INDEX_NAME

es = Elasticsearch(ES_HOST)

# Fields mapped as text+keyword multi-field — exact-match on the .keyword subfield.
_TEXT_KEYWORD_FIELDS = {"text", "author_name", "env_domain_raw", "thread_title"}


def _filter_clause(column_name, value):
    if isinstance(value, bool):
        return {"term": {column_name: value}}
    if isinstance(value, (int, float)):
        return {"term": {column_name: value}}
    if isinstance(value, str):
        if column_name in _TEXT_KEYWORD_FIELDS:
            return {"term": {f"{column_name}.keyword": value}}
        return {"term": {column_name: value}}
    return {"match": {column_name: value}}


def execute_universal_search(params):
    print(f"-> [Search Agent] Searching with params: {params}")
    must_clauses = []

    filters = params.get("filters", {}) or {}
    for column_name, value in filters.items():
        must_clauses.append(_filter_clause(column_name, value))

    if params.get("keywords"):
        must_clauses.append({"match": {"text": " ".join(params["keywords"])}})

    if params.get("author"):
        clean_author = params["author"].replace("@", "")
        must_clauses.append({
            "match": {
                "author_name": {"query": clean_author, "fuzziness": "AUTO"}
            }
        })

    if params.get("label"):
        must_clauses.append({
            "bool": {
                "should": [
                    {"term": {"model_label": params["label"]}},
                    {"term": {"agent_final_decision": params["label"]}},
                ]
            }
        })

    if params.get("reviewed_only") is True:
        must_clauses.append({"term": {"agent_reviewed": True}})

    if not must_clauses:
        must_clauses.append({"match_all": {}})

    try:
        res = es.search(
            index=INDEX_NAME,
            query={"bool": {"must": must_clauses}},
            sort=[{"timestamp": {"order": "desc"}}],
            size=params.get("limit", 10),
        )
        hits = res["hits"]["hits"]
        if not hits:
            return "No matching records found."

        extracted_data = []
        for hit in hits:
            source = hit["_source"]
            platform = source.get("source_platform", "Unknown")
            domain = source.get("env_domain", "General")
            subgenre = source.get("env_subgenre", "")
            domain_tag = f"{domain}/{subgenre}" if subgenre else domain
            author = source.get("author_name", "Anon")

            if source.get("agent_reviewed", False):
                label = f"XAI OVERRIDE: {source.get('agent_final_decision')}"
            else:
                label = f"DistilBERT: {source.get('model_label', 'Unknown')}"

            text = source.get("text", "")
            extracted_data.append(
                f"[{platform} | {domain_tag}] User: {author} | Label: [{label}] | Text: {text}"
            )

        return "\n".join(extracted_data)
    except Exception as e:
        return f"Database search failed: {e}"
