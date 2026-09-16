"""
replay_with_rag.py — leave-one-out RAG evaluation against a labelled CSV.

Purpose:
    For each row in the benchmark CSV, query the Qdrant index for top-k
    semantically similar rows (EXCLUDING the row itself), inject them as
    precedents into the RAG-only judge prompt, get a verdict, and write it
    to a new `agent_final_decision_with_rag` column in an OUTPUT CSV.

    The notebook §5 then compares baseline (no RAG) vs with-RAG against
    human_ground_truth, using McNemar's test for significance.

    This evaluation requires NO live ES data and NO new manual labelling
    — the 459-record internship CSV already carries human_ground_truth.

Usage:
    # Smoke test — first 5 rows, no writes to disk:
    python scripts/replay_with_rag.py --csv thesis_final_benchmark.csv --limit 5

    # Full leave-one-out replay, writing back to the same CSV:
    python scripts/replay_with_rag.py --csv thesis_final_benchmark.csv --apply

    # Write to a different file (preserve the original):
    python scripts/replay_with_rag.py --csv thesis_final_benchmark.csv --apply \\
        --output thesis_final_benchmark_with_rag.csv

Idempotency:
    Rows that already have a non-empty agent_final_decision_with_rag are
    skipped unless --force is passed.

Prerequisite:
    Run `python scripts/seed_rag_from_csv.py <csv> --apply` first so the
    Qdrant collection has the precedent corpus.

Requires:
    Docker stack up (Qdrant reachable), Ollama serving the model in
    shared_utils/config.py::ACTIVE_MODEL.
"""

import argparse
import os
import sys
import time

import pandas as pd

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

from shared_utils.config import ACTIVE_MODEL
from shared_utils.llm import ollama_chat_json
from shared_utils.prompts import build_judge_prompt_with_rag
from shared_utils.rag import fetch_retrieval_bundle

# ResponseError carries Ollama's HTTP status (e.g. 429 = session usage limit).
try:
    from ollama import ResponseError
except Exception:
    ResponseError = None

# Checkpoint the CSV to disk every N processed rows so a crash or rate limit
# never loses more than this many rows of (expensive) LLM work.
CHECKPOINT_EVERY = 5


