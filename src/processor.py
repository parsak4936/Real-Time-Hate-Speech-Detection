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
Model: DistilBERT (Fine-tuned on Merged Dataset -> Davidson 2017- Hatexplain - ToxiGen)
Date: February 2026
Description: 
    This script consumes live stream data from Kafka, processes it using 
    a DistilBERT model, and indexes the results to Elasticsearch.
"""
# --- CONFIGURATION ---
KAFKA_TOPICS = ['twitter_raw', 'youtube_live']
KAFKA_SERVER = '127.0.0.1:9093'
MODELS_DIR = '../models'
LOG_FILE = '../data/stream_log.csv'
ES_HOST = "http://localhost:9200"      #Kibana address
ES_INDEX = "real_time_analysis"
# ---------------------

# 1. connect to kibana 
print("---- STARTING PROCESSOR-----")
es = Elasticsearch(ES_HOST)
try:
    if es.ping():
        print(f"Connected to Kibana at {ES_HOST}")
    else:
        print(f"Could not find Elasticsearch")
except Exception as e:
    print(f"Connection Error: {e}")
    es = None

# 2.loading the model ( here we can use any other models we prefer! )
print("Loading BERT Model : ")
try:
    tokenizer = DistilBertTokenizer.from_pretrained(os.path.join(MODELS_DIR, 'bert_final'))
    model_bert = DistilBertForSequenceClassification.from_pretrained(os.path.join(MODELS_DIR, 'bert_final'))
    model_bert.eval()
    print("BERT Model Loaded.")
except Exception as e:
    print(f"Error loading model: {e}")
    exit(1)

#  predictoin 
def get_bert_prediction(text):
    text = str(text)
    inputs = tokenizer(text, return_tensors="pt", truncation=True, padding=True, max_length=128)
    with torch.no_grad():
        outputs = model_bert(**inputs)
    probs = torch.nn.functional.softmax(outputs.logits, dim=-1).numpy()[0]
    pred_label = np.argmax(probs)
    labels_map = {0: "HATE", 1: "OFFENSIVE", 2: "Normal"}
    return pred_label, labels_map[pred_label], probs

#  Kkafka setup
consumer = KafkaConsumer(
    *KAFKA_TOPICS,  #listen to all topics
    bootstrap_servers=KAFKA_SERVER,
    auto_offset_reset='latest',
    value_deserializer=lambda x: json.loads(x.decode('utf-8'))
)

#  log file for later use
if not os.path.exists(LOG_FILE):
    pd.DataFrame(columns=['timestamp','source','video_id','text','pred_label','pred_text','confidence']).to_csv(LOG_FILE, index=False)

print("-" * 100)
print(f"{'SOURCE':<10} | {'PREDICTION':<15} | {'CONFIDENCE':<10} | {'TEXT'}")
print("-" * 100)


try:
    for message in consumer:
        data = message.value
        text = data.get('text', '')
        source = data.get('source', 'Unknown')
        video_id = data.get('video_id', 'N/A')
        
        label_id, label_text, probabilities = get_bert_prediction(text)
        confidence = probabilities[label_id]
        
        if label_id == 0:
            label_display = f" | [{label_text} ] | "
        elif label_id == 1:
            label_display = f"| [{label_text} ] |"
        else:
            label_display = f"| [{label_text}] | "
        print(f"{source:<10} | {label_display:<25} | {confidence:.0%}       | {text[:50]}...")
        
        if es:
            doc = {
                'tweet_id': data.get('tweet_id'),
                'text': text,
                'source': source,
                'video_id': video_id,
                'prediction': int(label_id),  # 0, 1, or 2
                'label_text': label_text,     # "Hate", "Normal" , "Offensive"
                'confidence': float(confidence),
                'timestamp': datetime.datetime.now().isoformat()
            }
            try:
                es.index(index=ES_INDEX, document=doc)
            except Exception as e:
                print(f"Kibana Error: {e}")

        # save to csv
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            clean_text = text.replace('\n', ' ').replace(',', ' ')
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"{timestamp},{source},{video_id},{clean_text},{label_id},{label_text},{confidence:.4f}\n")

except KeyboardInterrupt:
    print("\nProcessor stopped.")