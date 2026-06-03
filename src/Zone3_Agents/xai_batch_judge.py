"""
Tier-2 XAI Batch Auditor.

Asynchronously sweeps the Elasticsearch index for unreviewed records under
the configured confidence threshold and asks the Tier-2 LLM to validate
the Tier-1 DistilBERT prediction. Writes the verdict back as an
agent_* overlay on the same document.

Master Control Panel constants at the top are intentionally simple knobs
the operator flips before each run.
"""

import os
import sys
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from elasticsearch import Elasticsearch

from shared_utils.config import ES_HOST, INDEX_NAME, ACTIVE_MODEL
from shared_utils.llm import ollama_chat_json
from shared_utils.prompts import build_judge_prompt

es = Elasticsearch(ES_HOST)

# =====================================================================
# --- MASTER CONTROL PANEL ---
# =====================================================================

# 1. How many records to audit per run. Use a large number to drain the queue.
BATCH_SIZE = 60

# 2. Confidence ceiling. Records below this Tier-1 confidence are audited.
#    Set > 1.0 to audit everything regardless of confidence.
TARGET_CONFIDENCE_BELOW = 0.80

# 3. Safety switch. True writes the verdict to ES; False is a dry run.
UPDATE_DATABASE = True

# =====================================================================


def run_configurable_batch_auditor():
    print("\n=== STARTING XAI BATCH AUDITOR ===")
    print(f"Target Index: {INDEX_NAME}")
    print(f"Batch Size: {BATCH_SIZE} | Target Conf < {TARGET_CONFIDENCE_BELOW}")
    print(f"Live DB Update Enabled: {UPDATE_DATABASE}\n")

    query = {
        "query": {
            "bool": {
                "must_not": [{"term": {"agent_reviewed": True}}],
                "must": [{"range": {"model_confidence": {"lt": TARGET_CONFIDENCE_BELOW}}}],
            }
        },
        "sort": [{"timestamp": {"order": "desc"}}],
        "size": BATCH_SIZE,
    }

    try:
        res = es.search(index=INDEX_NAME, body=query)
        hits = res["hits"]["hits"]

        if not hits:
            print("No unreviewed records found matching your criteria!")
            return

        print(f"Found {len(hits)} records to audit. Beginning process...\n")

        for index, hit in enumerate(hits, 1):
            doc_id = hit["_id"]
            source = hit["_source"]

            raw_text = source.get("text", "")
            original_prediction = source.get("model_label", "Unknown")
            confidence = source.get("model_confidence", 0)
            domain = source.get("env_domain", "General")
            strictness = source.get("env_strictness", "medium")
            subgenre = source.get("env_subgenre", "")
            author = source.get("author_name", "Unknown")

            print(f"--- RECORD {index}/{len(hits)} ---")
            print(f"USER: {author} | DOMAIN: {domain} ({strictness} strictness)")
            print(f'TEXT: "{raw_text}"')
            print(f"DISTILBERT: {original_prediction} (Conf: {confidence:.2f})")
            print("-> Thinking...")

            prompt = build_judge_prompt(
                raw_text=raw_text,
                original_prediction=original_prediction,
                confidence=confidence,
                domain=domain,
                strictness=strictness,
                subgenre=subgenre,
            )

            start_time = time.time()
            result = ollama_chat_json(prompt)
            latency = time.time() - start_time
            print(f"-> Agent Inference Time: {latency:.2f} seconds")

            if result is None:
                final_decision = "Parsing Error"
                explanation = "LLM produced unparseable JSON twice in a row."
            else:
                final_decision = result.get("decision", "Unknown")
                explanation = result.get("explanation", "No explanation.")

            print(f"VERDICT: {final_decision}")
            print(f"REASON: {explanation}")

            if UPDATE_DATABASE:
                es.update(
                    index=INDEX_NAME,
                    id=doc_id,
                    body={
                        "doc": {
                            "agent_reviewed": True,
                            "agent_model_used": ACTIVE_MODEL,
                            "agent_final_decision": final_decision,
                            "agent_explanation": explanation,
                            "agent_latency_seconds": round(latency, 2),
                        }
                    },
                )
                print("-> [SAVED TO DATABASE]")
            else:
                print("-> [DRY RUN - NOT SAVED]")

            print("")
            time.sleep(2)

        print("=== BATCH COMPLETE ===")

    except Exception as e:
        print(f"Batch Error: {e}")


if __name__ == "__main__":
    run_configurable_batch_auditor()
