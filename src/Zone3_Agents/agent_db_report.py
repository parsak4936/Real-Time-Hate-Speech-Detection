import sys
import os

# Ensure Python can find your config file
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ollama
from elasticsearch import Elasticsearch
from shared_utils.config import ES_HOST, INDEX_NAME, ACTIVE_MODEL

es = Elasticsearch(ES_HOST)

def run_agentic_report():
    print(f"Connecting to Elasticsearch at {ES_HOST}...")
    
    # 1. The Agent's "Eyes": Extract the exact metrics
    try:
        res = es.search(
            index=INDEX_NAME,
            size=0, 
            aggregations={
                "source_breakdown": {
                    "terms": {"field": "source.keyword"}
                }
            }
        )
    except Exception as e:
        print(f"Database Error: {e}")
        return

    total_docs = res['hits']['total']['value']
    buckets = res['aggregations']['source_breakdown']['buckets']
    
    # Format the raw metrics into a readable string
    raw_stats = f"Total Data: {total_docs}. Breakdown: "
    for b in buckets:
        raw_stats += f"{b['key']}: {b['doc_count']} records. "

    # 2. The Agent's "Brain": Inject metrics and request reasoning
    prompt = (
        f"You are the Lead AI Data Analyst for my Hate Speech Moderation Pipeline. "
        f"I just queried our Elasticsearch warehouse and retrieved these live metrics: {raw_stats}\n\n"
        f"You MUST format your response exactly using the template below. Do not skip any sections:\n\n"
        f"**1. DATABASE TOTAL:** [Insert total documents here]\n"
        f"**2. PLATFORM BREAKDOWN:**\n"
        f"- YouTube: [Insert exact number]\n"
        f"- Twitter: [Insert exact number]\n"
        f"**3. ARCHITECTURAL ANALYSIS:** [Write 2 sentences explaining what this specific data balance means for our AI training accuracy.]"
    )

    print(f"Agent ({ACTIVE_MODEL}) is analyzing the database distribution...\n")

    # 3. Execute the Agent
    try:
        response = ollama.chat(model=ACTIVE_MODEL, messages=[
            {'role': 'system', 'content': 'You are a precise, logical AI assistant.'},
            {'role': 'user', 'content': prompt}
        ])
        
        print("================ TIER-2 AGENT REPORT ================")
        print(response['message']['content'])
        print("=====================================================")
        
    except Exception as e:
        print(f"AI Connection Error: {e}")

if __name__ == "__main__":
    run_agentic_report()