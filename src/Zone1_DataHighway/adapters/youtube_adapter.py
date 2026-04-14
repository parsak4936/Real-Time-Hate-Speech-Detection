"""
Module: YouTube Live Stream Adapter
Architecture: Dumb Data Fetcher (Phase 1 of Omni-Pipeline)
Description: 
    Connects to a live YouTube video, scrapes raw pre-stream metadata (Title, 
    Channel, Description), requests context resolution from the central XAI Agent, 
    and forwards formatted chat messages to the Kafka message bus.
"""

import pytchat
import time
import json
import urllib.request
import re
from kafka import KafkaProducer

# Import the centralized AI brain (We will build this file next)
from adapters.context_agent import resolve_environment

# ------------------------------------------
# CONFIGURATION
# ------------------------------------------
KAFKA_TOPIC  = 'universal_stream'  
KAFKA_SERVER = '127.0.0.1:9093'

# ------------------------------------------
# UTILITY: METADATA EXTRACTION
# ------------------------------------------
def extract_video_id(url_or_id):
    """Parses standard and shortened YouTube URLs into a raw Video ID."""
    url_or_id = str(url_or_id).strip()
    if "v=" in url_or_id: return url_or_id.split("v=")[1].split("&")[0]
    elif "youtu.be/" in url_or_id: return url_or_id.split("youtu.be/")[1].split("?")[0]
    return url_or_id
def fetch_youtube_metadata(video_id):
    """
    Scrapes the YouTube page HTML to extract static metadata.
    Now includes a Live Broadcast detector.
    """
    print(f"-> [YouTube Adapter] Scraping metadata for ID: {video_id}...")
    url = f"https://www.youtube.com/watch?v={video_id}"
    
    metadata = {
        "title": "Unknown Title",
        "channel_name": "Unknown Channel",
        "description": "No description available.",
        "is_live": False  # <--- NEW FLAG
    }
    
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        html = urllib.request.urlopen(req, timeout=5).read().decode('utf-8')
        
        # --- NEW: Check if the stream is currently LIVE ---
        if '"isLiveNow":true' in html or 'itemprop="isLiveBroadcast"' in html:
            metadata["is_live"] = True

        # Extract Title
        title_match = re.search(r'<title>(.*?)</title>', html)
        if title_match:
            metadata["title"] = title_match.group(1).replace(" - YouTube", "").strip()
            
        # Extract Channel Name
        channel_match = re.search(r'<link itemprop="name" content="(.*?)">', html)
        if channel_match:
            metadata["channel_name"] = channel_match.group(1).strip()
            
        # Extract Description
        desc_match = re.search(r'<meta name="description" content="(.*?)">', html)
        if desc_match:
            metadata["description"] = desc_match.group(1)[:200].strip() + "..."
            
    except Exception as e:
        print(f"-> [YouTube Adapter] Metadata Warning: {e}")
        
    return metadata
# ------------------------------------------
# MAIN PIPELINE
# ------------------------------------------
def start_youtube_pipeline(url):
    video_id = extract_video_id(url)
    
    # 1. Scrape Raw Metadata
    raw_meta = fetch_youtube_metadata(video_id)
    
    print("\n--- EXTRACTED RAW METADATA ---")
    print(f"Title:   {raw_meta['title']}")
    print(f"Channel: {raw_meta['channel_name']}")
    print(f"Is Live: {raw_meta['is_live']}") # <--- Print the status
    print("------------------------------")

    # --- NEW: HARD STOP FOR OFFLINE VIDEOS ---
    if not raw_meta['is_live']:
        print("\n[BLOCKED] This video is NOT currently live.")
        print("-> Your pipeline requires an active, real-time data stream.")
        print("-> Please go to YouTube, click the 'Live' tab, and provide a valid link.")
        return  # This stops the script right here.

    # 2. Delegate to Context Agent (The Brain)
    print("\n-> [YouTube Adapter] Requesting Context Resolution from XAI Agent...")
    domain_context, strictness = resolve_environment("YouTube", raw_meta)
    
    # ... [The rest of the script continues as normal] ... 
    print(f"-> [YouTube Adapter] Context Locked: [{domain_context.upper()}] | Strictness: [{strictness.upper()}]")

    # 3. Connect to Kafka
    try:
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_SERVER,
            value_serializer=lambda v: json.dumps(v).encode('utf-8')
        )
    except Exception as e:
        print(f"-> [Kafka Error] Could not connect to message bus: {e}")
        return

# 4. Stream Data using Universal Schema
    try:
        chat = pytchat.create(video_id=video_id)
        
        # --- NEW: CONNECTION BUFFER ---
        # Give the socket 2 seconds to establish a secure connection
        time.sleep(2)
        
        # --- NEW: THE MISSING HEALTH CHECK ---
        if not chat.is_alive():
            print("\n[WARNING] Chat connection failed immediately.")
            print("-> Reason A: The creator has disabled the Live Chat.")
            print("-> Reason B: The chat is restricted (Members Only / Age-Restricted).")
            print("-> Action: Try a different live stream with a public chat.")
            return

        print(f"\n----- LIVE STREAM ACTIVE -----")
        
        empty_loops = 0  # <--- NEW: Heartbeat counter

        while chat.is_alive():
            items = chat.get().sync_items()
            
            if items:
                empty_loops = 0  # Reset counter when someone talks
                for c in items:
                    
                    # UNIVERSAL SCHEMA ENFORCEMENT
                    message = {
                        "payload_text": c.message,
                        "source_platform": "YouTube",
                        "env_domain": domain_context,
                        "env_strictness": strictness,
                        "platform_metadata": {
                            "video_id": video_id,
                            "video_title": raw_meta["title"],
                            "channel_name": raw_meta["channel_name"],
                            "tweet_id": str(c.id),
                            "author_id": c.author.channelId,
                            "author_name": c.author.name,
                            "is_moderator": c.author.isChatModerator,
                            "is_sponsor": c.author.isChatSponsor
                        }
                    }
                    
                    producer.send(KAFKA_TOPIC, message)
                    print(f"[{domain_context.upper()}] {c.author.name}: {c.message}")
            else:
                # --- NEW: THE HEARTBEAT ---
                empty_loops += 1
                if empty_loops % 10 == 0:  # Prints roughly every 5 seconds
                    print(f"[{domain_context.upper()}] ... [Waiting for chat messages] ...")
                    
            time.sleep(0.5)
                
 
    except KeyboardInterrupt:
        print("\n-> [YouTube Adapter] Stream safely terminated.")
    except Exception as e:
        print(f"-> [YouTube Adapter] Stream Error: {e}")

if __name__ == "__main__":
    print("Run this adapter via omni_ingest.py, not directly.")