import sys
import os

# Ensure Python can find your adapter files
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from adapters.youtube_adapter import start_youtube_pipeline
# from adapters.reddit_adapter import start_reddit_pipeline  # (For later)

def route_input():
    print("\n" + "="*60)
    print(" OMNI-INGESTION ROUTER: AWAITING DATA SOURCE")
    print("="*60)
    
    user_input = input("Paste a Link (YouTube, Reddit) or File Path: ").strip()
    
    # 1. Fallback for quick testing
    if not user_input:
        print("\n-> [Router] No input detected. Defaulting to Dota 2 test stream.")
        # We use a Dota 2 or Gaming stream ID here to test your "Nigma" theory!
        # You can replace this ID with a live gaming stream ID when you test.
        start_youtube_pipeline("mAoDkS1ZBw0") 
        return

    # 2. Route to YouTube
    if "youtube.com" in user_input or "youtu.be" in user_input:
        print("\n-> [Router] YouTube URL detected. Handing off to YouTube Adapter...")
        start_youtube_pipeline(user_input)
        
    # 3. Route to Reddit (Future)
    elif "reddit.com" in user_input:
        print("\n-> [Router] Reddit URL detected. (Adapter pending).")
        # start_reddit_pipeline(user_input)
        
    # 4. Route to Medical / Local Datasets (Future)
    elif user_input.endswith(".csv") or user_input.endswith(".dcm"):
        print("\n-> [Router] Static Dataset detected. (Adapter pending).")
        
    else:
        print("\n-> [Router] Error: Unknown data source. Cannot route.")

if __name__ == "__main__":
    try:
        route_input()
    except KeyboardInterrupt:
        print("\n[Router] Shutting down safely. Goodbye.")