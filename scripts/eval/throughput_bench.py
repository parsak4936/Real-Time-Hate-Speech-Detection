"""
Tier-1 throughput + scaling benchmark  —  PURE MODEL, non-destructive.

Loads the SAME fine-tuned DistilBERT the processor uses (models/bert_final) and
times inference over sample texts. It does NOT connect to Kafka or Elasticsearch
and writes NOTHING to them — it only measures how fast the classifier itself runs.

  * Throughput:  messages/second the classifier sustains (steady state).
  * Scaling:     pass --workers N to run N independent classifier processes over
                 the corpus at once; aggregate msgs/s shows how the compute tier
                 scales across cores (the same way extra Kafka-partition consumers
                 would scale the real pipeline).

Run 1, then 2, then 4 workers and record the aggregate rate each time:

    python scripts/eval/throughput_bench.py --n 2000 --workers 1
    python scripts/eval/throughput_bench.py --n 2000 --workers 2
    python scripts/eval/throughput_bench.py --n 2000 --workers 4
"""
import argparse
import csv
import os
import time
from pathlib import Path

# Match the processor: it runs DistilBERT on CPU (no .to(cuda)). Forcing CPU also
# avoids GPU contention when several workers run at once.
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / "models" / "bert_final"
CSV_LOG = ROOT / "data" / "stream_log.csv"


def load_texts(n):
    texts = []
    if CSV_LOG.exists():
        with open(CSV_LOG, encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f):
                t = (row.get("text") or "").strip()
                if t:
                    texts.append(t)
    if not texts:
        texts = ["this is a sample chat message for benchmarking"] * 200
    # repeat/truncate to exactly n
    out = (texts * (n // len(texts) + 1))[:n]
    return out


_THREADS = 0  # set per-process by the pool initializer


def _init_worker(threads):
    global _THREADS
    _THREADS = threads


def worker(texts):
    """Load model, warm up, then time classification of `texts`. Returns (count, seconds)."""
    import torch
    if _THREADS:
        torch.set_num_threads(_THREADS)   # pin cores/worker for a clean scaling curve
    from transformers import DistilBertForSequenceClassification, DistilBertTokenizer
    tok = DistilBertTokenizer.from_pretrained(str(MODEL_DIR))
    mdl = DistilBertForSequenceClassification.from_pretrained(str(MODEL_DIR))
    mdl.eval()

    def classify(t):
        inp = tok(str(t), return_tensors="pt", truncation=True, padding=True, max_length=128)
        with torch.no_grad():
            mdl(**inp)

    for t in texts[:10]:          # warm-up (not timed)
        classify(t)
    t0 = time.time()
    for t in texts:
        classify(t)
    return len(texts), time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=2000, help="total messages to classify")
    ap.add_argument("--workers", type=int, default=1, help="parallel classifier processes")
    ap.add_argument("--threads", type=int, default=0,
                    help="torch threads per worker (0=all cores; use 1 for a clean per-core scaling curve)")
    args = ap.parse_args()

    if not MODEL_DIR.exists():
        print(f"[!] Model not found at {MODEL_DIR}")
        return

    texts = load_texts(args.n)
    print(f"Benchmarking {len(texts)} messages across {args.workers} worker(s)...")

    t_start = time.time()
    if args.workers == 1:
        _init_worker(args.threads)
        per_worker = [worker(texts)]
    else:
        from concurrent.futures import ProcessPoolExecutor
        shards = [texts[i::args.workers] for i in range(args.workers)]
        with ProcessPoolExecutor(max_workers=args.workers,
                                 initializer=_init_worker, initargs=(args.threads,)) as ex:
            per_worker = list(ex.map(worker, shards))
    wall = time.time() - t_start

    total = sum(c for c, _ in per_worker)
    max_infer = max(s for _, s in per_worker)     # steady-state = parallel inference, excludes model load
    steady = total / max_infer if max_infer else 0
    agg_wall = total / wall
    print(f"\n  workers          : {args.workers}  (threads/worker: {args.threads or 'all cores'})")
    for i, (c, s) in enumerate(per_worker):
        print(f"  worker {i}         : {c} msgs in {s:.1f}s -> {c/s:.1f} msg/s")
    print(f"  STEADY-STATE     : {total} msgs / {max_infer:.1f}s inference -> {steady:.1f} msg/s "
          f"(~{steady*60:,.0f} msg/min)   <-- use this for the scaling curve")
    print(f"  incl. model load : {agg_wall:.1f} msg/s over {wall:.1f}s wall")
    print(f"\nRecord:  workers={args.workers}  threads={args.threads or 'all'}  "
          f"steady_state={steady:.1f} msg/s")


if __name__ == "__main__":
    main()
