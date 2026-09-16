"""
replay_with_wiki.py — LLM-Wiki evaluation against the benchmark CSV.

The switchable counterpart to replay_with_rag.py. For each row it consults the
curated knowledge base (wiki/ pages, via shared_utils.wiki), injects the relevant
policy/domain/glossary/edge-case entries into the Wiki judge prompt, gets a verdict,
and writes it to `agent_final_decision_with_wiki`. Comparing this column against
`agent_final_decision_with_rag` is the RAG-vs-Wiki result the supervisor asked for.

Crash-safe: checkpoints the CSV every few rows (atomic write), and on an Ollama
rate limit (429) it saves and exits cleanly so nothing is lost — re-run the same
command to resume (finished rows are skipped).

Prerequisite: none beyond the knowledge base in wiki/ and Ollama serving the model
in shared_utils/config.py::ACTIVE_MODEL. No Qdrant needed (the wiki is embedded
in memory, reusing the RAG embedder).

Usage:
    # Smoke test — first 5 rows, no writes:
    python -u scripts/eval/replay_with_wiki.py --csv thesis_benchmark_eval.csv --limit 5

    # Full run:
    python -u scripts/eval/replay_with_wiki.py --csv thesis_benchmark_eval.csv --apply

    # Re-judge rows already done:
    python -u scripts/eval/replay_with_wiki.py --csv thesis_benchmark_eval.csv --apply --force
"""

import argparse
import os
import sys
import time

import pandas as pd

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

from shared_utils.config import ACTIVE_MODEL
from shared_utils.llm import ollama_chat_json
from shared_utils.prompts import build_judge_prompt_with_wiki
from shared_utils.wiki import fetch_wiki_bundle

# ResponseError carries Ollama's HTTP status (e.g. 429 = session usage limit).
try:
    from ollama import ResponseError
except Exception:
    ResponseError = None

# Checkpoint the CSV every N processed rows so a crash or rate limit never loses
# more than this many rows of (expensive) LLM work.
CHECKPOINT_EVERY = 5

OUT_DECISION = "agent_final_decision_with_wiki"
OUT_EXPLAIN = "agent_explanation_with_wiki"
OUT_PAGES = "agent_wiki_pages_used"
OUT_COUNT = "agent_wiki_count"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", required=True, help="Path to the benchmark CSV.")
    parser.add_argument("--output", default=None, help="Output CSV path (default: overwrite input).")
    parser.add_argument("--apply", action="store_true", help="Write the CSV (default: dry run).")
    parser.add_argument("--limit", type=int, default=None, help="Cap the number of rows.")
    parser.add_argument("--force", action="store_true", help="Re-judge rows that already have a wiki verdict.")
    parser.add_argument("--sleep", type=float, default=0.5, help="Seconds between LLM calls.")
    args = parser.parse_args()

    if not os.path.exists(args.csv):
        print(f"[ERROR] CSV not found: {args.csv}")
        sys.exit(1)

    output_path = args.output or args.csv

    df = pd.read_csv(args.csv)
    for c in (OUT_DECISION, OUT_EXPLAIN, OUT_PAGES):
        if c not in df.columns:
            df[c] = ""
    if OUT_COUNT not in df.columns:
        df[OUT_COUNT] = 0

    print(f"-> CSV:    {args.csv} ({len(df)} rows)")
    print(f"-> Output: {output_path}")
    print(f"-> Model:  {ACTIVE_MODEL}")
    print(f"-> Backend: LLM-Wiki (curated knowledge base)")
    print(f"-> Mode:   {'APPLY (writing CSV)' if args.apply else 'DRY RUN (no CSV write)'}")
    if args.limit:
        print(f"-> Limit:  first {args.limit} rows")
    print()

    processed = 0
    parsed_errors = 0
    deltas = 0  # baseline vs with_wiki disagreement

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
        existing = str(row.get(OUT_DECISION) or "").strip()
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

        bundle = fetch_wiki_bundle(query_text=text, domain=domain)

        prompt = build_judge_prompt_with_wiki(
            raw_text=text,
            original_prediction=original_prediction,
            confidence=confidence,
            domain=domain,
            strictness=strictness,
            subgenre=subgenre,
            knowledge_text=bundle["knowledge_text"],
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
            wiki_decision = "Parsing Error"
            wiki_explanation = "LLM produced unparseable JSON twice in a row."
            parsed_errors += 1
        else:
            wiki_decision = result.get("decision", "Unknown")
            wiki_explanation = result.get("explanation", "No explanation.")

        processed += 1
        is_delta = baseline_decision.strip().lower() != wiki_decision.strip().lower()
        if is_delta:
            deltas += 1

        marker = " *DELTA*" if is_delta else ""
        print(
            f"[{processed:4d}] {str(row.get('message_id',''))[:24]:<26s} "
            f"baseline={baseline_decision!r:<22s} with_wiki={wiki_decision!r:<22s} "
            f"({bundle['count']}kb, {latency:.1f}s){marker}"
        )

        df.at[idx, OUT_DECISION] = wiki_decision
        df.at[idx, OUT_EXPLAIN] = wiki_explanation
        df.at[idx, OUT_PAGES] = ",".join(bundle["pages_used"])
        df.at[idx, OUT_COUNT] = bundle["count"]

        if processed % CHECKPOINT_EVERY == 0:
            save_progress()

        if args.sleep:
            time.sleep(args.sleep)
    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Ctrl-C — saving progress before exit.")
        save_progress("interrupted")
        return

    print()
    print(f"Processed:                   {processed}")
    print(f"Parse errors:                {parsed_errors}")
    if processed:
        print(f"Baseline vs with_wiki deltas: {deltas} ({deltas / processed * 100:.1f}%)")

    if args.apply and processed:
        save_progress("final")
        print(f"[OK] Wrote {output_path}")
    elif not args.apply:
        print("\nRe-run with --apply to write the CSV.")


if __name__ == "__main__":
    main()
