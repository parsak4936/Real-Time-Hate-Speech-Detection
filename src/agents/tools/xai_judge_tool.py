"""
XAI Judge — interactive, single-record version invoked by the Leader Agent
when an analyst asks to audit a specific user. Mirrors the forensic logic
of xai_batch_judge and uses the same memory-augmented prompt when
MEMORY_ENABLED.
"""

from elasticsearch import Elasticsearch

from shared_utils.config import (
    ES_HOST,
    INDEX_NAME,
    ACTIVE_MODEL,
    MEMORY_ENABLED,
)
from shared_utils.llm import ollama_chat_json
from shared_utils.memory import fetch_memory_bundle
from shared_utils.prompts import build_judge_prompt, build_judge_prompt_with_memory

es = Elasticsearch(ES_HOST)


def execute_xai_judge(params):
    target_user = params.get("target_user")
    print(f"-> [XAI Agent] Running forensic attribution for user: {target_user}")

    try:
        query = {
            "query": {"match": {"author_name": target_user}},
            "sort": [{"timestamp": {"order": "desc"}}],
            "size": 20,
        }
        res = es.search(index=INDEX_NAME, body=query)

        if not res["hits"]["hits"]:
            return f"Error: No records found for user {target_user}."

        hit = res["hits"]["hits"][0]
        doc_id = hit["_id"]
        source = hit["_source"]

        raw_text = source.get("text", "")
        original_prediction = source.get("model_label", "Unknown")
        confidence = source.get("model_confidence", 0)
        domain = source.get("env_domain", "General")
        strictness = source.get("env_strictness", "medium")
        subgenre = source.get("env_subgenre", "")
        author_id = source.get("author_id", "UNKNOWN")
        thread_id = source.get("thread_id", "N/A")
        message_id = source.get("message_id")
        timestamp = source.get("timestamp")

        memory_used = False
        memory_user_msgs = 0
        memory_thread_msgs = 0
        memory_fingerprint = ""

        if MEMORY_ENABLED:
            bundle = fetch_memory_bundle(
                author_id=author_id,
                thread_id=thread_id,
                before_timestamp=timestamp,
                exclude_message_id=message_id,
            )
            memory_used = True
            memory_user_msgs = bundle["user_msgs_count"]
            memory_thread_msgs = bundle["thread_msgs_count"]
            memory_fingerprint = bundle["fingerprint"]

            prompt = build_judge_prompt_with_memory(
                raw_text=raw_text,
                original_prediction=original_prediction,
                confidence=confidence,
                domain=domain,
                strictness=strictness,
                subgenre=subgenre,
                user_history_text=bundle["user_history_text"],
                thread_context_text=bundle["thread_context_text"],
                user_fingerprint=bundle["fingerprint"],
            )
        else:
            prompt = build_judge_prompt(
                raw_text=raw_text,
                original_prediction=original_prediction,
                confidence=confidence,
                domain=domain,
                strictness=strictness,
                subgenre=subgenre,
            )

        result = ollama_chat_json(prompt)
        if result is None:
            final_decision = "Parsing Error"
            explanation = "LLM produced unparseable JSON twice in a row."
        else:
            final_decision = result.get("decision", "Unknown")
            explanation = result.get("explanation", "No explanation.")

        es.update(
            index=INDEX_NAME,
            id=doc_id,
            body={
                "doc": {
                    "agent_reviewed": True,
                    "agent_model_used": ACTIVE_MODEL,
                    "agent_final_decision": final_decision,
                    "agent_explanation": explanation,
                    "agent_memory_used": memory_used,
                    "agent_memory_user_msgs": memory_user_msgs,
                    "agent_memory_thread_msgs": memory_thread_msgs,
                    "agent_memory_user_profile": memory_fingerprint,
                }
            },
        )

        memory_line = (
            f"\nMemory used: {memory_user_msgs} user msgs / {memory_thread_msgs} thread msgs"
            if memory_used else ""
        )
        return (
            f"--- XAI REPORT FOR '{target_user}' ---\n"
            f"Verdict: {final_decision}\n"
            f"Reason: {explanation}"
            f"{memory_line}\n"
            "(Database Updated Successfully)"
        )

    except Exception as e:
        return f"XAI Tool Failure: {str(e)}"
