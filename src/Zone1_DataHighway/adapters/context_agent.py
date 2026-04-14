import json
import ollama
import sys
import os

# --- PATH RESOLUTION ---
# This dynamically finds your 'src' folder (two levels up from this file)
# so Python knows exactly where the 'shared_utils' folder is located.
current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.abspath(os.path.join(current_dir, "../../"))
if src_dir not in sys.path:
    sys.path.append(src_dir)

# --- IMPORT CONFIG ---
# Now it pulls the active model directly from your global config file!
from shared_utils.config import ACTIVE_MODEL

def resolve_environment(source_platform, raw_meta):
    """
    The Headless Micro-Agent with Human-in-the-Loop (HITL) Fallback.
    """
    print(f"-> [Context Agent] Booting... Analyzing {source_platform} metadata.")
    print(f"-> [Context Agent] Using LLM: {ACTIVE_MODEL}") # Added a print to verify the model!
    
    # ... [The rest of your function stays exactly the same!] ...
    # 1. Format the metadata so the LLM can read it easily
    meta_string = "\n".join([f"{k.capitalize()}: {v}" for k, v in raw_meta.items()])
    
    # 2. The Strict System Prompt
    prompt = f"""
    You are an automated metadata classifier for a Trust & Safety data ingestion pipeline.
    Analyze the following metadata scraped from a {source_platform} stream:
    
    --- METADATA ---
    {meta_string}
    ----------------
    
    TASK:
    1. Determine the 'env_domain' (e.g., Gaming, Politics, Medical, Music, Sports, News, General). 
       Be specific. If it's Dota 2, the domain is 'Gaming/Esports'.
    2. Determine the moderation 'env_strictness' (low, medium, high).
       - 'low' = Gaming, esports, casual streams (slang and aggressive gaming terms are expected).
       - 'high' = Politics, news, medical (strict professional conduct expected).
       - 'medium' = General chatting, music.
    
    OUTPUT FORMAT:
    You must output ONLY a valid JSON object. No explanations. No markdown formatting.
    Example: {{"env_domain": "Gaming/Esports", "env_strictness": "low"}}
    """
    
    # 3. The LLM Call
    try:
        response = ollama.chat(model=ACTIVE_MODEL, messages=[{'role': 'user', 'content': prompt}])
        raw_output = response['message']['content'].strip()
        
        # 4. Clean and Parse the JSON output
        # Sometimes Ollama wraps JSON in markdown block quotes (```json ... ```)
        if raw_output.startswith("```json"):
            raw_output = raw_output[7:-3].strip()
        elif raw_output.startswith("```"):
            raw_output = raw_output[3:-3].strip()
            
        context_data = json.loads(raw_output)
        
        # 5. Extract safely with fallbacks
        domain = context_data.get("env_domain", "General")
        strictness = context_data.get("env_strictness", "medium")
        
        return domain, strictness

    except Exception as e:
        print(f"-> [Context Agent Error] Failed to parse AI response. Using fallback. Error: {e}")
        # If the LLM hallucinates or crashes, the pipeline survives!
        return "General", "medium"