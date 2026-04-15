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

    # 1. The OpenAPI-Style Schema Prompt
    # 1. The Schema-Aware Schema Prompt
    # 1. The Schema-Aware Schema Prompt
    intent_prompt = f"""
    You are the Orchestrator AI for a Trust & Safety Data Pipeline. 
    Analyze the user's request and choose the correct tool.
    
    CRITICAL DATABASE SCHEMA: You have access to these exact columns: {DB_SCHEMA_KEYS}
    RULE: Always prefer human-readable string columns (e.g., use 'author_name' instead of 'author_id').
    
    You must output a JSON object using ONE of these formats:
    
    1. For reading messages or keyword searches:
       {{"tool": "UNIVERSAL_SEARCH", "keywords": ["word1"], "limit": 20}}
       
    2. For counting data, finding TOP USERS, or checking labels. 
       YOU MUST select the correct column names from the SCHEMA list above for the user and the label!
       {{"tool": "GET_STATISTICS", "platform": "youtube", "user_column": "exact_schema_key", "label_column": "exact_schema_key"}} 
       
    3. For greetings, asking about your capabilities, or unrelated questions:
       {{"tool": "DIRECT_MESSAGE", "message": "[Write your natural, polite response here]"}}
    4. For checking the current date, time, weather, OR finding the user's current location/city:
       {{"tool": "GET_WEATHER", "location": "Optional City Name"}} 
       (Note: Leave "location" blank if they ask "where am I", "my weather", or "what city am I in").
    5. For explaining WHY a specific user was flagged or judging a model's decision:
       {{"tool": "XAI_JUDGE", "target_user": "username"}}

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
        if raw_output.startswith("```json"): 
            raw_output = raw_output[7:-3].strip()
        elif raw_output.startswith("```"): 
            raw_output = raw_output[3:-3].strip()

        params = json.loads(raw_output)

        print(f"-> AI Brain Output: {params}\n")
        
        tool = params.get("tool")
        
        # PHASE 2: Execute the chosen tool
        if tool == "DIRECT_MESSAGE":
            print(f"Leader: {params.get('message', 'Hello.')}")
            return
            
        elif tool in TOOL_REGISTRY:
            # The Magic: Look up the function in the dictionary and run it!
            selected_function = TOOL_REGISTRY[tool]
            # THE FIX: Rename this variable to match what Phase 3 expects!
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
        



        