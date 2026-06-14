"""
Stage 2 — Temporal Memory & Conversational Context.

Pulls per-user and per-thread history from Elasticsearch and formats it for
injection into the Tier-2 judge prompt. This is what lets the judge reason
"this user has been Normal 16/20 times, so this single suspicious message
is more likely sarcasm than coordinated harassment" instead of judging
each message in isolation.

Design choices:
- All functions return prompt-ready *strings*, never raw ES hits. Callers
  who need the raw hits can use ES directly; the string layer keeps the
  prompt-injection contract clean.
- No LLM calls happen here. Memory is pure retrieval — fast, deterministic.
- Per shared_utils/config.py the user-history window is 10 messages,
  lookback 24h, fingerprint over 20 messages. All configurable via env vars.
- Cross-domain by design — Stage 2 chose "All domains, full lookback" for
  the broadest behavioural signal (catches users who behave well in Gaming
  but escalate in Politics).
"""

import datetime
from typing import Optional

from elasticsearch import Elasticsearch

from shared_utils.config import (
    ES_HOST,
    INDEX_NAME,
    MEMORY_USER_WINDOW_SIZE,
    MEMORY_THREAD_WINDOW_SIZE,
    MEMORY_LOOKBACK_HOURS,
    MEMORY_FINGERPRINT_WINDOW,
)

_es = Elasticsearch(ES_HOST)


# ---------------------------------------------------------------------------
# Low-level ES retrieval
# ---------------------------------------------------------------------------

def _query_user_messages(
    author_id: str,
    window: int,
    lookback_hours: int,
    before_timestamp: Optional[str] = None,
    exclude_message_id: Optional[str] = None,
):
    """Last `window` messages from this author within `lookback_hours`, newest first.

    `before_timestamp` (ISO-8601) restricts to messages strictly before that
    moment — used when looking up history for a record we are currently
    judging so we don't leak the current message into its own context.
    """
    cutoff = (
        datetime.datetime.now() - datetime.timedelta(hours=lookback_hours)
    ).isoformat()

    must = [
        {"term": {"author_id": author_id}},
        {"range": {"timestamp": {"gte": cutoff}}},
    ]
    if before_timestamp:
        must.append({"range": {"timestamp": {"lt": before_timestamp}}})

    must_not = []
    if exclude_message_id:
        must_not.append({"term": {"message_id": exclude_message_id}})

    body = {
        "query": {"bool": {"must": must, "must_not": must_not}},
        "sort": [{"timestamp": {"order": "desc"}}],
        "size": window,
    }
    try:
        res = _es.search(index=INDEX_NAME, body=body)
        return res["hits"]["hits"]
    except Exception as exc:
        print(f"-> [Memory] user history query failed: {exc}")
        return []


def _query_thread_messages(
    thread_id: str,
    before_timestamp: Optional[str],
    window: int,
    exclude_message_id: Optional[str] = None,
):
    """Last `window` messages in the same thread that came before `before_timestamp`."""
    must = [{"term": {"thread_id": thread_id}}]
    if before_timestamp:
        must.append({"range": {"timestamp": {"lt": before_timestamp}}})

    must_not = []
    if exclude_message_id:
        must_not.append({"term": {"message_id": exclude_message_id}})

    body = {
        "query": {"bool": {"must": must, "must_not": must_not}},
        "sort": [{"timestamp": {"order": "desc"}}],
        "size": window,
    }
    try:
        res = _es.search(index=INDEX_NAME, body=body)
        return res["hits"]["hits"]
    except Exception as exc:
        print(f"-> [Memory] thread history query failed: {exc}")
        return []


# ---------------------------------------------------------------------------
# Formatting helpers — return strings ready to drop into prompts
# ---------------------------------------------------------------------------

def _format_age(iso_timestamp: str) -> str:
    try:
        ts = datetime.datetime.fromisoformat(iso_timestamp.replace("Z", ""))
        delta = datetime.datetime.now() - ts
        secs = delta.total_seconds()
        if secs < 60:
            return f"{int(secs)}s ago"
        if secs < 3600:
            return f"{int(secs / 60)}m ago"
        if secs < 86400:
            return f"{int(secs / 3600)}h ago"
        return f"{int(secs / 86400)}d ago"
    except Exception:
        return "?"


