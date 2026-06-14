"""
Twitch Live Chat Adapter — anonymous IRC.

Connects to Twitch's IRC-style chat server WITHOUT requiring an OAuth
token, using the documented "justinfan" anonymous-read convention. This
is the easiest possible Twitch ingestion: zero credentials, free, real-time.

If you want to act as an actual Twitch account (post messages, get
subscriber-only chat, etc.) you'd register a Twitch app, get an OAuth
token, and replace the anonymous credentials. For passive moderation
research the anonymous read path is sufficient.

References:
- https://dev.twitch.tv/docs/irc/
- Anonymous user: nick=justinfan<random>, pass=ignored

Reads metadata (stream title + category) from the public stream page via
HTTP scrape — no API key needed.
"""

import json
import random
import re
import socket
import time
import urllib.request

from kafka import KafkaProducer

from adapters.context_agent import resolve_environment

KAFKA_TOPIC = "universal_stream"
KAFKA_SERVER = "127.0.0.1:9093"

TWITCH_IRC_HOST = "irc.chat.twitch.tv"
TWITCH_IRC_PORT = 6667


# ---------------------------------------------------------------------------
# URL parsing + metadata
# ---------------------------------------------------------------------------

def extract_channel(url_or_name: str) -> str:
    """Accepts 'twitch.tv/channelname' or 'https://www.twitch.tv/channelname' or just 'channelname'."""
    s = str(url_or_name).strip().lower()
    if "twitch.tv/" in s:
        s = s.split("twitch.tv/", 1)[1]
    s = s.split("/")[0].split("?")[0]
    return s


def fetch_twitch_metadata(channel: str) -> dict:
    """Scrape https://www.twitch.tv/<channel> for stream title + category."""
    print(f"-> [Twitch Adapter] Fetching public metadata for channel: {channel}")
    url = f"https://www.twitch.tv/{channel}"

    metadata = {
        "channel_name": channel,
        "title": "Unknown Title",
        "category": "Unknown Category",
        "is_live": False,
    }

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        html = urllib.request.urlopen(req, timeout=5).read().decode("utf-8", errors="ignore")

        # Title in og:title (e.g. "channelname - Just Chatting - Twitch")
        m = re.search(r'<meta property="og:title" content="(.*?)"', html)
        if m:
            metadata["title"] = m.group(1).strip()

        # Description hints at category
        m = re.search(r'<meta property="og:description" content="(.*?)"', html)
        if m:
            metadata["category"] = m.group(1).strip()[:200]

        # A "isLiveBroadcast" hint usually appears for live channels
        metadata["is_live"] = '"isLiveBroadcast"' in html or '"BroadcastEvent"' in html

    except Exception as e:
        print(f"-> [Twitch Adapter] Metadata Warning: {e}")

    return metadata


# ---------------------------------------------------------------------------
# IRC protocol
# ---------------------------------------------------------------------------

def _irc_connect(channel: str) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((TWITCH_IRC_HOST, TWITCH_IRC_PORT))

    nick = f"justinfan{random.randint(10000, 99999)}"
    # Anonymous: any PASS is accepted but we send a placeholder for protocol completeness.
    s.send(b"PASS SCHMOOPIIE\r\n")
    s.send(f"NICK {nick}\r\n".encode("utf-8"))
    s.send(f"JOIN #{channel}\r\n".encode("utf-8"))
    s.settimeout(2.0)  # short timeout so we can yield control periodically
    print(f"-> [Twitch Adapter] Joined #{channel} as {nick}")
    return s


_PRIVMSG_RE = re.compile(
    r"^:(?P<nick>[^!]+)![^@]+@[^ ]+ PRIVMSG #(?P<channel>[^ ]+) :(?P<message>.*)$"
)


