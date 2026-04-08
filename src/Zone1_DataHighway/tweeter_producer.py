import pandas as pd
from kafka import KafkaProducer
import json
import time
import os

"""
Twitter Stream Simulator
Description: 
    Reads the static CSV dataset and "replays" it as a live stream 
    into the Kafka topic 'twitter_raw'.
"""

# ------------------------------------------
# CONFIGURATION
# ------------------------------------------
DATA_FILE    = r"../../data/Final_Mega_Dataset.csv"
BOOKMARK_FILE = 'bookmark.txt' # prevents duplicate data on restart
KAFKA_TOPIC  = 'twitter_raw'
KAFKA_SERVER = '127.0.0.1:9093'
SPEED        = 0.2             # delay in seconds (lower = faster stream)

# ------------------------------------------
# BOOKMARK SYSTEM
# ------------------------------------------
def get_last_position():
    """Reads the last sent index from disk to resume streaming."""
    if os.path.exists(BOOKMARK_FILE):
        try:
            with open(BOOKMARK_FILE, "r") as f:
                return int(f.read().strip())
        except ValueError:
            return -1
    return -1

def save_position(index):
    """Saves the current index to disk."""
    with open(BOOKMARK_FILE, "w") as f:
        f.write(str(index))

# ------------------------------------------
# KAFKA CONNECTION
# ------------------------------------------
print("Connecting to Kafka...")
try:
    producer = KafkaProducer(
        bootstrap_servers=KAFKA_SERVER,
        value_serializer=lambda v: json.dumps(v).encode('utf-8')
    )
    print("Connected successfully.")
except Exception as e:
    print(f"Connection Error: {e}")
    exit(1)

# ------------------------------------------
# DATA LOADING & NORMALIZATION
# ------------------------------------------
if not os.path.exists(DATA_FILE):
    print(f"Error: File not found: {DATA_FILE}")
    print(DATA_FILE)
    exit(1)

print(f"Loading dataset: {DATA_FILE}...")
df = pd.read_csv(DATA_FILE)

# smart column detection: handling different naming conventions
# this ensures the script works whether the column is called 'tweet' or 'text'
if 'tweet' in df.columns:
    df.rename(columns={'tweet': 'text'}, inplace=True)
elif 'text' in df.columns:
    pass
else:
    print(f"Error: Could not find text column. Found: {df.columns.tolist()}")
    exit(1)

# normalizing the label column
if 'class' in df.columns:
    df.rename(columns={'class': 'label'}, inplace=True)
elif 'manual_label' in df.columns:
    df.rename(columns={'manual_label': 'label'}, inplace=True)

# data cleaning: ensure labels are integers and remove empty rows
df = df.dropna(subset=['label'])
df['label'] = df['label'].astype(int)

total_rows = len(df)
print(f"Dataset loaded. Total tweets to stream: {total_rows}")

# ------------------------------------------
# STREAMING LOOP
# ------------------------------------------
start_index = get_last_position()
print(f"Resuming stream from index {start_index}...")
print(f"Target Topic: '{KAFKA_TOPIC}'")

try:
    for index, row in df.iterrows():
        # skip rows we have already sent
        if index <= start_index:
            continue

        # construct the message packet
        message = {
            'tweet_id': str(index),
            'text': str(row['text']),      
            'label': int(row['label']), # sending the ground truth for debugging
            'source': 'Twitter',
            'video_id': 'N/A'
        }

        # send to kafka
        producer.send(KAFKA_TOPIC, message)
        
        # save progress
        save_position(index)

        # print status every 100 messages to avoid cluttering the console
        if index % 100 == 0:
            print(f"[Twitter Stream] Sent: {str(row['text'])[:40]}...")
        
        # artificial delay to mimic real-time traffic
        time.sleep(SPEED)

except KeyboardInterrupt:
    print("\nStream stopped by user.")