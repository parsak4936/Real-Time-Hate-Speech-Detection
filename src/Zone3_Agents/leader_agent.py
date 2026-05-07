import sys
import os
import json
# --- CRITICAL FIX: Tell Python where the folders are FIRST ---
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ollama
from elasticsearch import Elasticsearch
from shared_utils.config import ES_HOST, INDEX_NAME, ACTIVE_MODEL

# === NEW: IMPORT YOUR SUB-AGENTS ===
from Zone3_Agents.tools.search_tool import execute_universal_search
from Zone3_Agents.tools.stats_tool import execute_statistics
from Zone3_Agents.tools.weather_tool import execute_weather_time 
from Zone3_Agents.tools.xai_judge_tool import execute_xai_judge

TOOL_REGISTRY = {
    "UNIVERSAL_SEARCH": execute_universal_search,
    "GET_STATISTICS": execute_statistics,
    "GET_WEATHER": execute_weather_time,
    "XAI_JUDGE": execute_xai_judge  
}
print(f"Booting Modular Orchestrator on {ACTIVE_MODEL}...")
es = Elasticsearch(ES_HOST)

def get_database_schema():
    try:
        res = es.search(index=INDEX_NAME, size=1)
        if res['hits']['hits']:
            # Grab all the keys from the first row (e.g., 'author_name', 'label_text')
            return list(res['hits']['hits'][0]['_source'].keys())
        return []
    except Exception:
        return ["error_reading_schema"]

DB_SCHEMA_KEYS = get_database_schema()
print(f"-> AI Schema Awareness Loaded: {DB_SCHEMA_KEYS}")

# ==========================================
def leader_router(user_input):
    print(f"\n[Phase 1: Analyzing Intent...]")

    intent_prompt = f"""
    You are the Orchestrator AI for a Trust & Safety Data Pipeline. 
    Analyze the user's request and choose the correct tool.
    
    CRITICAL DATABASE SCHEMA: You have access to these exact columns: {DB_SCHEMA_KEYS}
    
    YOUR VOCABULARY & DATABASE MAPPING:
    * "First AI", "Static", "DistilBERT", "hate speech", or "flagged" = map to `model_label` (Values are usually "HATE", "OFFENSIVE", or "Normal").
    * "LLM", "Tier-2", "Reviewed", "Overturned", "False Positive" = map to `agent_final_decision`.
    * "judged by agent", "reviewed by agent", "checked by AI", "agent_review" = map to `agent_reviewed` (Values MUST be boolean: true or false).
    * "time", "speed", "latency" = map to `processing_time_ms` or `agent_latency_seconds`.
    
    CRITICAL SEARCH RULES:
    - ONLY use "keywords" if the user is looking for a specific chat word. 
    - DO NOT put label names (like "hate speech") in the "keywords" list! 
    
    You must output a JSON object using ONE of these formats:
    
    1. For reading messages, searching history, or finding examples:
       {{"tool": "UNIVERSAL_SEARCH", "filters": {{"agent_final_decision": "False Positive"}}, "limit": 5}}
       
    2. For counting data, statistics, breakdowns, or finding totals based on ANY condition:
       {{"tool": "GET_STATISTICS", "filters": {{"exact_schema_key": value}}}} 
       - You MUST map the user's request directly to the CRITICAL DATABASE SCHEMA keys.
       - Example A: "how many entries are reviewed" -> {{"tool": "GET_STATISTICS", "filters": {{"agent_reviewed": true}}}}
       - Example B: "how many from youtube" -> {{"tool": "GET_STATISTICS", "filters": {{"source_platform": "youtube"}}}}
       - Example C: "how many false positives" -> {{"tool": "GET_STATISTICS", "filters": {{"agent_final_decision": "False Positive"}}}}
       - For global overall stats (no filters), leave it empty: {{"tool": "GET_STATISTICS", "filters": {{}}}}

    3. For investigating a SPECIFIC user or running an audit:
       {{"tool": "XAI_JUDGE", "target_user": "exact_username_here"}}

    4. For weather/time/location:
       {{"tool": "GET_WEATHER"}} 
       
    5. For general conversation:
       {{"tool": "DIRECT_MESSAGE", "message": "..."}}

    User Request: "{user_input}"
    
    Respond ONLY with raw JSON. Do not include markdown formatting, backticks, or extra text.
    """

    try:
        # PHASE 1: Get the search parameters from the LLM
        response = ollama.chat(model=ACTIVE_MODEL, messages=[
            {'role': 'user', 'content': intent_prompt}
        ])
        
        # Clean the output to ensure it's raw JSON
        raw_output = response['message']['content'].strip()
        if raw_output.startswith("`" + "``json"): 
            raw_output = raw_output[7:-3].strip()
        elif raw_output.startswith("`" + "``"): 
            raw_output = raw_output[3:-3].strip()

        params = json.loads(raw_output)

        print(f"-> AI Brain Output: {params}\n")
        
        tool = params.get("tool")
        
        # PHASE 2: Execute the chosen tool
        if tool == "DIRECT_MESSAGE":
            print(f"Leader: {params.get('message', 'Hello.')}")
            return
            
        elif tool in TOOL_REGISTRY:
            selected_function = TOOL_REGISTRY[tool]
            raw_database_results = selected_function(params)
            
        else:
            print(f"Error: The AI hallucinated a tool. '{tool}' is not in the registry.")
            return
            
        print(f"\n[Phase 3: Synthesizing Final Report...]")
        
        # PHASE 3: Synthesize the Answer (The Brain)
        synthesis_prompt = f"""
        You are a Trust & Safety Analyst. The user asked: "{user_input}"
        
        I ran a database search based on their request. Here is the exact raw data pulled from our servers:
        ---
        {raw_database_results}
        ---
        
        Read the raw data above and answer the user's original question. 
        CRITICAL RULE: Our database uses "Fuzzy Matching" to automatically correct human typos. If the user asks about a specific username, and the raw data returns a slightly differently spelled username, you MUST assume the user made a typo and treat the returned data as the correct match. Do not say the user is missing!
        
        Be concise, analytical, and ground your entire response ONLY in the provided data.
        """
        
        final_response = ollama.chat(model=ACTIVE_MODEL, messages=[
            {'role': 'user', 'content': synthesis_prompt}
        ])
        
        print("\n================ TIER-2 AGENT REPORT ================")
        print(final_response['message']['content'])
        print("=====================================================")

    except json.JSONDecodeError:
        print(f"Routing Error: The AI failed to generate valid JSON. Raw output was: {raw_output}")
    except Exception as e:
        print(f"System Error: {e}")

if __name__ == "__main__":
    print("================ TIER-2 COMMAND CENTER ================")
    print("Welcome to the Universal RAG Terminal.")
    
    while True:
        user_query = input("\nYour Command (or 'exit'): ")
        
        if user_query.lower() in ['exit', 'quit']:
            break
            
        leader_router(user_query)