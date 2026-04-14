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
            extracted_data.append(f"[{source.get('source', 'Unknown')}] User: {source.get('author_name', 'Anon')} | Label: {source.get('label_text', 'Unknown')} | Text: {source.get('text', '')}")
        return "\n".join(extracted_data)
    except Exception as e:
        return f"Database search failed: {e}"