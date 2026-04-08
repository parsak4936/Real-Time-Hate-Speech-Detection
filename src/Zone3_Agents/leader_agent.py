import sys
import os
import json

# Ensure Python can find your config file
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ollama
from shared_utils.config import ACTIVE_MODEL

# Import the specific tools the Leader can use
from Zone3_Agents.agent_db_report import run_agentic_report
from Zone3_Agents.trend_analyzer import analyze_trends

def leader_router(user_input):
    print(f"\n[Leader Agent is analyzing intent...]")

    # 1. The Dynamic Tool-Calling Prompt
    prompt = f"""
    You are the intelligent Command Center AI for a Moderation Pipeline.
    Analyze the user's request and determine the actions to take.
    
    You must output a JSON array containing objects with the following keys:
    
    1. If they ask for database counts, sizes, or amounts:
       {{"tool": "COUNT"}}
       
    2. If they ask for trends, toxic words, or analysis (extract any numbers they mention for the limit):
       {{"tool": "TREND", "limit": [insert number here, default 20]}}
       
    3. If they ask an out-of-scope question (weather, jokes, general chat, random text):
       {{"tool": "MESSAGE", "text": "[Write a natural, polite response explaining why you, as a Moderation AI, cannot answer that.]"}}
    
    User Request: "{user_input}"
    
    Respond ONLY with the JSON array. Do not include markdown formatting (like ```json), backticks, or any extra text.
    """

    try:
        # 2. Get the decision from the LLM
        response = ollama.chat(model=ACTIVE_MODEL, messages=[
            {'role': 'user', 'content': prompt}
        ])
        
        # Clean the output to ensure it's raw JSON
        raw_output = response['message']['content'].strip()
        if raw_output.startswith("```json"): 
            raw_output = raw_output[7:-3].strip()
        elif raw_output.startswith("```"): 
            raw_output = raw_output[3:-3].strip()

        # 3. Parse the JSON array into Python
        tasks = json.loads(raw_output)
        print(f"-> AI Brain Output: {tasks}\n")

        # 4. The Execution Engine
        for task in tasks:
            tool_name = task.get("tool")
            
            if tool_name == "COUNT":
                run_agentic_report()
                
            elif tool_name == "TREND":
                # Safely extract the limit, default to 20 if the AI missed it
                record_limit = task.get("limit", 20) 
                print(f"-> Extracting parameter: Analyzing {record_limit} records...")
                analyze_trends(limit=record_limit)
                
            elif tool_name == "MESSAGE":
                # Let the AI speak its custom rejection message
                ai_message = task.get("text", "I cannot process this request.")
                print(f"Leader Agent: {ai_message}")
                
            else:
                print(f"Error: Unknown tool request: {tool_name}")

    except json.JSONDecodeError:
        print(f"Routing Error: The AI failed to generate valid JSON. Raw output was: {raw_output}")
    except Exception as e:
        print(f"System Error: {e}")

if __name__ == "__main__":
    print("================ TIER-2 COMMAND CENTER ================")
    print("Welcome. Ask me for counts, trends, or try to chat with me.")
    
    while True:
        user_query = input("\nYour Command (or 'exit'): ")
        
        if user_query.lower() in ['exit', 'quit']:
            break
            
        leader_router(user_query)