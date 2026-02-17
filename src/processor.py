import json
import os
import torch
import numpy as np
import pandas as pd
import datetime
from kafka import KafkaConsumer
from transformers import DistilBertTokenizer, DistilBertForSequenceClassification
from elasticsearch import Elasticsearch  

"""
Real-Time Hate Speech Detection Pipeline
Big Data Management Project -> Parsa Kazemi (560 180) - University of Messina
Model: DistilBERT (Fine-tuned on Merged Dataset -> Davidson 2017 - Hatexplain - ToxiGen)
Date: February 2026
"""

# ------------------------------------------
# CONFIGURATION
# ------------------------------------------
KAFKA_TOPICS = ['twitter_raw', 'youtube_live']
KAFKA_SERVER = '127.0.0.1:9093'
MODELS_DIR   = '../models'
LOG_FILE     = '../data/stream_log.csv'

# kibana/elasticsearch settings
ES_HOST  = "http://localhost:9200"
ES_INDEX = "real_time_analysis"

# ------------------------------------------
# 1. CONNECT TO ELASTICSEARCH (KIBANA)
# ------------------------------------------
print("---- STARTING PROCESSOR ----")
es = Elasticsearch(ES_HOST)

try:
    if es.ping():
        print(f"Connected to Kibana at {ES_HOST}")
    else:
        print(f"Could not find Elasticsearch (Dashboard will be disabled)")
except Exception as e:
    print(f"Connection Error: {e}")
    es = None

# ------------------------------------------
# 2. LOAD THE TRAINED MODEL
# ------------------------------------------
print("Loading BERT Model...")
try:
    # loading the model we saved in the previous notebook
    tokenizer = DistilBertTokenizer.from_pretrained(os.path.join(MODELS_DIR, 'bert_final'))
    model_bert = DistilBertForSequenceClassification.from_pretrained(os.path.join(MODELS_DIR, 'bert_final'))
    
    # setting to eval mode disables dropout, making predictions deterministic and faster
    model_bert.eval()
    print("BERT Model Loaded successfully.")
except Exception as e:
    print(f"Error loading model: {e}")
    # we exit because the system cannot function without the brain
    exit(1)

# ------------------------------------------
# PREDICTION FUNCTION
# ------------------------------------------
def get_bert_prediction(text):
    text = str(text)
    # tokenize the input just like we did during training
    inputs = tokenizer(text, return_tensors="pt", truncation=True, padding=True, max_length=128)
    
    with torch.no_grad():
        outputs = model_bert(**inputs)
    
    # convert raw logits to probabilities using softmax
    probs = torch.nn.functional.softmax(outputs.logits, dim=-1).numpy()[0]
    pred_label = np.argmax(probs)
    
    labels_map = {0: "HATE", 1: "OFFENSIVE", 2: "Normal"}
    
    return pred_label, labels_map[pred_label], probs

# ------------------------------------------
# KAFKA SETUP
# ------------------------------------------
# creating the listener that sits on the message bus
consumer = KafkaConsumer(
    *KAFKA_TOPICS,  # unpacks the list to listen to multiple topics
    bootstrap_servers=KAFKA_SERVER,
    auto_offset_reset='latest',  # only listen to new messages, ignore old ones
    value_deserializer=lambda x: json.loads(x.decode('utf-8'))
)

# ------------------------------------------
# LOGGING SETUP
# ------------------------------------------
# create the csv header if the file doesn't exist
if not os.path.exists(LOG_FILE):
    pd.DataFrame(columns=['timestamp','source','video_id','text','pred_label','pred_text','confidence']).to_csv(LOG_FILE, index=False)

# print a clean table header for the console output
print("-" * 100)
print(f"{'SOURCE':<10} | {'PREDICTION':<15} | {'CONFIDENCE':<10} | {'TEXT'}")
print("-" * 100)

# ------------------------------------------
# MAIN LOOP (THE PIPELINE)
# ------------------------------------------
try:
    for message in consumer:
        data = message.value
        
        # extracting fields safely
        text = data.get('text', '')
        source = data.get('source', 'Unknown')
        video_id = data.get('video_id', 'N/A')
        
        # 1. AI Processing
        label_id, label_text, probabilities = get_bert_prediction(text)
        confidence = probabilities[label_id]
        
        # 2. Console Visualization
        # simple logic to format the output for readability
        label_display = f"| [{label_text}] |"
        print(f"{source:<10} | {label_display:<25} | {confidence:.0%}       | {text[:50]}...")
        
        # 3. Dashboard Indexing (Elasticsearch)
        if es:
            doc = {
                'tweet_id': data.get('tweet_id'),
                'text': text,
                'source': source,
                'video_id': video_id,
                'prediction': int(label_id),  # 0, 1, or 2
                'label_text': label_text,     # "Hate", "Normal", "Offensive"
                'confidence': float(confidence),
                'timestamp': datetime.datetime.now().isoformat()
            }
            try:
                # sending the json document to kibana
                es.index(index=ES_INDEX, document=doc)
            except Exception as e:
                print(f"Kibana Error: {e}")

        # 4. Audit Logging (CSV)
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            clean_text = text.replace('\n', ' ').replace(',', ' ')
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # writing raw string is faster than using pandas for single rows
            f.write(f"{timestamp},{source},{video_id},{clean_text},{label_id},{label_text},{confidence:.4f}\n")

except KeyboardInterrupt:
    print("\nProcessor stopped by user.")