from elasticsearch import Elasticsearch
from shared_utils.config import ES_HOST, INDEX_NAME

es = Elasticsearch(ES_HOST)

def execute_statistics(params):
    print(f"-> [Stats Agent] Running aggregations...")
    try:
        must_clauses = []
        if params.get("platform"):
            must_clauses.append({"match": {"source_platform": params.get("platform")}})
            
        res = es.search(
            index=INDEX_NAME, size=0, 
            query={"bool": {"must": must_clauses}} if must_clauses else {"match_all": {}}, 
            aggregations={
                "platform_breakdown": {"terms": {"field": "source_platform.keyword"}},
                "domain_breakdown": {"terms": {"field": "env_domain.keyword"}}, 
                "label_breakdown": {"terms": {"field": f"{params.get('label_column', 'model_label')}.keyword"}}, 
                "top_users": {"terms": {"field": f"{params.get('user_column', 'author_name')}.keyword", "size": 10}} 
            }
        )
        
        total = res['hits']['total']['value']
        aggs = res['aggregations']
        
        stats = f"Total Records: {total}\n"
        
        stats += "\n--- Platforms ---\n"
        for b in aggs.get('platform_breakdown', {}).get('buckets', []): stats += f"- {b['key']}: {b['doc_count']}\n"
        
        stats += "\n--- Domains ---\n"
        for b in aggs.get('domain_breakdown', {}).get('buckets', []): stats += f"- {b['key']}: {b['doc_count']}\n"
        
        stats += "\n--- AI Labels ---\n"
        for b in aggs.get('label_breakdown', {}).get('buckets', []): stats += f"- Label {b['key']}: {b['doc_count']}\n"
        
        stats += "\n--- Top Users ---\n"
        for b in aggs.get('top_users', {}).get('buckets', []): stats += f"- {b['key']}: {b['doc_count']} msgs\n"
        
        return stats
    except Exception as e:
        return f"Statistics failed: {e}"