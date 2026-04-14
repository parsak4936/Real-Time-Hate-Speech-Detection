import ollama
from elasticsearch import Elasticsearch
from shared_utils.config import ES_HOST, INDEX_NAME, ACTIVE_MODEL

es = Elasticsearch(ES_HOST)

def execute_xai_judge(params):
    target_user = params.get("target_user")
    print(f"-> [XAI Agent] Running SHAP-style attribution for user: {target_user}")

    # 1. RETRIEVAL: Get the flagged record from the database
    try:
        query = {"match": {"author_name": target_user}}
        res = es.search(index=INDEX_NAME, query=query, size=1)
        if not res['hits']['hits']:
            return f"Error: No records found for user {target_user}."
        
        hit = res['hits']['hits'][0]['_source']
        raw_text = hit.get('text', '')
        original_prediction = hit.get('label_text', 'Unknown')
        confidence = hit.get('confidence', 0)

        # 2. LOCAL EXPLAINABILITY (Simulated SHAP/Captum logic)
        # In a real setup, you'd run SHAP library here. 
        # For the Agent, we provide the raw text for 'LLM-as-a-Judge' to analyze.
        
        # 3. LLM-AS-A-JUDGE: Use the Tier-2 Model to evaluate the Tier-1 Model
        judge_prompt = f"""
        [ROLE: LLM-AS-A-JUDGE]
        Evaluate the following prediction made by a DistilBERT Hate Speech model.
        
        TEXT TO ANALYZE: "{raw_text}"
        MODEL PREDICTION: {original_prediction} (Confidence: {confidence:.2%})
        
        TASK:
        1. Local Explainability: Identify the high-attribution words (the words most likely causing the flag).
        2. Validation: Is the model's prediction Correct, a False Positive, or a False Negative?
        3. Reasoning: Explain why based on the ACM/Cambria survey standards for hate speech (intent vs. slur usage).
        
        Respond in a concise, structured report.
        """
        
        response = ollama.chat(model=ACTIVE_MODEL, messages=[{'role': 'user', 'content': judge_prompt}])
        return f"--- XAI JUDGE REPORT FOR {target_user} ---\n{response['message']['content']}"

    except Exception as e:
        return f"XAI Tool Failure: {str(e)}"