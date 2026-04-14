import json
import ollama
from elasticsearch import Elasticsearch
from shared_utils.config import ES_HOST, INDEX_NAME, ACTIVE_MODEL

es = Elasticsearch(ES_HOST)

def execute_xai_judge(params):
    target_user = params.get("target_user")
    print(f"-> [XAI Agent] Running SHAP-style attribution for user: {target_user}")

  # 1. RETRIEVAL: Get the flagged record from the database
    try:
        # NEW: Sort to get their most recent message
        query = {
            "query": {"match": {"author_name": target_user}},
            "sort": [{"timestamp": {"order": "desc"}}],
            "size": 1
        }
        res = es.search(index=INDEX_NAME, body=query)
        
        if not res['hits']['hits']:
            return f"Error: No records found for user {target_user}."
        
        # NEW: Grab doc_id so we can update it later
        hit = res['hits']['hits'][0]
        doc_id = hit['_id']
        source = hit['_source']
        
        # --- NEW UNIVERSAL SCHEMA FIELDS ---
        raw_text = source.get('text', '')
        original_prediction = source.get('model_label', 'Unknown')
        confidence = source.get('model_confidence', 0)
        domain = source.get('env_domain', 'General')
        strictness = source.get('env_strictness', 'medium')

        # 2. LOCAL EXPLAINABILITY (Simulated SHAP/Captum logic)
        # In a real setup, you'd run SHAP library here. 
        # For the Agent, we provide the raw text for 'LLM-as-a-Judge' to analyze.
        
       # 3. LLM-AS-A-JUDGE: Context-Aware Evaluation
        judge_prompt = f"""
        [ROLE: XAI CONTEXT JUDGE]
        Evaluate the following prediction made by DistilBERT.
        
        TEXT TO ANALYZE: "{raw_text}"
        PREDICTION: {original_prediction} (Confidence: {confidence:.2%})
        DOMAIN: {domain} | STRICTNESS: {strictness}
        
        RULES:
        - If strictness is 'low' (Gaming), aggressive slang and team names (like 'Nigma') are permitted.
        - If strictness is 'high' (Politics), zero tolerance.
        
        TASK:
        1. Validate: Correct, False Positive, or False Negative?
        2. Explain: Why, based on context?
        
        OUTPUT FORMAT: Output ONLY valid JSON: {{"decision": "...", "explanation": "..."}}
        """
        
        response = ollama.chat(model=ACTIVE_MODEL, messages=[{'role': 'user', 'content': judge_prompt}])
        raw_output = response['message']['content'].strip()

# 4. Clean markdown and parse JSON
        if raw_output.startswith("```json"): 
            raw_output = raw_output[7:-3].strip()
        elif raw_output.startswith("```"): 
            raw_output = raw_output[3:-3].strip()
        
        try:
            result = json.loads(raw_output)
            final_decision = result.get("decision", "Unknown")
            explanation = result.get("explanation", "No explanation.")
        except Exception as e:
            final_decision = "Parsing Error"
            explanation = raw_output 

        # 5. DATABASE OVERWRITE (Tier 2 Overlay)
        es.update(index=INDEX_NAME, id=doc_id, body={
            "doc": {
                "agent_reviewed": True,
                "agent_model_used": ACTIVE_MODEL,
                "agent_final_decision": final_decision,
                "agent_explanation": explanation
            }
        })

        return f"--- XAI REPORT FOR '{target_user}' ---\nVerdict: {final_decision}\nReason: {explanation}\n(Database Updated Successfully)"

    except Exception as e:
        return f"XAI Tool Failure: {str(e)}"