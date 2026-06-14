# Data sources — free APIs we can ingest from

A survey of platforms that publish user-generated text and let you read it for free. Categorised by **how easy** it is to start. The pipeline currently ships adapters for three of them (YouTube, Twitch, Reddit); the rest are notes for future work.

---

## Currently implemented (Layer-1 adapters in `src/ingestion/adapters/`)

### 1. YouTube Live Chat — `youtube_adapter.py`
- **Auth:** None. Uses `pytchat` library which connects to the live-chat backend anonymously.
- **Setup time:** 0 minutes.
- **Quality:** Excellent. Very active chats on live streams. Domain metadata (title, channel, description) scraped from the watch page.
- **Limits:** Stream must be currently live AND have public chat enabled. Members-only / age-restricted chats are blocked.
- **Run it:** `python src/ingestion/omni_ingest.py` → paste a YouTube live URL.

### 2. Twitch Chat — `twitch_adapter.py` *(new)*
- **Auth:** None. Connects to Twitch IRC as anonymous `justinfan<random>` user (documented Twitch pattern for read-only access).
- **Setup time:** 0 minutes.
- **Quality:** Very high. Twitch chat is fast, dense, slang-heavy — exactly the kind of stress test the Tier-2 judge needs. Stream title + game category scraped from the channel page.
- **Limits:** Doesn't have access to subscriber-only or follower-only modes. No moderator badges in messages (would need PRAW-equivalent capability negotiation; left for future polish).
- **Run it:** `python src/ingestion/omni_ingest.py` → paste `https://www.twitch.tv/channelname` or just `channelname`.

### 3. Reddit Comments — `reddit_adapter.py` *(new)*
- **Auth:** Required, free. PRAW with OAuth credentials.
- **Setup time:** 5 minutes one-time.
  1. Go to https://www.reddit.com/prefs/apps → "create another app"
  2. Choose "script", name it anything, redirect URI = `http://localhost:8080`
  3. Copy the client ID (under the app name) and the secret
  4. Add to your `.env`:
     ```
     REDDIT_CLIENT_ID=your_client_id
     REDDIT_CLIENT_SECRET=your_secret
     REDDIT_USER_AGENT=hate-speech-pipeline by /u/yourusername
     ```
  5. Install: `pip install praw>=7.7`
- **Quality:** Different data shape than live chat. Comments are longer, more deliberate, harder to classify. Good for testing the Context Agent against subreddit-specific cultures.
- **Run it:** `python src/ingestion/omni_ingest.py` → paste `https://www.reddit.com/r/AskReddit` or `r/AskReddit`.
- **Tip:** Multi-subreddit streams use `+`, e.g. `r/AskReddit+politics+gaming+technology`.

---

## Easy to add next (under 1 hour each)

### 4. Hacker News
- **Auth:** None. Public HTTP API.
- **Endpoint:** `https://hacker-news.firebaseio.com/v0/`
- **Quality:** Tech-domain comments. Generally civil but occasionally heated. Good for testing the agent on technical / news-adjacent text.
- **Polling not streaming:** the API is REST, not WebSocket — would need a poll loop fetching `maxitem` and walking backwards.
- **Implementation effort:** ~1 hour.

### 5. GitHub Issue Comments
- **Auth:** Free GitHub Personal Access Token. 5,000 req/hour with token, 60 without.
- **Endpoint:** `https://api.github.com/repos/{owner}/{repo}/issues/comments`
- **Quality:** Tech-domain, occasionally heated (open-source flame wars). Good for "is this user being toxic to a maintainer?" use cases.
- **Implementation effort:** ~1 hour.

### 6. Mastodon Public Timeline
- **Auth:** None for the public timeline of any instance (mastodon.social, fosstodon.org, etc.).
- **Streaming API:** `wss://mastodon.social/api/v1/streaming/public`
- **Quality:** Tweet-like short posts. Variable activity. Multilingual.
- **Implementation effort:** ~1.5 hours (WebSocket + parsing).

