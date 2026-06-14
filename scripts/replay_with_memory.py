"""
replay_with_memory.py — re-judge already-reviewed ES records with memory injected.

Purpose:
    The internship pipeline produced ~459 records with verdicts in
    `agent_final_decision`. Those verdicts were made WITHOUT temporal
    memory. To measure the contribution of the memory-augmented judge
    prompt, we re-run the Tier-2 judge against those same records with
    memory enabled, writing the new verdicts to
    `agent_final_decision_with_memory`. The original `agent_final_decision`
    field is NEVER touched. The evaluation notebook then compares the two
    columns against the human ground truth.

Behaviour:
    - Reads either ALL reviewed records in ES, or a specific subset
      identified by a CSV with a `message_id` column (--csv).
    - For each record, fetches the live memory bundle (user history,
      thread context, fingerprint) from ES.
    - Calls the memory-augmented judge prompt.
    - Writes to the *_with_memory fields only.
    - Dry-run by default. Pass --apply to actually write.

Usage:
    # Preview against every reviewed record:
    python scripts/replay_with_memory.py

    # Preview against a specific benchmark CSV:
    python scripts/replay_with_memory.py --csv thesis_final_benchmark.csv

    # Actually write the memory-augmented verdicts:
    python scripts/replay_with_memory.py --csv thesis_final_benchmark.csv --apply

    # Cap the run to N records for a quick smoke test:
    python scripts/replay_with_memory.py --apply --limit 10

Idempotency:
    Records that already have a non-empty `agent_final_decision_with_memory`
    are skipped unless --force is passed.

Requires:
    Docker stack up (Elasticsearch reachable) and Ollama serving the model
    aliased in shared_utils/config.py::ACTIVE_MODEL.
"""

import argparse
import os
import sys
import time

import pandas as pd

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from elasticsearch import Elasticsearch
from elasticsearch.helpers import scan

from shared_utils.config import ES_HOST, INDEX_NAME, ACTIVE_MODEL
from shared_utils.llm import ollama_chat_json
from shared_utils.memory import fetch_memory_bundle
from shared_utils.prompts import build_judge_prompt_with_memory


def _iter_target_records(es: Elasticsearch, csv_path: str | None, force: bool):
    """
    Yield (doc_id, source) tuples for every record we still need to replay.

    If csv_path is provided, the CSV's `message_id` column drives selection
    (one ES lookup per row). Otherwise we scan every record in ES that has
    agent_reviewed=true.
    """
    if csv_path:
        df = pd.read_csv(csv_path)
        if "message_id" not in df.columns:
            print(
                f"[ERROR] {csv_path} has no message_id column. "
                "Re-export with the latest src/export_subset.py."
            )
            return
        for msg_id in df["message_id"].dropna().astype(str):
            if not msg_id or msg_id == "UNKNOWN":
                continue
            res = es.search(
                index=INDEX_NAME,
                body={"query": {"term": {"message_id": msg_id}}, "size": 1},
            )
            hits = res["hits"]["hits"]
            if not hits:
                print(f"[warn] message_id={msg_id} not found in ES, skipping.")
                continue
            hit = hits[0]
            if not force and hit["_source"].get("agent_final_decision_with_memory"):
                continue
            yield hit["_id"], hit["_source"]
        return

    # Otherwise: scan everything reviewed in ES.
    query = {"query": {"term": {"agent_reviewed": True}}}
    for hit in scan(es, index=INDEX_NAME, query=query, size=200):
        if not force and hit["_source"].get("agent_final_decision_with_memory"):
            continue
        yield hit["_id"], hit["_source"]


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--apply", action="store_true", help="Write memory-augmented verdicts to ES (default: dry run).")
    parser.add_argument("--csv", default=None, help="Restrict to records present in this CSV's message_id column.")
    parser.add_argument("--limit", type=int, default=None, help="Cap the number of records to process.")
    parser.add_argument("--force", action="store_true", help="Re-judge even if a memory-augmented verdict already exists.")
    parser.add_argument("--sleep", type=float, default=1.0, help="Seconds to sleep between LLM calls (rate-limit guard).")
    args = parser.parse_args()

    es = Elasticsearch(ES_HOST)
    print(f"-> ES: {ES_HOST} | INDEX: {INDEX_NAME} | MODEL: {ACTIVE_MODEL}")
    print(f"-> Mode: {'APPLY (writing memory-augmented verdicts)' if args.apply else 'DRY RUN (no writes)'}")
    print(f"-> CSV filter: {args.csv or '(none - every reviewed ES record)'}")
    if args.limit:
        print(f"-> Limit: first {args.limit} records")
    print()

    processed = 0
    parsed_errors = 0
    deltas = 0  # count of baseline-verdict != memory-verdict

    for doc_id, source in _iter_target_records(es, args.csv, args.force):
        if args.limit is not None and processed >= args.limit:
            break

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
        baseline_decision = source.get("agent_final_decision", "?")

        bundle = fetch_memory_bundle(
            author_id=author_id,
            thread_id=thread_id,
            before_timestamp=timestamp,
            exclude_message_id=message_id,
        )

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

        start = time.time()
        result = ollama_chat_json(prompt)
        latency = time.time() - start

        if result is None:
            memory_decision = "Parsing Error"
            memory_explanation = "LLM produced unparseable JSON twice in a row."
            parsed_errors += 1
        else:
            memory_decision = result.get("decision", "Unknown")
            memory_explanation = result.get("explanation", "No explanation.")

        processed += 1
        is_delta = str(baseline_decision).strip().lower() != str(memory_decision).strip().lower()
        if is_delta:
            deltas += 1

        marker = " *DELTA*" if is_delta else ""
        print(
            f"[{processed:4d}] {message_id[:20] if message_id else '?':<22s} "
            f"baseline={baseline_decision!r:<22s} with_memory={memory_decision!r:<22s} "
            f"({bundle['user_msgs_count']}u/{bundle['thread_msgs_count']}t, "
            f"{latency:.1f}s){marker}"
        )

        if args.apply:
            es.update(
                index=INDEX_NAME,
                id=doc_id,
                body={
                    "doc": {
                        "agent_final_decision_with_memory": memory_decision,
                        "agent_explanation_with_memory": memory_explanation,
                        "agent_memory_used": True,
                        "agent_memory_user_msgs": bundle["user_msgs_count"],
                        "agent_memory_thread_msgs": bundle["thread_msgs_count"],
                        "agent_memory_user_profile": bundle["fingerprint"],
                    }
                },
            )

        if args.sleep:
            time.sleep(args.sleep)

    print()
    print(f"Processed:                     {processed}")
    print(f"Parse errors:                  {parsed_errors}")
    print(
        f"Baseline vs with-memory deltas: {deltas} "
        f"({(deltas / processed * 100) if processed else 0:.1f}%)"
    )
    if not args.apply and processed:
        print("\nRe-run with --apply to write these verdicts to ES.")


if __name__ == "__main__":
    main()
