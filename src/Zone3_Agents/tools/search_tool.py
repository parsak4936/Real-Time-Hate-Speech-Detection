from elasticsearch import Elasticsearch
from shared_utils.config import ES_HOST, INDEX_NAME

es = Elasticsearch(ES_HOST)

def execute_universal_search(params):
    print(f"-> [Search Agent] Searching with params: {params}")
    must_clauses = []
    # --- THE NEW DYNAMIC FILTER ENGINE ---
    filters = params.get("filters", {})
    for column_name, value in filters.items():
        if isinstance(value, bool):
            must_clauses.append({"term": {column_name: value}})
        else:
            must_clauses.append({"match": {column_name: value}})
    # ---------------------------------------
    # 1. Search by chat keywords (Original Logic)
    if params.get("keywords"):
        must_clauses.append({"match": {"text": " ".join(params["keywords"])}})
        
    # 2. NEW: Search by specific Author Name (Case-insensitive & @ stripped)
 # 2. Search by specific Author Name (Typos Allowed)
    if params.get("author"):
        clean_author = params["author"].replace("@", "")
        must_clauses.append({
            "match": {
                "author_name": {
                    "query": clean_author,
                    "fuzziness": "AUTO" # <-- Automatically handles 1-2 character typos
                }
            }
        })
        
    # 3. Search by specific AI Label
    if params.get("label"):
        must_clauses.append({
            "bool": {
                "should": [
                    {"match": {"model_label.keyword": params["label"]}},
                    {"match": {"agent_final_decision.keyword": params["label"]}}
                ]
            }
        })

    # 4. Filter for specifically reviewed records only
    if params.get("reviewed_only") == True:
        must_clauses.append({"term": {"agent_reviewed": True}})

    # If no filters were provided, just grab the most recent stuff
    if not must_clauses:
        must_clauses.append({"match_all": {}})

    try:
        # Sort by newest first to get the most relevant data
        res = es.search(
            index=INDEX_NAME, 
            query={"bool": {"must": must_clauses}}, 
            sort=[{"timestamp": {"order": "desc"}}],
            size=params.get("limit", 10)
        )
        hits = res['hits']['hits']
        if not hits: return "No matching records found."
            
        extracted_data = []
        for hit in hits:
            source = hit['_source']
            
            platform = source.get('source_platform', 'Unknown')
            domain = source.get('env_domain', 'General')
            author = source.get('author_name', 'Anon')
            
            # Show Tier-2 AI decision! Otherwise, show DistilBERT's label.
            if source.get('agent_reviewed', False):
                label = f"XAI OVERRIDE: {source.get('agent_final_decision')}"
            else:
                label = f"DistilBERT: {source.get('model_label', 'Unknown')}"
                
            text = source.get('text', '')
            extracted_data.append(f"[{platform} | {domain}] User: {author} | Label: [{label}] | Text: {text}")
            
        return "\n".join(extracted_data)
    except Exception as e:
        return f"Database search failed: {e}"