### 7. Bluesky Firehose
- **Auth:** Free account.
- **Endpoint:** `wss://bsky.network/xrpc/com.atproto.sync.subscribeRepos` (binary CBOR — needs decoding library).
- **Quality:** Twitter-like firehose. Very high volume. Multilingual.
- **Implementation effort:** ~2-3 hours (CBOR + AT Protocol learning curve).

---

## Possible but more friction

### 8. Twitter / X
- **Status:** The free API tier is severely restricted post-2023. Effectively unusable for streaming research projects.
- **Workaround:** `snscrape` was the community scraper of choice but Twitter has been actively blocking it.
- **Recommendation:** **Skip** unless you have an academic API access grant.

### 9. Discord
- **Auth:** Discord bot account (free) + server admin invite.
- **Quality:** Very high — Discord chats are similar in feel to Twitch.
- **Friction:** You need to be in the server. Public Discord servers exist but most interesting ones are invite-only.
- **Implementation effort:** ~1.5 hours with `discord.py`.

### 10. Stack Exchange / Stack Overflow
- **Auth:** Free token, 10,000 req/day.
- **Quality:** Tech-domain comments. Heavily moderated already — most toxicity has been removed.
- **Use case:** More for "what does NORMAL technical disagreement look like?" than "find toxicity".

### 11. 4chan public API
- **Auth:** None.
- **Quality:** Very high (raw, unmoderated text — exactly what Tier-2 should catch).
- **Ethical concern:** **Skip for thesis.** Defending the use of unmoderated extremist content as training data is a fight you don't need. Stick to platforms with active moderation policies.

---

## Recommended diversification for your thesis

If you want to argue "our pipeline generalises across platforms", aim for **3-4 substantively-different sources**:

| Bucket | Source | Why this bucket |
|---|---|---|
| Live streaming chat | YouTube (have) + Twitch (have) | Real-time, slang-heavy, gaming/entertainment-leaning |
| Forum-style comments | Reddit (have) | Longer text, threaded, community-specific norms |
| Microblogging | Mastodon OR Bluesky | Tweet-like, mixed topics, multilingual |
| Tech/professional | Hacker News OR GitHub Issues | Different register, professional context |

Three of those buckets already have working adapters. Adding **one of Mastodon/Bluesky + one of HN/GitHub** gets you to four buckets and a defensible "cross-domain Trust & Safety pipeline" claim. ~3-4 hours of total work.

---

## Implementation pattern (if you want to add a fourth source yourself)

Every Layer-1 adapter has the same shape — copy-paste from `twitch_adapter.py` and replace the protocol-specific bits:

1. **Parse the URL/identifier** → channel / subreddit / topic name.
2. **Scrape or fetch metadata** → title, description, channel name, anything the Context Agent can use to classify domain.
3. **Call `resolve_environment(platform_name, raw_meta)`** → the LLM proposes env_domain.
4. **Open the protocol connection** → IRC socket / WebSocket / polling loop.
5. **For each incoming message:**
   - Build a Universal Schema dict (`payload_text`, `source_platform`, every `env_*` field, nested `platform_metadata`).
   - Push to Kafka via the configured producer.
6. **Handle Ctrl+C and connection errors** → close socket / producer cleanly.

The Tier-1 processor doesn't care which adapter the message came from — every Kafka payload looks the same.

---

## Verifying multi-source ingestion works

Once you've started producers from 2+ platforms simultaneously, the **analytics dashboard** Tab 1 (`Overview`) shows a "Platform distribution" bar chart that breaks down records by `source_platform`. If you see multiple bars (`YouTube`, `Twitch`, `Reddit`), the pipeline is platform-agnostic and you can defend that claim.

In Kibana / the analytics dashboard, filter by `source_platform.keyword` to see per-platform Tier-1 + Tier-2 behaviour. Differences in (e.g.) `env_domain_match` rate between platforms is itself a publishable finding.