def _format_hits(hits, max_text_len: int = 80) -> str:
    if not hits:
        return "(no prior messages on record)"

    lines = []
    for hit in hits:
        src = hit["_source"]
        age = _format_age(src.get("timestamp", ""))
        label = src.get("model_label", "?")
        domain = src.get("env_domain", "?")
        text = (src.get("text", "") or "").replace("\n", " ")[:max_text_len]
        lines.append(f"  [{age:>7s} | {label:<9s} | {domain:<13s}] {text}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_user_history(
    author_id: str,
    window: int = MEMORY_USER_WINDOW_SIZE,
    lookback_hours: int = MEMORY_LOOKBACK_HOURS,
    before_timestamp: Optional[str] = None,
    exclude_message_id: Optional[str] = None,
) -> str:
    """Last N messages from this user across all threads, formatted for prompt injection."""
    if not author_id or author_id == "UNKNOWN":
        return "(unknown author — no history available)"
    hits = _query_user_messages(
        author_id=author_id,
        window=window,
        lookback_hours=lookback_hours,
        before_timestamp=before_timestamp,
        exclude_message_id=exclude_message_id,
    )
    return _format_hits(hits)


def get_thread_context(
    thread_id: str,
    before_timestamp: Optional[str],
    window: int = MEMORY_THREAD_WINDOW_SIZE,
    exclude_message_id: Optional[str] = None,
) -> str:
    """Last N messages in the same thread before this one, formatted for prompt injection."""
    if not thread_id or thread_id == "N/A":
        return "(no thread context available)"
    hits = _query_thread_messages(
        thread_id=thread_id,
        before_timestamp=before_timestamp,
        window=window,
        exclude_message_id=exclude_message_id,
    )
    return _format_hits(hits)


def get_user_behavior_fingerprint(
    author_id: str,
    window: int = MEMORY_FINGERPRINT_WINDOW,
    lookback_hours: int = MEMORY_LOOKBACK_HOURS,
    before_timestamp: Optional[str] = None,
    exclude_message_id: Optional[str] = None,
) -> str:
    """
    One-line structured summary of the user's recent labels, e.g.:
        "Last 20 msgs: 16 Normal / 3 OFFENSIVE / 1 HATE. Most recent flagged: 2h ago."
    """
    if not author_id or author_id == "UNKNOWN":
        return "(unknown author — no fingerprint)"

    hits = _query_user_messages(
        author_id=author_id,
        window=window,
        lookback_hours=lookback_hours,
        before_timestamp=before_timestamp,
        exclude_message_id=exclude_message_id,
    )

    if not hits:
        return "(no prior messages within lookback window)"

    counts = {"Normal": 0, "OFFENSIVE": 0, "HATE": 0}
    most_recent_toxic_age = None
    for hit in hits:
        src = hit["_source"]
        label = src.get("model_label", "Normal")
        if label in counts:
            counts[label] += 1
        if label in ("OFFENSIVE", "HATE") and most_recent_toxic_age is None:
            most_recent_toxic_age = _format_age(src.get("timestamp", ""))

    n = len(hits)
    parts = [f"{counts['Normal']} Normal", f"{counts['OFFENSIVE']} OFFENSIVE", f"{counts['HATE']} HATE"]
    fp = f"Last {n} msgs: " + " / ".join(parts) + "."
    if most_recent_toxic_age:
        fp += f" Most recent flagged: {most_recent_toxic_age}."
    else:
        fp += " No flagged events in lookback window."
    return fp


def fetch_memory_bundle(
    author_id: str,
    thread_id: str,
    before_timestamp: Optional[str] = None,
    exclude_message_id: Optional[str] = None,
) -> dict:
    """
    Convenience: pull all three context blocks at once. Returns a dict with the
    formatted strings AND raw counts so the caller can persist
    agent_memory_user_msgs / agent_memory_thread_msgs to ES.
    """
    user_hits = _query_user_messages(
        author_id=author_id,
        window=MEMORY_USER_WINDOW_SIZE,
        lookback_hours=MEMORY_LOOKBACK_HOURS,
        before_timestamp=before_timestamp,
        exclude_message_id=exclude_message_id,
    )
    thread_hits = _query_thread_messages(
        thread_id=thread_id,
        before_timestamp=before_timestamp,
        window=MEMORY_THREAD_WINDOW_SIZE,
        exclude_message_id=exclude_message_id,
    )

    fingerprint = get_user_behavior_fingerprint(
        author_id=author_id,
        before_timestamp=before_timestamp,
        exclude_message_id=exclude_message_id,
    )

    return {
        "user_history_text": _format_hits(user_hits) if user_hits else "(no prior messages on record)",
        "thread_context_text": _format_hits(thread_hits) if thread_hits else "(no thread context available)",
        "fingerprint": fingerprint,
        "user_msgs_count": len(user_hits),
        "thread_msgs_count": len(thread_hits),
    }
