from elasticsearch import Elasticsearch
from shared_utils.config import ES_HOST, INDEX_NAME

es = Elasticsearch(ES_HOST)

def execute_statistics(params):
    print(f"-> [Stats Agent] Running aggregations with params: {params}")
    try:
        must_clauses = []
        context_str = []
        
        # --- THE PURE DYNAMIC FILTER ENGINE ---
        # No more hardcoded platforms or users. Everything flows through here.
        filters = params.get("filters", {})
        for column_name, value in filters.items():
            context_str.append(f"{column_name} = {value}")
            
            if isinstance(value, bool):
                must_clauses.append({"term": {column_name: value}})
            else:
                # If it's the author name, strip the @ just in case
                if column_name == "author_name" and isinstance(value, str):
                    value = value.replace("@", "")
                must_clauses.append({"match": {column_name: value}})

        # Run Aggregations on the FILTERED dataset
       # Run Aggregations on the FILTERED dataset
        res = es.search(
            index=INDEX_NAME, 
            size=0, 
            track_total_hits=True,
            query={"bool": {"must": must_clauses}} if must_clauses else {"match_all": {}}, 
            aggregations={
                "platform_breakdown": {"terms": {"field": "source_platform.keyword"}},
                "domain_breakdown": {"terms": {"field": "env_domain.keyword"}}, 
                "label_breakdown": {"terms": {"field": "model_label.keyword"}}, 
                "xai_override_breakdown": {"terms": {"field": "agent_final_decision.keyword"}}, 
                "top_users": {"terms": {"field": "author_name.keyword", "size": 10}},
                
                # --- NEW: PERFORMANCE METRICS ENGINE ---
                "avg_tier1_speed": {"avg": {"field": "processing_time_ms"}},
                "avg_tier2_speed": {"avg": {"field": "agent_latency_seconds"}}
            }
        )
        
        total = res['hits']['total']['value']
        aggs = res['aggregations']
        
        # Dynamic Context Header 
        header = f"--- Data Context: {' | '.join(context_str) if context_str else 'Global Database'} ---\n"
        
        stats = f"{header}Total Records matching criteria: {total}\n"
        
        # --- NEW: PRINT PERFORMANCE METRICS ---
        stats += "\n--- Performance Metrics ---\n"
        t1_avg = aggs.get('avg_tier1_speed', {}).get('value')
        t2_avg = aggs.get('avg_tier2_speed', {}).get('value')
        if t1_avg: stats += f"- Average Tier-1 Latency: {t1_avg:.2f} ms\n"
        if t2_avg: stats += f"- Average Tier-2 Latency: {t2_avg:.2f} seconds\n"
        
        stats += "\n--- Platforms ---\n"
        
        total = res['hits']['total']['value']
        aggs = res['aggregations']
        
        # Dynamic Context Header 
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