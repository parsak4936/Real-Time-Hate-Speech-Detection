"""
Replay producer for the scaling experiments  —  writes ONLY to perf_* topics.

Sends a fixed, repeatable workload of real chat messages into a Kafka TEST
topic, so every scaling run processes exactly the same traffic. The Tier-1
processor reads these messages as if they were live chat.

Workload: messages from one collection day of data/stream_log.csv (default
2026-06-13), W of them picked with a fixed seed and kept in their original
order. Same --date, --n and --seed = same messages, every time.

Two modes (see thesis/THESIS_STATE.md section 12, the measurement protocol):
  preload   send everything as fast as possible BEFORE the processors start
            -> measures throughput (how fast the processors drain the topic)
  rate      send exactly --rate messages per second on a fixed schedule
            -> measures end-to-end latency below capacity

Safety:
  * refuses any topic that does not start with "perf_" (never universal_stream)
  * reads stream_log.csv, never writes it; never touches Elasticsearch

Output (written as it goes, so an interrupted run keeps its record):
  reports/scaling/<run_id>/manifest_producer.json   settings + results + status
  reports/scaling/<run_id>/sent.csv                  one row per acknowledged message

Examples:
  # look at the workload without sending anything (no Kafka needed)
  python scripts/eval/replay_producer.py --topic perf_smoke --partitions 2 --n 100 --dry-run
  # smoke test: 100 messages into a 2-partition test topic
  python scripts/eval/replay_producer.py --topic perf_smoke --partitions 2 --n 100 --mode preload
  # latency run: 20 messages/second
  python scripts/eval/replay_producer.py --topic perf_p2_lat_r1 --partitions 2 --n 3000 --mode rate --rate 20
  # later, on the cluster: only the broker address changes
  python scripts/eval/replay_producer.py --brokers 10.0.0.5:9093 --topic perf_p4_r1 --partitions 4
"""
import argparse
import collections
import csv
import datetime
import json
import os
import platform
import random
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT / "src"))
DEFAULT_SOURCE = ROOT / "data" / "stream_log.csv"
REPORTS = ROOT / "reports" / "scaling"
LABELS = {"HATE", "OFFENSIVE", "Normal"}

try:
    sys.stdout.reconfigure(errors="replace")  # chat text can hold emoji the console can't print
except Exception:
    pass


def default_brokers():
    try:
        from shared_utils.config import KAFKA_BROKERS
        return KAFKA_BROKERS
    except Exception:
        return os.getenv("KAFKA_BROKERS", "127.0.0.1:9093")


