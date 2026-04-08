import sys
import os

# This line ensures Python can find your 'shared_utils' folder 
# no matter where you run the script from.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ollama
from elasticsearch import Elasticsearch
from shared_utils.config import ES_HOST, INDEX_NAME, ACTIVE_MODEL

# 1. Connect to the Database
print(f"Connecting to Elasticsearch at {ES_HOST}...")
es = Elasticsearch(ES_HOST)

def run_simple_test():
    try:
        # 2. Get the exact count of documents in the database
        res = es.count(index=INDEX_NAME)
        total_data_count = res['count']
        print(f"Success! Found {total_data_count} tweets in the database.\n")

        # 3. Create the prompt for the AI
        prompt = (
            f"I am building an AI moderation pipeline for my thesis. "
            f"My database currently has {total_data_count} tweets processed in it. "
            f"Please write a short, one-sentence confirmation saying the system is online and state the current database size."
        )

        print(f"Sending data to AI model: {ACTIVE_MODEL}...")

        # 4. Send to the AI using your config variable
        response = ollama.chat(model=ACTIVE_MODEL, messages=[
            {'role': 'user', 'content': prompt}
        ])

        # 5. Print the final result
        print("\n--- AI Status Report ---")
        print(response['message']['content'])

    except Exception as e:
        print(f"\nError: {e}")
        print("Hint: Make sure Elasticsearch is running in Docker!")

if __name__ == "__main__":
    run_simple_test()