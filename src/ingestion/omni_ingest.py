"""
Omni-Ingestion Router.

Entry point that decides which Layer-1 adapter to spin up based on the
URL the operator provides. Routes YouTube live chat, Twitch live chat
(anonymous IRC), and Reddit comment streams.

New adapters plug in by adding an `elif` branch + an adapter module
under adapters/ and registering it here.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from adapters.youtube_adapter import start_youtube_pipeline
from adapters.twitch_adapter import start_twitch_pipeline
from adapters.reddit_adapter import start_reddit_pipeline

DEFAULT_TEST_VIDEO_ID = "mAoDkS1ZBw0"


def route_input():
    print("\n" + "=" * 60)
    print(" OMNI-INGESTION ROUTER")
    print("=" * 60)
    print("Accepts:")
    print("  - YouTube:  https://www.youtube.com/watch?v=... or https://youtu.be/...")
    print("  - Twitch:   https://www.twitch.tv/<channel> or just <channel>")
    print("  - Reddit:   https://www.reddit.com/r/<subreddit> or r/<subreddit>")
    print()

    user_input = input("Paste a URL (Enter for default YouTube test stream): ").strip()

    if not user_input:
        print(f"\n-> [Router] No input. Defaulting to YouTube test stream {DEFAULT_TEST_VIDEO_ID}.")
        start_youtube_pipeline(DEFAULT_TEST_VIDEO_ID)
        return

    lower = user_input.lower()

    if "youtube.com" in lower or "youtu.be" in lower:
        print("\n-> [Router] YouTube URL detected. Handing off to YouTube adapter...")
        start_youtube_pipeline(user_input)
        return

    if "twitch.tv" in lower or lower.startswith("twitch:"):
        print("\n-> [Router] Twitch URL detected. Handing off to Twitch adapter...")
        start_twitch_pipeline(user_input)
        return

    if "reddit.com" in lower or lower.startswith("r/") or lower.startswith("/r/"):
        print("\n-> [Router] Reddit URL detected. Handing off to Reddit adapter...")
        start_reddit_pipeline(user_input)
        return

    # Heuristic fallback: bare channel/subreddit names
    if "/" not in user_input and " " not in user_input and len(user_input) <= 30:
        print(
            "\n-> [Router] Ambiguous bare name. Defaulting to Twitch channel. "
            "Prefix with 'r/' to force Reddit."
        )
        start_twitch_pipeline(user_input)
        return

    print("\n-> [Router] Error: Could not recognise the source from this URL.")
    print("    Supported: YouTube, Twitch, Reddit. See docs/SOURCES.md.")


if __name__ == "__main__":
    try:
        route_input()
    except KeyboardInterrupt:
        print("\n[Router] Shutting down safely. Goodbye.")
