"""
Tier-1 DistilBERT Processor (the "Omni-Processor").

Consumes the Universal Schema from Kafka, runs DistilBERT inference,
writes the labeled record to Elasticsearch + a CSV audit log. Tier-2
overlay fields (agent_*) are written later by the batch judge.
"""

import csv
import datetime
import json
import os
import socket
import sys
import time

import numpy as np
import pandas as pd
import torch
from elasticsearch import Elasticsearch
from kafka import KafkaConsumer
from transformers import DistilBertForSequenceClassification, DistilBertTokenizer

# Chat text contains emoji. When output goes to a file (or a non-UTF-8 console)
# Windows falls back to cp1252 and printing one would kill the processor, so
# unprintable characters are replaced instead.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.abspath(os.path.join(current_dir, "../"))
if src_dir not in sys.path:
    sys.path.append(src_dir)

from shared_utils.config import ES_HOST, INDEX_NAME, KAFKA_BROKERS, KAFKA_TOPICS

MODELS_DIR = os.path.join(src_dir, "../models")
# Opt-in: which checkpoint to load and where to run it. Defaults reproduce the
# original behaviour exactly (the fine-tuned DistilBERT, on CPU).
MODEL_DIR = os.getenv("MODEL_DIR", os.path.join(MODELS_DIR, "bert_final"))
DEVICE = os.getenv("DEVICE", "cpu").strip().lower()
LOG_FILE = os.getenv("PROCESSOR_LOG_FILE", os.path.join(src_dir, "../data/stream_log.csv"))

# Opt-in benchmark settings for the scaling experiments. Unset = original behaviour.
GROUP_ID = os.getenv("PROCESSOR_GROUP_ID", "moderation_processor")
BENCH_LOG = os.getenv("BENCH_LOG", "")
NODE_NAME = os.getenv("NODE_NAME", socket.gethostname())

# ---------------------------------------------------------------------------
# 1. Elasticsearch
# ---------------------------------------------------------------------------
print("---- STARTING OMNI-PROCESSOR ----")
es = Elasticsearch(ES_HOST)
try:
    if es.ping():
        print(f"-> Connected to Elasticsearch at {ES_HOST} | Index: {INDEX_NAME}")
    else:
        print("-> Could not find Elasticsearch (Dashboard will be disabled)")
        es = None
except Exception as e:
    print(f"-> Connection Error: {e}")
    es = None

# ---------------------------------------------------------------------------
# 2. DistilBERT model
# ---------------------------------------------------------------------------
if DEVICE == "auto":
    DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
if DEVICE.startswith("cuda") and not torch.cuda.is_available():
    # Fail loudly: silently falling back to CPU would make the measurements a lie.
    print("-> [FATAL] DEVICE=cuda but no CUDA device is available to torch.")
    sys.exit(1)

print(f"-> Loading model from {MODEL_DIR} on {DEVICE}...")
try:
    tokenizer = DistilBertTokenizer.from_pretrained(MODEL_DIR)
    model_bert = DistilBertForSequenceClassification.from_pretrained(MODEL_DIR)
    model_bert.eval()
    model_bert.to(DEVICE)
    if DEVICE.startswith("cuda"):
        print(f"-> GPU: {torch.cuda.get_device_name(0)}")
    print("-> BERT Model Loaded successfully.")
except Exception as e:
    print(f"-> [FATAL] Error loading model: {e}")
    sys.exit(1)


def get_bert_prediction(text):
    start_time = time.time()
    text = str(text)
    inputs = tokenizer(text, return_tensors="pt", truncation=True, padding=True, max_length=128)
    if DEVICE != "cpu":
        inputs = {k: v.to(DEVICE) for k, v in inputs.items()}
    with torch.no_grad():
        outputs = model_bert(**inputs)
    if DEVICE.startswith("cuda"):
        torch.cuda.synchronize()  # GPU work is asynchronous; without this the timing would be wrong
    probs = torch.nn.functional.softmax(outputs.logits, dim=-1).cpu().numpy()[0]
    pred_label = np.argmax(probs)
    calc_time_ms = (time.time() - start_time) * 1000
    labels_map = {0: "HATE", 1: "OFFENSIVE", 2: "Normal"}
    return pred_label, labels_map[pred_label], probs, calc_time_ms


# ---------------------------------------------------------------------------
# 3. Kafka
# ---------------------------------------------------------------------------
consumer = KafkaConsumer(
    *KAFKA_TOPICS,
    bootstrap_servers=KAFKA_BROKERS,
    auto_offset_reset="earliest",
    enable_auto_commit=True,
    group_id=GROUP_ID,
    value_deserializer=lambda x: json.loads(x.decode("utf-8")),
)

# ---------------------------------------------------------------------------
# 4. CSV audit log header
# ---------------------------------------------------------------------------
if not os.path.exists(LOG_FILE):
    pd.DataFrame(
        columns=[
            "timestamp",
            "source_platform",
            "env_domain",
            "env_subgenre",
            "thread_id",
            "text",
            "model_label",
            "model_confidence",
            "latency_ms",
        ]
    ).to_csv(LOG_FILE, index=False)

