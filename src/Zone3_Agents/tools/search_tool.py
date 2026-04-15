from elasticsearch import Elasticsearch
from shared_utils.config import ES_HOST, INDEX_NAME

es = Elasticsearch(ES_HOST)

def execute_universal_search(params):
    print(f"-> [Search Agent] Looking for keywords: {params.get('keywords', [])}")
    must_clauses = []
    if params.get("keywords"):
        must_clauses.append({"match": {"text": " ".join(params["keywords"])}})
    else:
        must_clauses.append({"match_all": {}})

    try:
        res = es.search(index=INDEX_NAME, query={"bool": {"must": must_clauses}}, size=params.get("limit", 10))
        hits = res['hits']['hits']
        if not hits: return "No matching records found."
            
        extracted_data = []
        for hit in hits:
            source = hit['_source']
            
            # Use Universal Schema fields
            platform = source.get('source_platform', 'Unknown')
            domain = source.get('env_domain', 'General')
            author = source.get('author_name', 'Anon')
            
            # If the Tier-2 AI reviewed it, show that decision! Otherwise, show DistilBERT's label.
            if source.get('agent_reviewed', False):
                label = f"XAI OVERRIDE: {source.get('agent_final_decision')}"
            else:
                label = f"DistilBERT: {source.get('model_label', 'Unknown')}"
                
            text = source.get('text', '')
            extracted_data.append(f"[{platform} | {domain}] User: {author} | Label: [{label}] | Text: {text}")
            
        return "\n".join(extracted_data)
    except Exception as e:
        return f"Database search failed: {e}"