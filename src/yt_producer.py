import pytchat
import time
from kafka import KafkaProducer
import json
import sys

KAFKA_TOPIC = 'youtube_live' 
KAFKA_SERVER = '127.0.0.1:9093'
# ---------------------

def extract_video_id(url_or_id):
    # clear the link to get just the ID (e.g., "mAoDkS1ZBw0")
    if "v=" in url_or_id:
        return url_or_id.split("v=")[1].split("&")[0]
    elif "youtu.be/" in url_or_id:
        return url_or_id.split("youtu.be/")[1].split("?")[0]
    else:
        return url_or_id
# -------------------------

def start_yt_stream():
    print("Paste the YouTube Link :")
    raw_input = input("Link:").strip()
    
    if not raw_input:
        video_id = "mAoDkS1ZBw0" # Default Dota 2 stream 
    else:
        video_id = extract_video_id(raw_input)

    print(f"Target Video ID: {video_id}")

    #Connect to Kafka
    try:
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_SERVER,
            value_serializer=lambda v: json.dumps(v).encode('utf-8')
        )
        print("Connected to Kafka.")
    except Exception as e:
        print(f"ERROR : {e}")
        return
    

    #Connect to YT
    try:
        chat = pytchat.create(video_id=video_id)
        print(f"----- CONNECTED TO YOUTUBE ----")
        print("Waiting for messages...")

        while chat.is_alive():
            for c in chat.get().sync_items():
                
                message = {
                    'tweet_id': int(time.time() * 1000),
                    'text': c.message,
                    'label': 2,           # 2 = Neutral 
                    'source': 'YouTube',
                    'video_id': video_id  # to seperate diffeent videos
                }
                
                producer.send(KAFKA_TOPIC, message)
                print(f"[YouTube] {c.author.name}: {c.message}")
            
            time.sleep(0.5) 

    except KeyboardInterrupt:
        print("\nStopped.")
    except Exception as e:
        print(f"Connection Lost: {e}")

if __name__ == "__main__":
    start_yt_stream()