"""
YouTube Live Stream Adapter — Phase 1 of the Omni-Pipeline.

Scrapes pre-stream HTML metadata (title, channel, description, live state),
hands it to the Context Agent to resolve env_domain / env_subgenre /
env_strictness, then forwards live-chat messages to Kafka under the
Universal Schema.

This adapter is intentionally a "dumb fetcher" — every intelligence step
(domain classification, judge) lives downstream.
"""

import json
import re
import time
import urllib.request

import pytchat
from kafka import KafkaProducer

from adapters.context_agent import resolve_environment

KAFKA_TOPIC = "universal_stream"
KAFKA_SERVER = "127.0.0.1:9093"


def extract_video_id(url_or_id):
    url_or_id = str(url_or_id).strip()
    if "v=" in url_or_id:
        return url_or_id.split("v=")[1].split("&")[0]
    if "youtu.be/" in url_or_id:
        return url_or_id.split("youtu.be/")[1].split("?")[0]
    return url_or_id


def fetch_youtube_metadata(video_id):
    """Scrape the public watch-page HTML for title, channel, description, live flag."""
    print(f"-> [YouTube Adapter] Scraping metadata for ID: {video_id}...")
    url = f"https://www.youtube.com/watch?v={video_id}"

    metadata = {
        "title": "Unknown Title",
        "channel_name": "Unknown Channel",
        "description": "No description available.",
        "is_live": False,
    }

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        html = urllib.request.urlopen(req, timeout=5).read().decode("utf-8")

        if '"isLiveNow":true' in html or 'itemprop="isLiveBroadcast"' in html:
            metadata["is_live"] = True

        title_match = re.search(r"<title>(.*?)</title>", html)
        if title_match:
            metadata["title"] = title_match.group(1).replace(" - YouTube", "").strip()

        channel_match = re.search(r'<link itemprop="name" content="(.*?)">', html)
        if channel_match:
            metadata["channel_name"] = channel_match.group(1).strip()

        desc_match = re.search(r'<meta name="description" content="(.*?)">', html)
        if desc_match:
            metadata["description"] = desc_match.group(1)[:200].strip() + "..."

    except Exception as e:
        print(f"-> [YouTube Adapter] Metadata Warning: {e}")

    return metadata


def start_youtube_pipeline(url):
    video_id = extract_video_id(url)
    raw_meta = fetch_youtube_metadata(video_id)

    print("\n--- EXTRACTED RAW METADATA ---")
    print(f"Title:   {raw_meta['title']}")
    print(f"Channel: {raw_meta['channel_name']}")
    print(f"Is Live: {raw_meta['is_live']}")
    print("------------------------------")

    if not raw_meta["is_live"]:
        print("\n[BLOCKED] This video is NOT currently live.")
        print("-> Your pipeline requires an active, real-time data stream.")
        print("-> Please go to YouTube, click the 'Live' tab, and provide a valid link.")
        return

    print("\n-> [YouTube Adapter] Requesting Context Resolution from XAI Agent...")
    domain_context, strictness, subgenre = resolve_environment("YouTube", raw_meta)

    subgenre_display = f"/{subgenre}" if subgenre else ""
    print(
        f"-> [YouTube Adapter] Context Locked: "
        f"[{domain_context.upper()}{subgenre_display}] | Strictness: [{strictness.upper()}]"
    )

    try:
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_SERVER,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
    except Exception as e:
        print(f"-> [Kafka Error] Could not connect to message bus: {e}")
        return

    try:
        chat = pytchat.create(video_id=video_id)
        time.sleep(2)  # give the socket time to connect

        if not chat.is_alive():
            print("\n[WARNING] Chat connection failed immediately.")
            print("-> Reason A: The creator has disabled the Live Chat.")
            print("-> Reason B: The chat is restricted (Members Only / Age-Restricted).")
            print("-> Action: Try a different live stream with a public chat.")
            return

        print(f"\n----- LIVE STREAM ACTIVE -----")
        empty_loops = 0

        while chat.is_alive():
            items = chat.get().sync_items()

            if items:
                empty_loops = 0
                for c in items:
                    message = {
                        "payload_text": c.message,
                        "source_platform": "YouTube",
                        "env_domain": domain_context,
                        "env_subgenre": subgenre,
                        "env_strictness": strictness,
                        "platform_metadata": {
                            "video_id": video_id,
                            "video_title": raw_meta["title"],
                            "channel_name": raw_meta["channel_name"],
                            "tweet_id": str(c.id),
                            "author_id": c.author.channelId,
                            "author_name": c.author.name,
                            "is_moderator": c.author.isChatModerator,
                            "is_sponsor": c.author.isChatSponsor,
                        },
                    }
                    producer.send(KAFKA_TOPIC, message)
                    print(f"[{domain_context.upper()}{subgenre_display}] {c.author.name}: {c.message}")
            else:
                empty_loops += 1
                if empty_loops % 10 == 0:
                    print(f"[{domain_context.upper()}{subgenre_display}] ... [Waiting for chat messages] ...")

            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\n-> [YouTube Adapter] Stream safely terminated.")
    except Exception as e:
        print(f"-> [YouTube Adapter] Stream Error: {e}")


if __name__ == "__main__":
    print("Run this adapter via omni_ingest.py, not directly.")
