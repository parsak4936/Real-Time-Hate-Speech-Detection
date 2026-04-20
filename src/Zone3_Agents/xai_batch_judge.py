import sys
import os
import json
import time

# Tell Python where the shared_utils are
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ollama
from elasticsearch import Elasticsearch
from shared_utils.config import ES_HOST, INDEX_NAME, ACTIVE_MODEL

es = Elasticsearch(ES_HOST)

# =====================================================================
# --- MASTER CONTROL PANEL ---
# Change these variables to adjust how the script runs!
# =====================================================================

# 1. How many records should it check at once? (Put 10000 for "All")
BATCH_SIZE = 6 

# 2. What confidence level should it target? 
# (0.90 means < 90%. Change to 1.01 to check literally everything)
TARGET_CONFIDENCE_BELOW = 0.80 

# 3. SAFETY SWITCH: True = Update Database | False = Print Only (Dry Run)
UPDATE_DATABASE = True 

# =====================================================================

def run_configurable_batch_auditor():
    print(f"\n=== STARTING XAI BATCH AUDITOR ===")
    print(f"Target Index: {INDEX_NAME}")
    print(f"Batch Size: {BATCH_SIZE} | Target Conf < {TARGET_CONFIDENCE_BELOW}")
    print(f"Live DB Update Enabled: {UPDATE_DATABASE}\n")

    # Query: Unreviewed records under the target confidence
    query = {
        "query": {
            "bool": {
                "must_not": [
                    {"term": {"agent_reviewed": True}}
                ],
                "must": [
                    {"range": {"model_confidence": {"lt": TARGET_CONFIDENCE_BELOW}}} 
                ]
            }
        },
        "sort": [{"timestamp": {"order": "desc"}}],
        "size": BATCH_SIZE
    }

    try:
        res = es.search(index=INDEX_NAME, body=query)
        hits = res['hits']['hits']
        
        if not hits:
            print("No unreviewed records found matching your criteria!")
            return
        
        print(f"Found {len(hits)} records to audit. Beginning process...\n")
        
        for index, hit in enumerate(hits, 1):
            doc_id = hit['_id']
            source = hit['_source']
            
            raw_text = source.get('text', '')
            original_prediction = source.get('model_label', 'Unknown')
            confidence = source.get('model_confidence', 0)
            domain = source.get('env_domain', 'General')
            strictness = source.get('env_strictness', 'medium')
            author = source.get('author_name', 'Unknown')

            print(f"--- RECORD {index}/{len(hits)} ---")
            print(f"USER: {author} | DOMAIN: {domain} ({strictness} strictness)")
            print(f"TEXT: \"{raw_text}\"")
            print(f"DISTILBERT: {original_prediction} (Conf: {confidence:.2f})")
            print("-> Thinking...")

            # The Advanced Forensic Prompt
            judge_prompt = f"""
            [ROLE: XAI CONTEXT JUDGE - TRUST & SAFETY ADVISOR]
            Evaluate the following prediction made by a static DistilBERT model.
            
            TEXT TO ANALYZE: "{raw_text}"
            PREDICTION: {original_prediction} (Confidence: {confidence:.2%})
            DOMAIN: {domain} | STRICTNESS: {strictness}
            
            ADVANCED FORENSIC RULES:
            1. Sarcasm & In-Game Events: If the domain is Gaming, analyze if the text represents in-game actions, celebrations, or sarcastic trash talk. Override DistilBERT if it is standard gameplay rhetoric.
            2. Evasion & Dogwhistles: Hunt for leetspeak, symbol replacement, or known dogwhistles. Expose the true intent.
            3. Cultural Context: Factor in regional/cultural slang. 
            4. Instigator/Troll Detection: If DistilBERT labeled this 'Normal', but the text is highly manipulative, passive-aggressive, or clearly baiting another user into an argument, rule it a False Negative.
            
            TASK:
            1. Validate: Is DistilBERT's prediction Correct, a False Positive, or a False Negative?
            2. Explain: Detail exactly why. You MUST reference the forensic rules above if they apply.
            
            OUTPUT FORMAT: Output ONLY valid JSON: {{"decision": "...", "explanation": "..."}}
            """

            # Call the LLM
            response = ollama.chat(model=ACTIVE_MODEL, messages=[{'role': 'user', 'content': judge_prompt}])
            raw_output = response['message']['content'].strip()
            
            # Clean JSON formatting (Bypassing markdown UI bugs)
            if raw_output.startswith("`" + "``json"): raw_output = raw_output[7:-3].strip()
            elif raw_output.startswith("`" + "``"): raw_output = raw_output[3:-3].strip()
            
            try:
                result = json.loads(raw_output)
                final_decision = result.get("decision", "Unknown")
                explanation = result.get("explanation", "No explanation.")
            except Exception as e:
                final_decision = "JSON Parsing Error"
                explanation = raw_output 
            
            print(f"VERDICT: {final_decision}")
            print(f"REASON: {explanation}")
            
            # 3. DATABASE UPDATE LOGIC
            if UPDATE_DATABASE:
                es.update(index=INDEX_NAME, id=doc_id, body={
                    "doc": {
                        "agent_reviewed": True,
                        "agent_model_used": ACTIVE_MODEL,
                        "agent_final_decision": final_decision,
                        "agent_explanation": explanation
                    }
                })
                print("-> [SAVED TO DATABASE]")
            else:
                print("-> [DRY RUN - NOT SAVED]")
                
            print("")
            time.sleep(2) 

        print("=== BATCH COMPLETE ===")

    except Exception as e:
        print(f"Batch Error: {e}")

if __name__ == "__main__":
    run_configurable_batch_auditor()