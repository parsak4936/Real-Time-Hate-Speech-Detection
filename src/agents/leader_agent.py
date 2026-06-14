"""
Leader Agent — natural-language analyst console.

Two-phase orchestration:
  Phase 1 (router):  the LLM classifies the user's intent into a tool call.
  Phase 2 (execute): the chosen tool runs against Elasticsearch / external APIs.
  Phase 3 (synth):   a second LLM call summarises the raw results for the analyst.

All prompts live in shared_utils/prompts.py. All Ollama calls go through
shared_utils/llm.py so temperature=0 and JSON-mode are enforced uniformly.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from elasticsearch import Elasticsearch

from shared_utils.config import ES_HOST, INDEX_NAME, ACTIVE_MODEL
from shared_utils.llm import ollama_chat_json, ollama_chat_text
from shared_utils.prompts import (
    build_leader_router_prompt,
    build_leader_synthesis_prompt,
)

from agents.tools.search_tool import execute_universal_search
from agents.tools.stats_tool import execute_statistics
from agents.tools.weather_tool import execute_weather_time
from agents.tools.xai_judge_tool import execute_xai_judge

TOOL_REGISTRY = {
    "UNIVERSAL_SEARCH": execute_universal_search,
    "GET_STATISTICS": execute_statistics,
    "GET_WEATHER": execute_weather_time,
    "XAI_JUDGE": execute_xai_judge,
}

print(f"Booting Modular Orchestrator on {ACTIVE_MODEL}...")
es = Elasticsearch(ES_HOST)


def get_database_schema():
    try:
        res = es.search(index=INDEX_NAME, size=1)
        if res["hits"]["hits"]:
            return list(res["hits"]["hits"][0]["_source"].keys())
        return []
    except Exception:
        return ["error_reading_schema"]


DB_SCHEMA_KEYS = get_database_schema()
print(f"-> AI Schema Awareness Loaded: {DB_SCHEMA_KEYS}")


def leader_router(user_input):
    print("\n[Phase 1: Analyzing Intent...]")

    router_prompt = build_leader_router_prompt(user_input, DB_SCHEMA_KEYS)
    params = ollama_chat_json(router_prompt)

    if params is None:
        print("Routing Error: The AI failed to generate valid JSON after one retry.")
        return

    print(f"-> AI Brain Output: {params}\n")

    tool = params.get("tool")

    if tool == "DIRECT_MESSAGE":
        print(f"Leader: {params.get('message', 'Hello.')}")
        return

    if tool not in TOOL_REGISTRY:
        print(f"Error: The AI hallucinated a tool. '{tool}' is not in the registry.")
        return

    raw_database_results = TOOL_REGISTRY[tool](params)

    print("\n[Phase 3: Synthesizing Final Report...]")
    synthesis_prompt = build_leader_synthesis_prompt(user_input, raw_database_results)
    final_text = ollama_chat_text(synthesis_prompt)

    print("\n================ TIER-2 AGENT REPORT ================")
    print(final_text)
    print("=====================================================")


if __name__ == "__main__":
    print("================ TIER-2 COMMAND CENTER ================")
    print("Welcome to the Universal RAG Terminal.")

    while True:
        try:
            user_query = input("\nYour Command (or 'exit'): ")
        except (EOFError, KeyboardInterrupt):
            break

        if user_query.lower() in ("exit", "quit"):
            break

        try:
            leader_router(user_query)
        except Exception as e:
            print(f"System Error: {e}")