# Per-message timing log, only when BENCH_LOG is set. Line-buffered, so every
# row reaches disk immediately and an interrupted run keeps everything so far.
bench_file = bench_writer = None
if BENCH_LOG:
    new_file = not os.path.exists(BENCH_LOG)
    bench_file = open(BENCH_LOG, "a", newline="", encoding="utf-8", buffering=1)
    bench_writer = csv.writer(bench_file)
    if new_file:
        bench_writer.writerow([
            "node", "pid", "run_id", "seq", "topic", "partition", "offset",
            "kafka_ts_ms", "kafka_ts_type", "t_recv_ms", "infer_ms", "es_ms",
            "t_done_ms", "label", "confidence",
        ])
    print(f"-> Benchmark log: {BENCH_LOG} | node {NODE_NAME} | group {GROUP_ID}")

print("-" * 120)
print(f"{'DOMAIN':<12} | {'SOURCE':<8} | {'PREDICTION':<12} | {'CONF.':<6} | {'LATENCY':<8} | {'TEXT'}")
print("-" * 120)

# ---------------------------------------------------------------------------
# 5. Main loop
# ---------------------------------------------------------------------------
try:
    for message in consumer:
        t_recv_ms = time.time() * 1000
        data = message.value

        payload_text = data.get("payload_text", "")
        source_platform = data.get("source_platform", "Unknown")
        env_domain = data.get("env_domain", "General")
        env_domain_raw = data.get("env_domain_raw", "") or ""
        env_domain_match = data.get("env_domain_match", "unknown")
        env_subgenre = data.get("env_subgenre", "") or ""
        env_strictness = data.get("env_strictness", "medium")
        env_strictness_reasoning = data.get("env_strictness_reasoning", "") or ""

        platform_meta = data.get("platform_metadata", {})
        thread_id = platform_meta.get("video_id") or platform_meta.get("subreddit") or "N/A"

        label_id, label_text, probabilities, latency_ms = get_bert_prediction(payload_text)
        confidence = probabilities[label_id]

        domain_display = f"{env_domain}/{env_subgenre}" if env_subgenre else env_domain
        label_display = f"[{label_text}]"
        print(
            f"[{domain_display[:10].upper():<10}] | {source_platform[:8]:<8} | "
            f"{label_display:<12} | {confidence:.0%}    | {latency_ms:6.1f}ms | "
            f"{payload_text[:40]}..."
        )

        es_ms = 0.0
        if es:
            doc = {
                "message_id": platform_meta.get("tweet_id", "UNKNOWN"),
                "text": payload_text,
                "timestamp": datetime.datetime.now().isoformat(),

                "source_platform": source_platform,
                "env_domain": env_domain,
                "env_domain_raw": env_domain_raw,
                "env_domain_match": env_domain_match,
                "env_subgenre": env_subgenre,
                "env_strictness": env_strictness,
                "env_strictness_reasoning": env_strictness_reasoning,
                "thread_id": thread_id,
                "thread_title": platform_meta.get("video_title", "Unknown"),
                "has_media": False,

                "author_id": platform_meta.get("author_id", "UNKNOWN"),
                "author_name": platform_meta.get("author_name", "Anonymous"),
                "is_moderator": platform_meta.get("is_moderator", False),
                "is_sponsor": platform_meta.get("is_sponsor", False),

                "model_prediction": int(label_id),
                "model_label": label_text,
                "model_confidence": float(confidence),
                "processing_time_ms": round(latency_ms, 2),

                "agent_reviewed": False,
                "agent_model_used": None,
                "agent_final_decision": None,
                "agent_explanation": None,
            }
            t_es = time.time()
            try:
                es.index(index=INDEX_NAME, document=doc)
            except Exception as e:
                print(f"Kibana Error: {e}")
            es_ms = (time.time() - t_es) * 1000

        if bench_writer:
            t_done_ms = time.time() * 1000
            bench_writer.writerow([
                NODE_NAME, os.getpid(), data.get("bench_run_id", ""), data.get("bench_seq", ""),
                message.topic, message.partition, message.offset,
                message.timestamp, message.timestamp_type,
                round(t_recv_ms, 3), round(latency_ms, 3), round(es_ms, 3), round(t_done_ms, 3),
                label_text, round(float(confidence), 4),
            ])

        with open(LOG_FILE, "a", encoding="utf-8") as f:
            clean_text = payload_text.replace("\n", " ").replace(",", " ")
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(
                f"{timestamp},{source_platform},{env_domain},{env_subgenre},"
                f"{thread_id},{clean_text},{label_text},{confidence:.4f},{latency_ms:.2f}\n"
            )

except KeyboardInterrupt:
    print("\nProcessor stopped safely.")
finally:
    if bench_file:
        bench_file.close()
