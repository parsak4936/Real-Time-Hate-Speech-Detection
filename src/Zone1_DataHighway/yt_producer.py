import pytchat
import time
from kafka import KafkaProducer
import json
import sys
import re
"""
YouTube Live Stream Ingestion
Description: 
    Connects to a live YouTube video and forwards the chat messages 
    to the Kafka topic 'youtube_live' in real-time.
"""

# ------------------------------------------
# CONFIGURATION
# ------------------------------------------
KAFKA_TOPIC  = 'youtube_live' 
KAFKA_SERVER = '127.0.0.1:9093'

# ------------------------------------------
# UTILITY: EXTRACT VIDEO ID
# ------------------------------------------
def extract_video_id(url_or_id):
    """
    Parses various YouTube URL formats to find the unique Video ID.
    Supports:
    - Standard: https://www.youtube.com/watch?v=VIDEO_ID
    - Short: https://youtu.be/VIDEO_ID
    - Raw ID: VIDEO_ID
    """
    url_or_id = str(url_or_id).strip()
    
    if "v=" in url_or_id:
        return url_or_id.split("v=")[1].split("&")[0]
    elif "youtu.be/" in url_or_id:
        return url_or_id.split("youtu.be/")[1].split("?")[0]
    else:
        return url_or_id




# ------------------------------------------
# MAIN STREAMING FUNCTION
# ------------------------------------------
def start_yt_stream():
    print("----- YouTube Live Stream Setup -----")
    print("Paste the YouTube Link (or press Enter for default):")
    input_url = input("Link: ").strip()
    
    if not input_url:
        # default to 'Lofi Girl' or a similar 24/7 stream for testing
        video_id = "mAoDkS1ZBw0" 
        print("No link provided. Using default stream (Lofi Girl).")
    else:
        video_id = extract_video_id(input_url)

    print(f"Target Video ID: {video_id}")

    # 1. Connect to Kafka
    try:
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_SERVER,
            value_serializer=lambda v: json.dumps(v).encode('utf-8')
        )
        print("Connected to Kafka Message Bus.")
    except Exception as e:
        print(f"Kafka Connection Error: {e}")
        return

    # 2. Connect to YouTube Chat
    try:
        chat = pytchat.create(video_id=video_id)
        print(f"----- CONNECTED TO YOUTUBE CHAT -----")
        print("Listening for messages...")

        while chat.is_alive():
            for c in chat.get().sync_items():
                
                # construct the standard data packet
              # construct the standard data packet
                message = {
                    'tweet_id': str(c.id),                    # Official YouTube Unique ID
                    'text': c.message,
                    'label': 2,                           # default to 'Neutral' (2)
                    'source': 'YouTube',
                    'video_id': video_id,
                    
                    # --- NEW ENTITY TRACKING FIELDS ---
                    'author_id': c.author.channelId,      # The permanent user ID
                    'author_name': c.author.name,
                    'is_moderator': c.author.isChatModerator,
                    'is_sponsor': c.author.isChatSponsor
                }
                
                # send to kafka
                producer.send(KAFKA_TOPIC, message)
                
                # print to console for verification
                print(f"[YouTube] {c.author.name}: {c.message}")
            
            # slight delay to prevent cpu spiking
            time.sleep(0.5) 

    except KeyboardInterrupt:
        print("\nStream stopped by user.")
    except Exception as e:
        print(f"Connection Lost: {e}")

if __name__ == "__main__":
    start_yt_stream()