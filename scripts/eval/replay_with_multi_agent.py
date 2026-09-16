"""
replay_with_multi_agent.py — Stage 4 evaluation on a benchmark CSV.

For each row, runs the four-agent pipeline (Risk Scorer -> Behavior Profiler
-> Escalator -> Supervisor) and writes the final verdict plus every
intermediate signal back to the CSV. Mirrors replay_with_rag.py so the
evaluation notebook can compare this variant against the others.

Memory context (user history + thread context + fingerprint) is pulled from
Elasticsearch per row, same as the memory replay. Precedents are pulled from
Qdrant if RAG_ENABLED and the collection exists — otherwise the supervisor
just runs without precedents (still valid).

Cost: 4 LLM calls per row (~20-30s each). For 298 rows expect ~1.5-2 hours.
ALWAYS test with --limit 5 first.

Usage:
    # Smoke test on 5 rows (writes nothing unless --apply):
    python -u scripts/replay_with_multi_agent.py --csv thesis_benchmark_eval.csv --limit 5

    # Full run:
    python -u scripts/replay_with_multi_agent.py --csv thesis_benchmark_eval.csv --apply

    # Re-run rows already done:
    python -u scripts/replay_with_multi_agent.py --csv thesis_benchmark_eval.csv --apply --force

Columns written:
    agent_final_decision_with_multi_agent   (Correct | False Positive | False Negative | Parsing Error)
    agent_explanation_with_multi_agent
    agent_ma_risk_score
    agent_ma_behavior_risk
    agent_ma_escalation_action
"""

import argparse
import os
import sys
import time

import pandas as pd

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src")
sys.path.insert(0, ROOT)

from elasticsearch import Elasticsearch

# ResponseError carries Ollama's HTTP status (e.g. 429 = session usage limit).
# Optional import so the script still runs if the ollama lib layout changes.
try:
    from ollama import ResponseError
except Exception:  # pragma: no cover
    ResponseError = None

from shared_utils.config import ES_HOST, INDEX_NAME, ACTIVE_MODEL, RAG_ENABLED
from shared_utils.memory import fetch_memory_bundle
from agents.multi_agent import run_multi_agent

# Flush the CSV to disk every N freshly-processed rows so a crash (rate limit,
# network drop, Ctrl-C) loses at most this many rows instead of the whole run.
CHECKPOINT_EVERY = 5

# RAG precedents are optional — only attempt if enabled and importable.
_fetch_precedents = None
if RAG_ENABLED:
    try:
        from shared_utils.rag import fetch_retrieval_bundle as _fetch_precedents
    except Exception:
        _fetch_precedents = None

es = Elasticsearch(ES_HOST, request_timeout=60)

OUT_DECISION = "agent_final_decision_with_multi_agent"
OUT_EXPLAIN = "agent_explanation_with_multi_agent"
OUT_RISK = "agent_ma_risk_score"
OUT_BEHAVIOR = "agent_ma_behavior_risk"
OUT_ESCALATION = "agent_ma_escalation_action"
# Full per-agent reasoning — saved so the four agents' processing is auditable
# (e.g. to show a supervisor exactly why each verdict was reached).
OUT_RISK_RATIONALE = "agent_ma_risk_rationale"
OUT_PROFILE = "agent_ma_profile_summary"
OUT_ESC_RATIONALE = "agent_ma_escalation_rationale"
OUT_ESC_HUMAN = "agent_ma_escalate_to_human"

