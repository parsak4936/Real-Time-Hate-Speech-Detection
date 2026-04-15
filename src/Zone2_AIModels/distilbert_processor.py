import json
import os
import sys
import time
import torch
import numpy as np
import pandas as pd
import datetime
from kafka import KafkaConsumer
from transformers import DistilBertTokenizer, DistilBertForSequenceClassification
from elasticsearch import Elasticsearch  

# --- PATH RESOLUTION & CONFIG IMPORT ---
# Dynamically find the src directory (ONE level up from Zone2_AIModels)
current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.abspath(os.path.join(current_dir, "../"))  # <--- Change is right here!
if src_dir not in sys.path:
    sys.path.append(src_dir)

from shared_utils.config import ES_HOST, INDEX_NAME, KAFKA_BROKERS, KAFKA_TOPICS
"""
Real-Time Hate Speech Detection Pipeline
Omni-Processor: Universal Schema & Latency Tracking
"""

# ------------------------------------------
# LOCAL CONFIGURATION
# ------------------------------------------
MODELS_DIR   = os.path.join(src_dir, '../models')
LOG_FILE     = os.path.join(src_dir, '../data/stream_log.csv')

# ------------------------------------------
# 1. CONNECT TO ELASTICSEARCH (KIBANA)
# ------------------------------------------
print("---- STARTING OMNI-PROCESSOR ----")
es = Elasticsearch(ES_HOST)

try:
    if es.ping():
        print(f"-> Connected to Kibana at {ES_HOST} | Index: {INDEX_NAME}")
    else:
        print(f"-> Could not find Elasticsearch (Dashboard will be disabled)")
        es = None
except Exception as e:
    print(f"-> Connection Error: {e}")
    es = None

# ------------------------------------------
# 2. LOAD THE TRAINED MODEL
# ------------------------------------------
print("-> Loading DistilBERT Model...")
try:
    tokenizer = DistilBertTokenizer.from_pretrained(os.path.join(MODELS_DIR, 'bert_final'))
    model_bert = DistilBertForSequenceClassification.from_pretrained(os.path.join(MODELS_DIR, 'bert_final'))
    model_bert.eval()
    print("-> BERT Model Loaded successfully.")
except Exception as e:
    print(f"-> [FATAL] Error loading model: {e}")
    exit(1)

# ------------------------------------------
# PREDICTION FUNCTION (WITH LATENCY TRACKING)
# ------------------------------------------
def get_bert_prediction(text):
    start_time = time.time()
    
    text = str(text)
    inputs = tokenizer(text, return_tensors="pt", truncation=True, padding=True, max_length=128)
    
    with torch.no_grad():
        outputs = model_bert(**inputs)
    
    probs = torch.nn.functional.softmax(outputs.logits, dim=-1).numpy()[0]
    pred_label = np.argmax(probs)
    
    calc_time_ms = (time.time() - start_time) * 1000
    labels_map = {0: "HATE", 1: "OFFENSIVE", 2: "Normal"}
    
    return pred_label, labels_map[pred_label], probs, calc_time_ms

# ------------------------------------------
# KAFKA SETUP
# ------------------------------------------
consumer = KafkaConsumer(
    *KAFKA_TOPICS,
    bootstrap_servers=KAFKA_BROKERS,
    auto_offset_reset='earliest',
    value_deserializer=lambda x: json.loads(x.decode('utf-8'))
)

# ------------------------------------------
# LOGGING SETUP
# ------------------------------------------
if not os.path.exists(LOG_FILE):
    # Updated CSV Headers to match new schema
    pd.DataFrame(columns=['timestamp', 'source_platform', 'env_domain', 'thread_id', 'text', 'model_label', 'model_confidence', 'latency_ms']).to_csv(LOG_FILE, index=False)

print("-" * 120)
print(f"{'DOMAIN':<12} | {'SOURCE':<8} | {'PREDICTION':<12} | {'CONF.':<6} | {'LATENCY':<8} | {'TEXT'}")
print("-" * 120)

# ------------------------------------------
# MAIN LOOP (THE PIPELINE)
# ------------------------------------------
try:
    for message in consumer:
        data = message.value
        
        # --- 1. EXTRACT FROM UNIVERSAL SCHEMA ---
        payload_text = data.get('payload_text', '') 
        source_platform = data.get('source_platform', 'Unknown')
        env_domain = data.get('env_domain', 'General')
        env_strictness = data.get('env_strictness', 'medium')
        
        platform_meta = data.get('platform_metadata', {})
        
        # Ensure we have a valid Thread ID regardless of platform
        thread_id = platform_meta.get('video_id') or platform_meta.get('subreddit') or "N/A"
        
        # --- 2. AI PROCESSING ---
        label_id, label_text, probabilities, latency_ms = get_bert_prediction(payload_text)
        confidence = probabilities[label_id]
        
        # --- 3. CONSOLE VISUALIZATION ---
        label_display = f"[{label_text}]"
        print(f"[{env_domain[:10].upper():<10}] | {source_platform[:8]:<8} | {label_display:<12} | {confidence:.0%}    | {latency_ms:6.1f}ms | {payload_text[:40]}...")
        
        # --- 4. DATABASE INDEXING (THE NEW SCHEMA) ---
        if es:
            doc = {
                # A. Core
                "message_id": platform_meta.get("tweet_id", "UNKNOWN"),
                "text": payload_text,
                "timestamp": datetime.datetime.now().isoformat(),
                
                # B. Context
                "source_platform": source_platform,
                "env_domain": env_domain,
                "env_strictness": env_strictness,
                "thread_id": thread_id,
                "thread_title": platform_meta.get("video_title", "Unknown"),
                "has_media": False,
                
                # C. Entity
                "author_id": platform_meta.get("author_id", "UNKNOWN"),
                "author_name": platform_meta.get("author_name", "Anonymous"),
                "is_moderator": platform_meta.get("is_moderator", False),
                "is_sponsor": platform_meta.get("is_sponsor", False),
                
                # D. Intelligence (Tier 1 - Local Model)
                "model_prediction": int(label_id),
                "model_label": label_text,
                "model_confidence": float(confidence),
                "processing_time_ms": round(latency_ms, 2),
                
                # E. Intelligence (Tier 2 - Agent Overlay)
                "agent_reviewed": False,
                "agent_model_used": None,
                "agent_final_decision": None,
                "agent_explanation": None
            }
            try:
                es.index(index=INDEX_NAME, document=doc)
            except Exception as e:
                print(f"Kibana Error: {e}")

        # --- 5. AUDIT LOGGING ---
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            clean_text = payload_text.replace('\n', ' ').replace(',', ' ')
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"{timestamp},{source_platform},{env_domain},{thread_id},{clean_text},{label_text},{confidence:.4f},{latency_ms:.2f}\n")

except KeyboardInterrupt:
    print("\nProcessor stopped safely.")