def _row_message_id(idx: int, row) -> str:
    """Same id-synthesis convention as seed_rag_from_csv.py."""
    mid = row.get("message_id")
    if mid is None or pd.isna(mid):
        return f"csv-row-{idx}"
    s = str(mid).strip()
    if not s or s in ("nan", "UNKNOWN"):
        return f"csv-row-{idx}"
    return s


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--csv", required=True, help="Path to the benchmark CSV.")
    parser.add_argument("--output", default=None, help="Output CSV path (default: overwrite input).")
    parser.add_argument("--apply", action="store_true", help="Write the CSV (default: dry run).")
    parser.add_argument("--limit", type=int, default=None, help="Cap the number of rows.")
    parser.add_argument("--force", action="store_true", help="Re-judge rows that already have agent_final_decision_with_rag.")
    parser.add_argument("--sleep", type=float, default=0.5, help="Seconds between LLM calls.")
    args = parser.parse_args()

    if not os.path.exists(args.csv):
        print(f"[ERROR] CSV not found: {args.csv}")
        sys.exit(1)

    output_path = args.output or args.csv

    df = pd.read_csv(args.csv)
    # Ensure the column exists so we can write into it row-by-row.
    if "agent_final_decision_with_rag" not in df.columns:
        df["agent_final_decision_with_rag"] = ""
    if "agent_explanation_with_rag" not in df.columns:
        df["agent_explanation_with_rag"] = ""
    if "agent_retrieved_precedent_ids" not in df.columns:
        df["agent_retrieved_precedent_ids"] = ""
    if "agent_retrieval_count" not in df.columns:
        df["agent_retrieval_count"] = 0

    print(f"-> CSV:    {args.csv} ({len(df)} rows)")
    print(f"-> Output: {output_path}")
    print(f"-> Model:  {ACTIVE_MODEL}")
    print(f"-> Mode:   {'APPLY (writing CSV)' if args.apply else 'DRY RUN (no CSV write)'}")
    if args.limit:
        print(f"-> Limit:  first {args.limit} rows")
    print()

    processed = 0
    parsed_errors = 0
    deltas = 0  # baseline vs with_rag disagreement

    def save_progress(reason=""):
        """Atomically write the CSV so a partial/interrupted run is never half-written."""
        if not (args.apply and processed):
            return
        tmp = output_path + ".tmp"
        df.to_csv(tmp, index=False, encoding="utf-8")
        os.replace(tmp, output_path)
        tag = f" ({reason})" if reason else ""
        print(f"[checkpoint] saved {processed} processed rows -> {output_path}{tag}")

    iterable = df.iterrows()
    if args.limit is not None:
        from itertools import islice
        iterable = islice(iterable, args.limit)

    try:
      for idx, row in iterable:
        existing = str(row.get("agent_final_decision_with_rag") or "").strip()
        if existing.lower() in ("nan", "none"):
            existing = ""
        if existing and not args.force:
            continue

        text = str(row.get("text", "") or "").strip()
        if not text:
            continue

        original_prediction = str(row.get("model_label", "Unknown"))
        try:
            confidence = float(row.get("model_confidence", 0) or 0)
        except (TypeError, ValueError):
            confidence = 0.0
        domain = str(row.get("env_domain", "General") or "General")
        strictness = str(row.get("env_strictness", "medium") or "medium")
        subgenre = str(row.get("env_subgenre", "") or "")
        baseline_decision = str(row.get("agent_final_decision", "") or "")

        message_id = _row_message_id(idx, row)

        bundle = fetch_retrieval_bundle(
            query_text=text,
            exclude_message_id=message_id,
        )

        prompt = build_judge_prompt_with_rag(
            raw_text=text,
            original_prediction=original_prediction,
            confidence=confidence,
            domain=domain,
            strictness=strictness,
            subgenre=subgenre,
            precedents_text=bundle["precedents_text"],
        )

        start = time.time()
        try:
            result = ollama_chat_json(prompt)
        except Exception as exc:  # noqa: BLE001 — re-raise non-recoverable ones below
            if getattr(exc, "status_code", None) == 429:
                print(f"\n[STOP] Ollama rate limit (429) at row {idx}. "
                      f"Already-processed rows are safe.")
                save_progress("rate limit reached")
                print("Re-run the SAME command later — done rows are skipped automatically.")
                return
            print(f"\n[ERROR] Unexpected failure at row {idx}: {exc}")
            save_progress("error — partial results kept")
            raise
        latency = time.time() - start

        if result is None:
            rag_decision = "Parsing Error"
            rag_explanation = "LLM produced unparseable JSON twice in a row."
            parsed_errors += 1
        else:
            rag_decision = result.get("decision", "Unknown")
            rag_explanation = result.get("explanation", "No explanation.")

        processed += 1
        is_delta = baseline_decision.strip().lower() != rag_decision.strip().lower()
        if is_delta:
            deltas += 1

        marker = " *DELTA*" if is_delta else ""
        print(
            f"[{processed:4d}] {message_id[:24]:<26s} "
            f"baseline={baseline_decision!r:<22s} with_rag={rag_decision!r:<22s} "
            f"({bundle['precedents_count']}p, {latency:.1f}s){marker}"
        )

        df.at[idx, "agent_final_decision_with_rag"] = rag_decision
        df.at[idx, "agent_explanation_with_rag"] = rag_explanation
        df.at[idx, "agent_retrieved_precedent_ids"] = ",".join(
            str(p) for p in bundle["precedent_ids"] if p
        )
        df.at[idx, "agent_retrieval_count"] = bundle["precedents_count"]

        if processed % CHECKPOINT_EVERY == 0:
            save_progress()

        if args.sleep:
            time.sleep(args.sleep)
    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Ctrl-C — saving progress before exit.")
        save_progress("interrupted")
        return

    print()
    print(f"Processed:                  {processed}")
    print(f"Parse errors:               {parsed_errors}")
    if processed:
        print(f"Baseline vs with_rag deltas: {deltas} ({deltas / processed * 100:.1f}%)")

    if args.apply and processed:
        save_progress("final")
        print(f"[OK] Wrote {output_path}")
    elif not args.apply:
        print("\nRe-run with --apply to write the CSV.")


if __name__ == "__main__":
    main()
