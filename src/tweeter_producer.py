import pandas as pd
from kafka import KafkaProducer
import json
import time
import os

DATA_FILE = '../data/Final_Mega_Dataset.csv'  
BOOKMARK_FILE = 'bookmark.txt'#to not create duplicate data from labeled data (merged file)
KAFKA_TOPIC = 'twitter_raw'
KAFKA_SERVER = '127.0.0.1:9093'
SPEED = 0.2
# ---------------------

def get_start_index():
    if os.path.exists(BOOKMARK_FILE):
        try:
            with open(BOOKMARK_FILE, "r") as f:
                return int(f.read().strip())
        except ValueError:
            return -1
    return -1

def save_bookmark(index):
    with open(BOOKMARK_FILE, "w") as f:
        f.write(str(index))

#Setup Kafka
print("Connecting to Kafka....")
try:
    producer = KafkaProducer(
        bootstrap_servers=KAFKA_SERVER,
        value_serializer=lambda v: json.dumps(v).encode('utf-8')
    )
    print("Connected.")
except Exception as e:
    print(f"ERROR : {e}")
    exit(1)

#Load and Inspect Data
if not os.path.exists(DATA_FILE):
    print(f"ERROR: File not found: {DATA_FILE}")
    exit(1)

print(f"Loading dataset: {DATA_FILE}...")
df = pd.read_csv(DATA_FILE)

# --- SMART COLUMN DETECTION (The Fix) ---
#  normalizing the column names so the code never crashes.
if 'tweet' in df.columns:
    df.rename(columns={'tweet': 'text'}, inplace=True)
elif 'text' in df.columns:
    pass
else:
    #Your CSV must have a column named 'tweet' or 'text'
    print(f"Found columns: {df.columns.tolist()}")
    exit(1)

#find the Label Column
if 'class' in df.columns:
    df.rename(columns={'class': 'label'}, inplace=True)
elif 'label' in df.columns:
    pass 
elif 'manual_label' in df.columns:
    df.rename(columns={'manual_label': 'label'}, inplace=True)
else:
    print("ERROR: data must have a column named 'class', 'label', or 'manual_label'.")
    exit(1)

#  labels should be integer
df = df.dropna(subset=['label'])
df['label'] = df['label'].astype(int)

total_rows = len(df)
print(f"dataset loaded and fixed. Columns: {df.columns.tolist()}")
print(f"Total Tweets: {total_rows}")

# Stream 
start_index = get_start_index()
print(f"Streaming to '{KAFKA_TOPIC}'...")

try:
    for index, row in df.iterrows():
        if index <= start_index:
            continue

        message = {
            'tweet_id': index,
            'text': row['text'],      
            'label': int(row['label']),
            'source': 'Twitter',
            'video_id': 'N/A'
        }

        producer.send(KAFKA_TOPIC, message)
        save_bookmark(index)

        if index % 100 == 0:
            print(f"[Twitter] Sent: {str(row['text'])[:40]}...")
        
        time.sleep(SPEED)

except KeyboardInterrupt:
    print("\nStream stopped.")