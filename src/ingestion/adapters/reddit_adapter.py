"""
Reddit Comment Streaming Adapter (via PRAW).

Streams comments from one or more subreddits in real time and forwards
them to Kafka under the Universal Schema. Comments stream is read-only;
PRAW handles auth via OAuth credentials configured in `.env`.

Setup (one-time, ~5 minutes):
  1. Go to https://www.reddit.com/prefs/apps and click "create another app"
  2. Choose "script", name it anything, redirect URI = http://localhost:8080
  3. Copy the client ID (under the app name) and the secret
  4. Add to your .env file:
        REDDIT_CLIENT_ID=...
        REDDIT_CLIENT_SECRET=...
        REDDIT_USER_AGENT=hate-speech-pipeline by /u/yourname

Usage (via omni_ingest.py):
  Paste a URL like:
      https://www.reddit.com/r/AskReddit
      https://www.reddit.com/r/politics+gaming+news    (multi-subreddit)
      r/AskReddit                                       (shorthand)
"""

import json
import os
import sys

from kafka import KafkaProducer

from adapters.context_agent import resolve_environment

# Lazy imports — only require praw + config when this adapter actually runs.
sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

KAFKA_TOPIC = "universal_stream"
KAFKA_SERVER = "127.0.0.1:9093"


def extract_subreddit(url_or_name: str) -> str:
    """Accepts /r/foo, r/foo, https://reddit.com/r/foo, reddit.com/r/foo, foo+bar+baz."""
    s = str(url_or_name).strip()
    s = s.replace("https://", "").replace("http://", "")
    s = s.replace("www.", "").replace("old.", "").replace("new.", "")
    if "reddit.com/" in s:
        s = s.split("reddit.com/", 1)[1]
    s = s.strip("/")
    if s.startswith("r/"):
        s = s[2:]
    if "/" in s:
        s = s.split("/", 1)[0]
    return s


def start_reddit_pipeline(url_or_name: str):
    try:
        import praw
    except ImportError:
        print("[Reddit Adapter] praw is not installed. Run: pip install praw>=7.7")
        return

    from shared_utils.config import (
        REDDIT_CLIENT_ID,
        REDDIT_CLIENT_SECRET,
        REDDIT_USER_AGENT,
    )

    if not REDDIT_CLIENT_ID or not REDDIT_CLIENT_SECRET:
        print("[Reddit Adapter] Reddit credentials missing. Add to your .env:")
        print("    REDDIT_CLIENT_ID=...")
        print("    REDDIT_CLIENT_SECRET=...")
        print("    REDDIT_USER_AGENT=hate-speech-pipeline by /u/yourname")
        print("See docs/SOURCES.md for the one-time Reddit app setup.")
        return

    sub_name = extract_subreddit(url_or_name)
    if not sub_name:
        print("[Reddit Adapter] Could not parse a subreddit name from input.")
        return

    print(f"-> [Reddit Adapter] Target subreddit(s): r/{sub_name}")

    raw_meta = {
        "subreddit": sub_name,
        "title": f"Reddit comment stream — r/{sub_name}",
        "description": f"Live comments from r/{sub_name}",
        "is_live": True,
    }

    print("\n-> [Reddit Adapter] Requesting Context Resolution from XAI Agent...")
    env = resolve_environment("Reddit", raw_meta)
    domain = env["env_domain"]
    subgenre = env["env_subgenre"]
    strictness = env["env_strictness"]
    subgenre_display = f"/{subgenre}" if subgenre else ""
    print(
        f"-> [Reddit Adapter] Context Locked: [{domain.upper()}{subgenre_display}] | "
        f"Strictness: [{strictness.upper()}] | Match: {env['env_domain_match']} | "
        f"LLM raw proposal: {env['env_domain_raw']!r}"
    )

    try:
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_SERVER,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
    except Exception as e:
        print(f"-> [Kafka Error] Could not connect to message bus: {e}")
        return

    print("-> [Reddit Adapter] Connecting to Reddit via PRAW...")
    reddit = praw.Reddit(
        client_id=REDDIT_CLIENT_ID,
        client_secret=REDDIT_CLIENT_SECRET,
        user_agent=REDDIT_USER_AGENT,
    )

    print(f"\n----- REDDIT COMMENT STREAM ACTIVE for r/{sub_name} -----")
    try:
        subreddit = reddit.subreddit(sub_name)
        for comment in subreddit.stream.comments(skip_existing=True):
            try:
                text = (comment.body or "").strip()
                if not text or text == "[deleted]" or text == "[removed]":
                    continue

                author_name = (
                    str(comment.author) if comment.author else "[deleted]"
                )

                message = {
                    "payload_text":               text,
                    "source_platform":            "Reddit",
                    "env_domain":                 env["env_domain"],
                    "env_domain_raw":             env["env_domain_raw"],
                    "env_domain_match":           env["env_domain_match"],
                    "env_subgenre":               env["env_subgenre"],
                    "env_strictness":             env["env_strictness"],
                    "env_strictness_reasoning":   env["env_strictness_reasoning"],
                    "platform_metadata": {
                        "video_id":      str(comment.submission.id),
                        "video_title":   (comment.submission.title or "")[:200],
                        "channel_name":  f"r/{comment.subreddit.display_name}",
                        "tweet_id":      str(comment.id),
                        "author_id":     author_name,
                        "author_name":   author_name,
                        "is_moderator":  bool(comment.distinguished == "moderator"),
                        "is_sponsor":    False,
                    },
                }
                producer.send(KAFKA_TOPIC, message)
                print(
                    f"[{domain.upper()}{subgenre_display}] "
                    f"{author_name} (r/{comment.subreddit.display_name}): "
                    f"{text[:120]}"
                )

            except Exception as inner:
                print(f"-> [Reddit Adapter] Skipped one comment: {inner}")

    except KeyboardInterrupt:
        print("\n-> [Reddit Adapter] Stream safely terminated.")
    except Exception as e:
        print(f"-> [Reddit Adapter] Stream error: {e}")
    finally:
        # CRITICAL: flush the Kafka producer's async buffer before exiting.
        # Otherwise short runs lose pending messages.
        try:
            print("-> [Reddit Adapter] Flushing Kafka producer buffer...")
            producer.flush(timeout=10)
            producer.close(timeout=5)
            print("-> [Reddit Adapter] Producer closed.")
        except Exception as e:
            print(f"-> [Reddit Adapter] Producer flush failed: {e}")


if __name__ == "__main__":
    print("Run this adapter via omni_ingest.py, not directly.")