NEW_COLS = [
    OUT_DECISION, OUT_EXPLAIN, OUT_RISK, OUT_BEHAVIOR, OUT_ESCALATION,
    OUT_RISK_RATIONALE, OUT_PROFILE, OUT_ESC_RATIONALE, OUT_ESC_HUMAN,
]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--csv", required=True)
    p.add_argument("--output", default=None, help="Output CSV (default: overwrite input).")
    p.add_argument("--apply", action="store_true", help="Write the CSV (default: dry run).")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--force", action="store_true", help="Re-run rows already done.")
    p.add_argument("--sleep", type=float, default=0.3)
    args = p.parse_args()

    if not os.path.exists(args.csv):
        print(f"[ERROR] CSV not found: {args.csv}")
        sys.exit(1)

    out_path = args.output or args.csv
    df = pd.read_csv(args.csv)
    for c in NEW_COLS:
        if c not in df.columns:
            df[c] = ""

    print(f"-> CSV:    {args.csv} ({len(df)} rows)")
    print(f"-> Output: {out_path}")
    print(f"-> Model:  {ACTIVE_MODEL}  (4 calls/row)")
    print(f"-> RAG precedents: {'ON' if _fetch_precedents else 'OFF'}")
    print(f"-> Mode:   {'APPLY' if args.apply else 'DRY RUN'}")
    if args.limit:
        print(f"-> Limit:  first {args.limit} rows")
    print()

    processed = 0
    deltas = 0

    def save_progress(reason=""):
        """Atomically write the CSV so a partial run is never half-written."""
        if not (args.apply and processed):
            return
        tmp = out_path + ".tmp"
        df.to_csv(tmp, index=False, encoding="utf-8")
        os.replace(tmp, out_path)
        tag = f" ({reason})" if reason else ""
        print(f"[checkpoint] saved {processed} processed rows -> {out_path}{tag}")

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
        author_name = str(row.get("author_name", "Unknown") or "Unknown")
        author_id = str(row.get("author_id", "UNKNOWN") or "UNKNOWN")
        thread_id = str(row.get("thread_id", "N/A") or "N/A")
        message_id = str(row.get("message_id", "") or "")
        timestamp = row.get("timestamp")
        baseline_decision = str(row.get("agent_final_decision", "") or "")

        # Memory context from ES (same as memory replay).
        try:
            bundle = fetch_memory_bundle(
                author_id=author_id,
                thread_id=thread_id,
                before_timestamp=timestamp,
                exclude_message_id=message_id,
            )
        except Exception:
            bundle = {
                "fingerprint": "(no fingerprint)",
                "user_history_text": "(no history)",
                "thread_context_text": "(no thread context)",
            }

        precedents_text = ""
        if _fetch_precedents:
            try:
                rb = _fetch_precedents(query_text=text, exclude_message_id=message_id)
                precedents_text = rb.get("precedents_text", "")
            except Exception:
                precedents_text = ""

        start = time.time()
        try:
            result = run_multi_agent(
                raw_text=text,
                original_prediction=original_prediction,
                confidence=confidence,
                domain=domain,
                strictness=strictness,
                author_name=author_name,
                fingerprint=bundle.get("fingerprint", ""),
                user_history_text=bundle.get("user_history_text", ""),
                thread_context_text=bundle.get("thread_context_text", ""),
                precedents_text=precedents_text,
                subgenre=subgenre,
            )
        except Exception as exc:  # noqa: BLE001 — we re-raise non-recoverable ones
            status = getattr(exc, "status_code", None)
            is_rate_limit = status == 429 or (
                ResponseError is not None and isinstance(exc, ResponseError) and status == 429
            )
            if is_rate_limit:
                print(f"\n[STOP] Ollama rate limit (429) at row {idx}. "
                      f"Already-processed rows are safe.")
                save_progress("rate limit reached")
                print("Re-run the SAME command later — done rows are skipped automatically.")
                return
            # Any other error: persist what we have, then surface the failure.
            print(f"\n[ERROR] Unexpected failure at row {idx}: {exc}")
            save_progress("error — partial results kept")
            raise
        latency = time.time() - start

        processed += 1
        decision = result["decision"]
        is_delta = baseline_decision.strip().lower() != decision.strip().lower()
        if is_delta:
            deltas += 1
        marker = " *DELTA*" if is_delta else ""

        print(
            f"[{processed:4d}] {message_id[:22]:<24s} "
            f"base={baseline_decision!r:<18s} MA={decision!r:<18s} "
            f"(risk={result['risk_score']:.2f}/{result['behavior_risk']}/{result['escalation_action']}, "
            f"{latency:.1f}s){marker}"
        )

        df.at[idx, OUT_DECISION] = decision
        df.at[idx, OUT_EXPLAIN] = result["explanation"]
        df.at[idx, OUT_RISK] = result["risk_score"]
        df.at[idx, OUT_BEHAVIOR] = result["behavior_risk"]
        df.at[idx, OUT_ESCALATION] = result["escalation_action"]
        df.at[idx, OUT_RISK_RATIONALE] = result["risk_rationale"]
        df.at[idx, OUT_PROFILE] = result["profile_summary"]
        df.at[idx, OUT_ESC_RATIONALE] = result["escalation_rationale"]
        df.at[idx, OUT_ESC_HUMAN] = result["escalate_to_human"]

        if processed % CHECKPOINT_EVERY == 0:
            save_progress()

        if args.sleep:
            time.sleep(args.sleep)
    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Ctrl-C — saving progress before exit.")
        save_progress("interrupted")
        return

    print()
    print(f"Processed: {processed}")
    if processed:
        print(f"Baseline vs multi-agent deltas: {deltas} ({deltas / processed * 100:.1f}%)")

    if args.apply and processed:
        save_progress("final")
        print(f"[OK] Wrote {out_path}")
    elif not args.apply:
        print("\nDry run. Re-run with --apply to write the CSV.")


if __name__ == "__main__":
    main()
