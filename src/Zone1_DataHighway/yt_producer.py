import pytchat
import time
import json
from kafka import KafkaProducer

"""
Intelligent YouTube Live Stream Producer
Description: 
    Connects to a live YouTube video, automatically resolves the context/environment,
    and forwards the chat messages to Kafka using the Universal Schema.
"""

# ------------------------------------------
# CONFIGURATION
# ------------------------------------------
KAFKA_TOPIC  = 'universal_stream'  # Updated to reflect the new modular architecture
KAFKA_SERVER = '127.0.0.1:9093'

# ------------------------------------------
# UTILITY FUNCTIONS
# ------------------------------------------
def extract_video_id(url_or_id):
    """Parses various YouTube URL formats to find the unique Video ID."""
    url_or_id = str(url_or_id).strip()
    if "v=" in url_or_id:
        return url_or_id.split("v=")[1].split("&")[0]
    elif "youtu.be/" in url_or_id:
        return url_or_id.split("youtu.be/")[1].split("?")[0]
    return url_or_id

def auto_resolve_context(video_id):
    """
    THE INTELLIGENCE LAYER:
    In a full production environment, this would ping the official YouTube Data API 
    to get the 'categoryId'. For now, it uses a simulation dictionary to map 
    known videos to their environmental context.
    """
    print(f"-> [Auto-Resolver] Analyzing metadata for video: {video_id}...")
    
    # Simulating YouTube API responses
    mock_api_database = {
        "mAoDkS1ZBw0": {"category": "Music", "title": "Lofi Girl"},
        "gaming123": {"category": "Gaming", "title": "Dota 2 Finals Live"},
        "news456": {"category": "Politics", "title": "Live News Debate"}
    }
    
    metadata = mock_api_database.get(video_id, {"category": "General", "title": "Unknown Stream"})
    category = metadata["category"]
    
    # Map the API Category to your strictness rules
    if category == "Gaming":
        return "Gaming", "low"
    elif category in ["Politics", "News"]:
        return "Politics", "high"
    else:
        return category, "medium"

# ------------------------------------------
# MAIN STREAMING FUNCTION
# ------------------------------------------
def start_yt_stream():
    print("=====================================================")
    print(" INTELLIGENT YOUTUBE PRODUCER BOOTING...")
    print("=====================================================")
    
    input_url = input("Paste the YouTube Link (or press Enter for default): ").strip()
    
    if not input_url:
        video_id = "mAoDkS1ZBw0" 
        print("No link provided. Using default stream (Lofi Girl).")
    else:
        video_id = extract_video_id(input_url)

    print(f"Target Video ID: {video_id}")
    
    # 1. Automatically figure out the environment
    domain_context, strictness = auto_resolve_context(video_id)
    print(f"-> Context Locked: [{domain_context.upper()}] | Strictness: [{strictness.upper()}]")

    # 2. Connect to Kafka Message Bus
    try:
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_SERVER,
            value_serializer=lambda v: json.dumps(v).encode('utf-8')
        )
        print("-> Connected to Kafka Message Bus.")
    except Exception as e:
        print(f"Kafka Connection Error: {e}")
        return

    # 3. Connect to YouTube Chat and Stream
    try:
        chat = pytchat.create(video_id=video_id)
        print(f"\n----- LIVE STREAM ACTIVE -----")

        while chat.is_alive():
            for c in chat.get().sync_items():
                
                # THE UNIVERSAL SCHEMA
                # This guarantees that the processor and database NEVER crash,
                # no matter what platform we add later.
                message = {
                    "payload_text": c.message,
                    "source_platform": "YouTube",
                    
                    # The Environment Block (For the LLM Judge later)
                    "env_domain": domain_context,
                    "env_strictness": strictness,
                    
                    # Platform-Specific Metadata (Safely nested)
                    "platform_metadata": {
                        "video_id": video_id,
                        "tweet_id": str(c.id),
                        "author_id": c.author.channelId,
                        "author_name": c.author.name,
                        "is_moderator": c.author.isChatModerator,
                        "is_sponsor": c.author.isChatSponsor
                    }
                }
                
                # Send to Kafka
                producer.send(KAFKA_TOPIC, message)
                
                # Print to console for verification
                print(f"[{domain_context.upper()}] {c.author.name}: {c.message}")
            
            time.sleep(0.5) 

    except KeyboardInterrupt:
        print("\nStream stopped by user.")
    except Exception as e:
        print(f"Connection Lost: {e}")

if __name__ == "__main__":
    start_yt_stream()