# ---------------------------------------------------------------------------
# Workload
# ---------------------------------------------------------------------------
def load_day(source, date):
    """Rows of the processor's 9-column log for one day, in file order.

    Layout: timestamp,source,domain,subgenre,thread,text,label,confidence,latency
    The processor replaces commas inside the text with spaces, but the text is
    still rebuilt from the middle fields, and a row is kept only if its last
    three fields look like label/confidence/latency.
    """
    rows, skipped = [], 0
    with open(source, encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.startswith(date):
                continue
            parts = line.rstrip("\r\n").split(",")
            if len(parts) < 9 or parts[-3] not in LABELS:
                skipped += 1
                continue
            try:
                float(parts[-2]); float(parts[-1])
            except ValueError:
                skipped += 1
                continue
            text = ",".join(parts[5:-3]).strip()
            if not text:
                skipped += 1
                continue
            rows.append({"ts": parts[0], "platform": parts[1], "domain": parts[2],
                         "subgenre": parts[3], "thread": parts[4], "text": text})
    return rows, skipped


def build_workload(rows, n, seed):
    if n > len(rows):
        sys.exit(f"--n {n} is larger than the {len(rows)} usable messages for this date.")
    picked = sorted(random.Random(seed).sample(range(len(rows)), n))
    return [rows[i] for i in picked]


def make_payload(row, run_id, seq):
    """Same Universal Schema fields the live adapters send, plus the bench tags."""
    return {
        "payload_text": row["text"],
        "source_platform": row["platform"],
        "env_domain": row["domain"],
        "env_domain_raw": row["domain"],
        "env_domain_match": "replay",
        "env_subgenre": row["subgenre"],
        "env_strictness": "medium",
        "env_strictness_reasoning": "replayed benchmark workload",
        "platform_metadata": {
            "video_id": row["thread"],
            "video_title": "replay",
            "channel_name": "",
            "tweet_id": f"{run_id}-{seq}",
            "author_id": "bench",
            "author_name": "bench",
            "is_moderator": False,
            "is_sponsor": False,
        },
        "bench_run_id": run_id,
        "bench_seq": seq,
    }


def expected_partitions(n, partitions):
    """Where Kafka's default partitioner will put keys 0..n-1 (murmur2, like Java)."""
    try:
        from kafka.partitioner.default import murmur2
    except Exception:
        return None
    counts = collections.Counter((murmur2(str(s).encode()) & 0x7FFFFFFF) % partitions for s in range(n))
    return dict(sorted(counts.items()))


# ---------------------------------------------------------------------------
# Kafka
# ---------------------------------------------------------------------------
def ensure_topic(brokers, topic, partitions):
    from kafka import KafkaAdminClient
    from kafka.admin import NewTopic
    admin = KafkaAdminClient(bootstrap_servers=brokers, client_id="replay_producer")
    try:
        if topic in admin.list_topics():
            info = admin.describe_topics([topic])[0]
            have = len(info.get("partitions", []))
            if have != partitions:
                sys.exit(f"Topic {topic} already exists with {have} partition(s), not {partitions}. "
                         f"Use a new topic name for this run.")
            print(f"-> Topic {topic} exists with {have} partition(s), reusing it.")
        else:
            admin.create_topics([NewTopic(name=topic, num_partitions=partitions, replication_factor=1)])
            print(f"-> Created topic {topic} with {partitions} partition(s).")
    finally:
        admin.close()


def write_manifest(path, manifest):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def git_commit():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, timeout=10).stdout.strip() or None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Replay a fixed chat workload into a perf_* Kafka topic.")
    ap.add_argument("--topic", required=True, help="test topic, must start with perf_")
    ap.add_argument("--partitions", type=int, default=1)
    ap.add_argument("--n", type=int, default=10000, help="number of messages (W)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--date", default="2026-06-13", help="collection day to draw from")
    ap.add_argument("--source", default=str(DEFAULT_SOURCE))
    ap.add_argument("--mode", choices=["preload", "rate"], default="preload")
    ap.add_argument("--rate", type=float, default=0.0, help="messages per second (rate mode)")
    ap.add_argument("--brokers", default=default_brokers())
    ap.add_argument("--run-id", default="")
    ap.add_argument("--dry-run", action="store_true", help="build and show the workload, send nothing")
    a = ap.parse_args()

    if not a.topic.startswith("perf_"):
        sys.exit("Refusing: the topic must start with 'perf_' so the live pipeline is never touched.")
    if a.partitions < 1 or a.n < 1:
        sys.exit("--partitions and --n must be at least 1.")
    if a.mode == "rate" and a.rate <= 0:
        sys.exit("rate mode needs --rate > 0 (messages per second).")

    run_id = a.run_id or f"{datetime.datetime.now():%Y%m%d-%H%M%S}_{a.topic}"
    rows, skipped = load_day(a.source, a.date)
    work = build_workload(rows, a.n, a.seed)
    platforms = dict(collections.Counter(r["platform"] for r in work))
    print(f"-> Workload: {len(work)} messages picked from {len(rows)} usable rows on {a.date} "
          f"(skipped {skipped} malformed), seed {a.seed}")
    print(f"   platforms: {platforms} | first {work[0]['ts']} | last {work[-1]['ts']}")
    print(f"   expected messages per partition: {expected_partitions(len(work), a.partitions)}")

    if a.dry_run:
        for seq in range(min(3, len(work))):
            p = make_payload(work[seq], run_id, seq)
            p["payload_text"] = p["payload_text"][:80]
            print(json.dumps(p, ensure_ascii=False))
        print("-> Dry run: nothing sent, nothing written.")
        return

    from kafka import KafkaProducer
    from kafka.errors import NoBrokersAvailable

    out = REPORTS / run_id
    out.mkdir(parents=True, exist_ok=True)
    mpath = out / "manifest_producer.json"
    manifest = {
        "status": "running", "run_id": run_id, "started_at": datetime.datetime.now().isoformat(),
        "topic": a.topic, "partitions": a.partitions, "n": len(work), "seed": a.seed, "date": a.date,
        "mode": a.mode, "rate": a.rate if a.mode == "rate" else None, "brokers": a.brokers,
        "source": a.source, "workload_platforms": platforms,
        "host": socket.gethostname(), "git_commit": git_commit(),
        "python": platform.python_version(),
    }
    write_manifest(mpath, manifest)

    try:
        ensure_topic(a.brokers, a.topic, a.partitions)
        producer = KafkaProducer(
            bootstrap_servers=a.brokers,
            key_serializer=lambda k: str(k).encode("utf-8"),
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            acks=1,
            linger_ms=0 if a.mode == "rate" else 20,
        )
    except NoBrokersAvailable:
        manifest.update(status="failed", error=f"Kafka not reachable at {a.brokers}")
        write_manifest(mpath, manifest)
        sys.exit(f"Kafka not reachable at {a.brokers}. Start it first: docker compose up -d zookeeper kafka")

    lock = threading.Lock()
    per_partition, errors = collections.Counter(), []
    sent_file = open(out / "sent.csv", "w", newline="", encoding="utf-8", buffering=1)
    sent = csv.writer(sent_file)
    sent.writerow(["seq", "partition", "offset", "kafka_ts_ms", "t_call_ms"])

    def on_ok(seq, t_call_ms, md):
        with lock:
            per_partition[md.partition] += 1
            sent.writerow([seq, md.partition, md.offset, md.timestamp, round(t_call_ms, 3)])

    def on_err(seq, exc):
        with lock:
            errors.append(f"{seq}: {exc}")

    status, max_lag_ms = "done", 0.0
    t_start = time.perf_counter()
    try:
        for seq, row in enumerate(work):
            if a.mode == "rate":
                target = t_start + seq / a.rate
                now = time.perf_counter()
                if target > now:
                    time.sleep(target - now)
                else:
                    max_lag_ms = max(max_lag_ms, (now - target) * 1000)
            t_call_ms = time.time() * 1000
            fut = producer.send(a.topic, key=seq, value=make_payload(row, run_id, seq))
            fut.add_callback(on_ok, seq, t_call_ms)
            fut.add_errback(on_err, seq)
            if seq and seq % 1000 == 0:
                print(f"   sent {seq}/{len(work)}")
    except KeyboardInterrupt:
        status = "interrupted"
        print("\n-> Interrupted: flushing what was already sent.")
    finally:
        producer.flush()
        producer.close()
        elapsed = time.perf_counter() - t_start
        sent_file.close()
        ok = sum(per_partition.values())
        manifest.update(
            status=status if not errors else f"{status}_with_errors",
            finished_at=datetime.datetime.now().isoformat(),
            sent_ok=ok, send_errors=len(errors), first_errors=errors[:5],
            per_partition=dict(sorted(per_partition.items())),
            send_seconds=round(elapsed, 3),
            achieved_rate=round(ok / elapsed, 2) if elapsed > 0 else None,
            max_schedule_lag_ms=round(max_lag_ms, 1) if a.mode == "rate" else None,
        )
        write_manifest(mpath, manifest)
        print(f"-> {status}: {ok} acknowledged, {len(errors)} errors, {elapsed:.1f}s "
              f"({manifest['achieved_rate']} msg/s). Per partition: {manifest['per_partition']}")
        print(f"-> Saved: {mpath}")


if __name__ == "__main__":
    main()
