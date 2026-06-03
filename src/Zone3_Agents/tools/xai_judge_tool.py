"""
XAI Judge — interactive, single-record version invoked by the Leader Agent
when an analyst asks to audit a specific user. Mirrors the forensic logic
of xai_batch_judge but runs on the user's most recent message and writes
the verdict straight back to Elasticsearch.
"""

from elasticsearch import Elasticsearch

from shared_utils.config import ES_HOST, INDEX_NAME, ACTIVE_MODEL
from shared_utils.llm import ollama_chat_json
from shared_utils.prompts import build_judge_prompt

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
                }
            },
        )

        return (
            f"--- XAI REPORT FOR '{target_user}' ---\n"
            f"Verdict: {final_decision}\n"
            f"Reason: {explanation}\n"
            f"(Database Updated Successfully)"
        )

    except Exception as e:
        return f"XAI Tool Failure: {str(e)}"
