"""
Tier-2 XAI Batch Auditor (Stage 2 — memory-augmented).

Asynchronously sweeps the Elasticsearch index for unreviewed records under
the configured confidence threshold and asks the Tier-2 LLM to validate
the Tier-1 DistilBERT prediction. When `MEMORY_ENABLED`, the prompt is
enriched with the author's recent history, the same thread's last few
messages, and a behavioural fingerprint — addressing the implicit-bias
blindness failure mode flagged in Internship Report §6.3.

Writes the verdict back as an agent_* overlay on the same document.

USAGE
-----
    # Default — drain whatever's unreviewed under threshold, 60 records:
    python src/agents/xai_batch_judge.py

    # Only audit Twitch records (so under-represented platforms catch up):
    python src/agents/xai_batch_judge.py --platform Twitch

    # Multiple platforms or domains:
    python src/agents/xai_batch_judge.py --platform Twitch --platform Reddit
    python src/agents/xai_batch_judge.py --domain Gaming --domain Politics

    # Larger batch + override confidence ceiling:
    python src/agents/xai_batch_judge.py --batch-size 200 --confidence 1.01

    # Per-domain cap (balanced sweep across all domains):
    python src/agents/xai_batch_judge.py --per-domain-cap 30 --batch-size 300

    # Dry-run (don't write verdicts to ES):
    python src/agents/xai_batch_judge.py --no-update
"""

import argparse
import os
import sys
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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

es = Elasticsearch(ES_HOST, request_timeout=60)

# =====================================================================
# Defaults — can be overridden via CLI args
# =====================================================================
DEFAULT_BATCH_SIZE = 60
DEFAULT_CONFIDENCE_CEILING = 0.80


def _build_query(batch_size: int, conf_below: float, platforms, domains):
    must = [{"range": {"model_confidence": {"lt": conf_below}}}]
    if platforms:
        must.append({"terms": {"source_platform": platforms}})
    if domains:
        must.append({"terms": {"env_domain": domains}})

    return {
        "query": {
            "bool": {
                "must_not": [{"term": {"agent_reviewed": True}}],
                "must": must,
            }
        },
        "sort": [{"timestamp": {"order": "desc"}}],
        "size": batch_size,
    }


def _fetch_records_per_domain(batch_size, conf_below, platforms, per_domain_cap):
    """Balanced sweep: cap per-domain so over-represented platforms don't drown others."""
    # Use a composite aggregation to walk every (env_domain) bucket and pull a
    # capped sample from each. Simpler approach: iterate domains we know about.
    domains_query = {
        "size": 0,
        "query": {
            "bool": {
                "must_not": [{"term": {"agent_reviewed": True}}],
                "must": [{"range": {"model_confidence": {"lt": conf_below}}}]
                       + ([{"terms": {"source_platform": platforms}}] if platforms else []),
            }
        },
        "aggs": {"domains": {"terms": {"field": "env_domain", "size": 50}}},
    }
    res = es.search(index=INDEX_NAME, body=domains_query)
    domain_buckets = res["aggregations"]["domains"]["buckets"]

    if not domain_buckets:
        return []

    print(f"-> Found {len(domain_buckets)} unreviewed domains. Pulling up to {per_domain_cap} per domain.")

    collected = []
    for b in domain_buckets:
        d = b["key"]
        if len(collected) >= batch_size:
            break
        remaining = batch_size - len(collected)
        size = min(per_domain_cap, remaining)
        q = _build_query(size, conf_below, platforms, [d])
        r = es.search(index=INDEX_NAME, body=q)
        collected.extend(r["hits"]["hits"])

    return collected[:batch_size]


