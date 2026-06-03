"""
Omni-Ingestion Router (Stage 0 — YouTube only).

Entry point that decides which Layer-1 adapter to spin up based on the
URL the operator provides. Currently routes only to the YouTube adapter;
new adapters (Reddit, Twitch, etc.) plug in by adding a branch + an
adapter module under adapters/ and registering it here.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from adapters.youtube_adapter import start_youtube_pipeline

DEFAULT_TEST_VIDEO_ID = "mAoDkS1ZBw0"


def route_input():
    print("\n" + "=" * 60)
    print(" OMNI-INGESTION ROUTER: AWAITING DATA SOURCE")
    print("=" * 60)

    user_input = input("Paste a YouTube link (Enter for default test stream): ").strip()

    if not user_input:
        print(f"\n-> [Router] No input detected. Defaulting to test stream {DEFAULT_TEST_VIDEO_ID}.")
        start_youtube_pipeline(DEFAULT_TEST_VIDEO_ID)
        return

    if "youtube.com" in user_input or "youtu.be" in user_input:
        print("\n-> [Router] YouTube URL detected. Handing off to YouTube Adapter...")
        start_youtube_pipeline(user_input)
        return

    print("\n-> [Router] Error: Only YouTube URLs are supported in Stage 0.")
    print("    Other adapters (Reddit, Twitch, etc.) are future-work — see docs/ROADMAP.md.")


if __name__ == "__main__":
    try:
        route_input()
    except KeyboardInterrupt:
        print("\n[Router] Shutting down safely. Goodbye.")
