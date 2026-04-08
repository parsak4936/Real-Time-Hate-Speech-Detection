import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ollama
from elasticsearch import Elasticsearch
from shared_utils.config import ES_HOST, INDEX_NAME, ACTIVE_MODEL

es = Elasticsearch(ES_HOST)

def analyze_trends(limit=20):  # Default to 20 if no number is given
    print(f"Connecting to Warehouse at {ES_HOST}...")
    
    try:
        res = es.search(
            index=INDEX_NAME,
            size=limit,  # <--- Change the hardcoded 20 to the dynamic 'limit'
            query={
                "range": {"confidence": {"lt": 0.8}}
            }
        )
    except Exception as e:
        print(f"Database Error: {e}")
        return

    hits = res['hits']['hits']
    if not hits:
        print("Not enough suspicious data found yet. Let the streams run longer!")
        return

    # 2. Extract just the text from those 20 messages
    recent_messages = [hit['_source'].get('text', '') for hit in hits]
    compiled_text = "\n- ".join(recent_messages)

    # 3. The Prompt: Ask the Agent to find the repeated words/trends
    prompt = (
        f"You are a Threat Intelligence Analyst for a moderation team. "
        f"Here is a sample of recent chat messages flagged by our fast-filter AI:\n\n"
        f"- {compiled_text}\n\n"
        f"Analyze this data and provide a brief report:\n"
        f"1. What is the most frequently repeated topic or word in this batch?\n"
        f"2. Are there any specific internet slang terms, gaming jargon, or emerging toxic trends you notice here?\n"
        f"Keep the report highly analytical and concise."
    )

    print(f"\nFeeding 20 recent messages to Agent ({ACTIVE_MODEL}) for pattern recognition...\n")

    # 4. Get the Agent's Analysis
    try:
        response = ollama.chat(model=ACTIVE_MODEL, messages=[
            {'role': 'system', 'content': 'You are an expert in internet culture and Trust & Safety analysis.'},
            {'role': 'user', 'content': prompt}
        ])
        
        print("================ THREAT INTELLIGENCE REPORT ================")
        print(response['message']['content'])
        print("============================================================")
        
    except Exception as e:
        print(f"AI Connection Error: {e}")

if __name__ == "__main__":
    analyze_trends()