def _parse_privmsg(line: str):
    """Returns (author, channel, text) or None if line isn't a chat message."""
    line = line.strip()
    if not line:
        return None
    if line.startswith("PING "):
        return ("__PING__", line[5:], "")
    m = _PRIVMSG_RE.match(line)
    if not m:
        return None
    return (m["nick"], m["channel"], m["message"])


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def start_twitch_pipeline(url_or_name: str):
    channel = extract_channel(url_or_name)
    if not channel:
        print("[BLOCKED] Could not parse a Twitch channel name from input.")
        return

    raw_meta = fetch_twitch_metadata(channel)

    print("\n--- EXTRACTED TWITCH METADATA ---")
    print(f"Channel:  {raw_meta['channel_name']}")
    print(f"Title:    {raw_meta['title']}")
    print(f"Category: {raw_meta['category']}")
    print(f"Is Live:  {raw_meta['is_live']}")
    print("---------------------------------")

    if not raw_meta["is_live"]:
        print("\n[WARN] Stream may not be live — Twitch metadata hints disagree.")
        print("-> Continuing anyway; IRC will simply receive no messages if offline.")

    print("\n-> [Twitch Adapter] Requesting Context Resolution from XAI Agent...")
    env = resolve_environment("Twitch", raw_meta)
    domain = env["env_domain"]
    subgenre = env["env_subgenre"]
    strictness = env["env_strictness"]
    subgenre_display = f"/{subgenre}" if subgenre else ""
    print(
        f"-> [Twitch Adapter] Context Locked: [{domain.upper()}{subgenre_display}] | "
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

    try:
        sock = _irc_connect(channel)
    except Exception as e:
        print(f"-> [Twitch Adapter] IRC connect failed: {e}")
        return

    print(f"\n----- TWITCH CHAT ACTIVE for #{channel} -----")

    buffer = b""
    msg_counter = 0
    empty_loops = 0

    try:
        while True:
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                empty_loops += 1
                if empty_loops % 30 == 0:  # every ~60 seconds
                    print(f"[{domain.upper()}{subgenre_display}] ... [Waiting for chat] ...")
                continue
            if not chunk:
                print("-> [Twitch Adapter] IRC connection closed by server.")
                break

            empty_loops = 0
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                try:
                    text = line.decode("utf-8", errors="ignore").strip()
                except Exception:
                    continue

                parsed = _parse_privmsg(text)
                if parsed is None:
                    continue

                author, channel_in, content = parsed

                if author == "__PING__":
                    sock.send(f"PONG {content}\r\n".encode("utf-8"))
                    continue

                msg_counter += 1
                message = {
                    "payload_text":               content,
                    "source_platform":            "Twitch",
                    "env_domain":                 env["env_domain"],
                    "env_domain_raw":             env["env_domain_raw"],
                    "env_domain_match":           env["env_domain_match"],
                    "env_subgenre":               env["env_subgenre"],
                    "env_strictness":             env["env_strictness"],
                    "env_strictness_reasoning":   env["env_strictness_reasoning"],
                    "platform_metadata": {
                        "video_id":      f"twitch-{channel}",   # placeholder thread id
                        "video_title":   raw_meta["title"],
                        "channel_name":  raw_meta["channel_name"],
                        "tweet_id":      f"twitch-{channel}-{msg_counter}",
                        "author_id":     author,        # Twitch login name (lowercase)
                        "author_name":   author,
                        "is_moderator":  False,         # would need IRC tags parsing (capability request) to detect
                        "is_sponsor":    False,
                    },
                }
                producer.send(KAFKA_TOPIC, message)
                print(f"[{domain.upper()}{subgenre_display}] {author}: {content[:120]}")

    except KeyboardInterrupt:
        print("\n-> [Twitch Adapter] Stream safely terminated.")
    except Exception as e:
        print(f"-> [Twitch Adapter] Stream error: {e}")
    finally:
        # CRITICAL: flush any buffered Kafka messages before exit. Without this,
        # short runs (Ctrl+C after only a few messages) lose the entire async
        # send buffer — those messages never reach the broker.
        try:
            print("-> [Twitch Adapter] Flushing Kafka producer buffer...")
            producer.flush(timeout=10)
            producer.close(timeout=5)
            print(f"-> [Twitch Adapter] Producer closed. {msg_counter} messages sent in this session.")
        except Exception as e:
            print(f"-> [Twitch Adapter] Producer flush failed: {e}")
        try:
            sock.close()
        except Exception:
            pass


if __name__ == "__main__":
    print("Run this adapter via omni_ingest.py, not directly.")
