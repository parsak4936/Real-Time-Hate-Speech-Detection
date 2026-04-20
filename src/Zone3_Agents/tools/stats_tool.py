from elasticsearch import Elasticsearch
from shared_utils.config import ES_HOST, INDEX_NAME

es = Elasticsearch(ES_HOST)

def execute_statistics(params):
    # UPDATED: This print statement will prove you are running the new code
    print(f"-> [Stats Agent] Running aggregations with params: {params}")
    try:
        must_clauses = []
        
        # Filter 1: Platform Bypass
        platform = params.get("platform")
        if platform and platform.lower() not in ["all", "any", "none"]:
            must_clauses.append({"match": {"source_platform": platform}})
            
        # NEW Filter 2: Specific User Targeting (With @ symbol safeguard)
# NEW Filter 2: Specific User Targeting (With @ symbol safeguard)
        target_user = params.get("target_user")
        if target_user:
            clean_user = target_user.replace("@", "")
            must_clauses.append({"match": {"author_name": clean_user}}) # <--- THE FIX
            
        # NEW Filter 3: Specific Label Targeting (e.g., 'HATE' or 'False Positive')
        target_label = params.get("target_label")
        if target_label:
            must_clauses.append({
                "bool": {
                    "should": [
                        {"term": {"model_label.keyword": target_label}},
                        {"term": {"agent_final_decision.keyword": target_label}}
                    ]
                }
            })

        # Run Aggregations on the FILTERED dataset
        res = es.search(
            index=INDEX_NAME, 
            size=0, 
            track_total_hits=True,  # <-- Keeps counting past 10,000
            query={"bool": {"must": must_clauses}} if must_clauses else {"match_all": {}}, 
            aggregations={
                "platform_breakdown": {"terms": {"field": "source_platform.keyword"}},
                "domain_breakdown": {"terms": {"field": "env_domain.keyword"}}, 
                "label_breakdown": {"terms": {"field": "model_label.keyword"}}, 
                "xai_override_breakdown": {"terms": {"field": "agent_final_decision.keyword"}}, 
                "top_users": {"terms": {"field": "author_name.keyword", "size": 10}} 
            }
        )
        
        total = res['hits']['total']['value']
        aggs = res['aggregations']
        
        # Dynamic Context Header based on filters
        context_str = []
        if target_user: context_str.append(f"User: {target_user}")
        if target_label: context_str.append(f"Filtered for Label: {target_label}")
        header = f"--- Data Context: {' | '.join(context_str) if context_str else 'Global Database'} ---\n"
        
        stats = f"{header}Total Records matching criteria: {total}\n"
        
        stats += "\n--- Platforms ---\n"
        for b in aggs.get('platform_breakdown', {}).get('buckets', []): stats += f"- {b['key']}: {b['doc_count']}\n"
        
        stats += "\n--- Domains ---\n"
        for b in aggs.get('domain_breakdown', {}).get('buckets', []): stats += f"- {b['key']}: {b['doc_count']}\n"
        
        stats += "\n--- AI Labels (Tier-1 DistilBERT) ---\n"
        for b in aggs.get('label_breakdown', {}).get('buckets', []): stats += f"- {b['key']}: {b['doc_count']}\n"

        stats += "\n--- XAI Overrides (Tier-2 Judge) ---\n"
        override_buckets = aggs.get('xai_override_breakdown', {}).get('buckets', [])
        if override_buckets:
            for b in override_buckets: stats += f"- {b['key']}: {b['doc_count']}\n"
        else:
            stats += "- 0 records matching this criteria have XAI Overrides.\n"
        
        stats += "\n--- Top Users in this Dataset ---\n"
        for b in aggs.get('top_users', {}).get('buckets', []): stats += f"- {b['key']}: {b['doc_count']} msgs\n"
        
        return stats
    except Exception as e:
        return f"Statistics failed: {e}"