def run_batch_auditor(args):
    print("\n=== STARTING XAI BATCH AUDITOR ===")
    print(f"Target Index:   {INDEX_NAME}")
    print(f"Batch Size:     {args.batch_size}")
    print(f"Confidence <    {args.confidence}")
    print(f"Platform filter: {args.platform or 'any'}")
    print(f"Domain filter:   {args.domain or 'any'}")
    print(f"Per-domain cap:  {args.per_domain_cap or 'no cap'}")
    print(f"Memory:         {MEMORY_ENABLED}")
    print(f"Update ES:      {not args.no_update}\n")

    try:
        if args.per_domain_cap:
            hits = _fetch_records_per_domain(
                args.batch_size, args.confidence, args.platform, args.per_domain_cap
            )
        else:
            query = _build_query(args.batch_size, args.confidence, args.platform, args.domain)
            res = es.search(index=INDEX_NAME, body=query)
            hits = res["hits"]["hits"]

        if not hits:
            print("No unreviewed records found matching your criteria!")
            return

        print(f"Found {len(hits)} records to audit. Beginning process...\n")

        ok_count = 0
        err_count = 0

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
            author_id = source.get("author_id", "UNKNOWN")
            thread_id = source.get("thread_id", "N/A")
            message_id = source.get("message_id")
            timestamp = source.get("timestamp")
            platform = source.get("source_platform", "?")

            print(f"--- RECORD {index}/{len(hits)} ---")
            print(f"PLATFORM: {platform} | USER: {author} | DOMAIN: {domain} ({strictness})")
            print(f'TEXT: "{raw_text[:140]}"')
            print(f"DISTILBERT: {original_prediction} (Conf: {confidence:.2f})")

            # Build prompt (baseline OR memory-augmented).
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

                print(f"-> Memory: {memory_user_msgs}u / {memory_thread_msgs}t | {memory_fingerprint}")

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

            print("-> Thinking...")
            start_time = time.time()

            # Per-record try/except so a single Ollama timeout doesn't kill the batch.
            try:
                result = ollama_chat_json(prompt)
            except Exception as e:
                print(f"-> LLM ERROR (record skipped): {e}")
                err_count += 1
                time.sleep(args.sleep)
                continue

            latency = time.time() - start_time
            print(f"-> Inference: {latency:.2f}s")

            if result is None:
                final_decision = "Parsing Error"
                explanation = "LLM produced unparseable JSON twice in a row."
            else:
                final_decision = result.get("decision", "Unknown")
                explanation = result.get("explanation", "No explanation.")

            print(f"VERDICT: {final_decision}")

            if not args.no_update:
                doc_update = {
                    "agent_reviewed": True,
                    "agent_model_used": ACTIVE_MODEL,
                    "agent_final_decision": final_decision,
                    "agent_explanation": explanation,
                    "agent_latency_seconds": round(latency, 2),
                    "agent_memory_used": memory_used,
                    "agent_memory_user_msgs": memory_user_msgs,
                    "agent_memory_thread_msgs": memory_thread_msgs,
                    "agent_memory_user_profile": memory_fingerprint,
                }
                try:
                    es.update(index=INDEX_NAME, id=doc_id, body={"doc": doc_update})
                    ok_count += 1
                except Exception as e:
                    print(f"-> ES UPDATE FAILED: {e}")
                    err_count += 1
            else:
                print("-> [DRY RUN - NOT SAVED]")
                ok_count += 1

            print("")
            time.sleep(args.sleep)

        print(f"=== BATCH COMPLETE: {ok_count} ok, {err_count} errors ===")

    except KeyboardInterrupt:
        print("\n-> Batch interrupted by user. Records already saved are committed.")
    except Exception as e:
        print(f"Batch Error: {e}")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                        help=f"Total records to audit this run (default: {DEFAULT_BATCH_SIZE}).")
    parser.add_argument("--confidence", type=float, default=DEFAULT_CONFIDENCE_CEILING,
                        help=f"Audit records with model_confidence < this (default: {DEFAULT_CONFIDENCE_CEILING}). "
                             "Set 1.01 to audit everything.")
    parser.add_argument("--platform", action="append", default=None,
                        help="Restrict to specific source_platform value(s). Repeat for multiple.")
    parser.add_argument("--domain", action="append", default=None,
                        help="Restrict to specific env_domain value(s). Repeat for multiple.")
    parser.add_argument("--per-domain-cap", type=int, default=None,
                        help="Pull at most N records per domain (balanced sweep).")
    parser.add_argument("--no-update", action="store_true",
                        help="Dry run — don't write verdicts to ES.")
    parser.add_argument("--sleep", type=float, default=2.0,
                        help="Seconds between LLM calls (rate-limit guard).")
    args = parser.parse_args()

    run_batch_auditor(args)


if __name__ == "__main__":
    main()
