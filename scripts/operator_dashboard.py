"""
Operator dashboard — read-only monitoring UI for the moderation pipeline.

NOT a chat UI. NOT user-facing. This is the equivalent of a power-plant
control room: numbers, charts, "is X reachable", "what just happened".
Used by the moderator / thesis author / examiner to verify the pipeline
is alive without SSHing into containers.

Run:
    streamlit run scripts/operator_dashboard.py

Then open http://localhost:8501.

Auto-refreshes every ~5-15 seconds depending on the panel. Closing the
tab stops the page; the Streamlit process is killed with Ctrl+C.

Requires:
    pip install streamlit
"""

from __future__ import annotations

import datetime
import os
import sys
from pathlib import Path

import streamlit as st

# Path setup — make src/ importable so we can reach shared_utils.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shared_utils.config import (
    ES_HOST,
    INDEX_NAME,
    ACTIVE_MODEL,
    QDRANT_HOST,
    QDRANT_PORT,
    QDRANT_COLLECTION,
    MEMORY_ENABLED,
    RAG_ENABLED,
)

PENDING_TAXONOMY_LOG = ROOT / "data" / "pending_taxonomy.log"

st.set_page_config(
    page_title="Moderation Pipeline — Operator Dashboard",
    layout="wide",
)


# ---------------------------------------------------------------------------
# Health checks (cheap, run on every refresh)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=5)
def check_elasticsearch() -> tuple[bool, str]:
    try:
        from elasticsearch import Elasticsearch
        es = Elasticsearch(ES_HOST, request_timeout=2)
        if not es.ping():
            return False, "ping failed"
        info = es.indices.exists(index=INDEX_NAME)
        return True, f"index '{INDEX_NAME}' {'exists' if info else 'MISSING'}"
    except Exception as exc:
        return False, str(exc)[:80]


@st.cache_data(ttl=5)
def check_qdrant() -> tuple[bool, str]:
    try:
        import requests
        r = requests.get(f"http://{QDRANT_HOST}:{QDRANT_PORT}/collections/{QDRANT_COLLECTION}", timeout=2)
        if r.status_code == 200:
            data = r.json().get("result", {})
            n = data.get("points_count") or data.get("vectors_count") or 0
            return True, f"{n} points in '{QDRANT_COLLECTION}'"
        if r.status_code == 404:
            return False, f"collection '{QDRANT_COLLECTION}' not created yet"
        return False, f"HTTP {r.status_code}"
    except Exception as exc:
        return False, str(exc)[:80]


@st.cache_data(ttl=5)
def check_ollama() -> tuple[bool, str]:
    try:
        import requests
        r = requests.get("http://localhost:11434/api/tags", timeout=2)
        if r.status_code == 200:
            models = [m["name"] for m in r.json().get("models", [])]
            model_short = ACTIVE_MODEL.split(":")[0]
            served = any(model_short in m for m in models)
            return True, f"running — {'serving ' + ACTIVE_MODEL if served else ACTIVE_MODEL + ' NOT FOUND'}"
        return False, f"HTTP {r.status_code}"
    except Exception as exc:
        return False, str(exc)[:80]


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------

@st.cache_data(ttl=10)
def recent_records(limit: int = 20):
    try:
        from elasticsearch import Elasticsearch
        es = Elasticsearch(ES_HOST, request_timeout=3)
        res = es.search(
            index=INDEX_NAME,
            body={"query": {"match_all": {}}, "sort": [{"timestamp": {"order": "desc"}}], "size": limit},
        )
        return [hit["_source"] for hit in res["hits"]["hits"]]
    except Exception as exc:
        return [{"error": str(exc)[:120]}]


@st.cache_data(ttl=10)
def aggregate_counts(since_minutes: int = 60):
    """Returns dict with label / domain / agent / domain_match breakdowns."""
    try:
        from elasticsearch import Elasticsearch
        es = Elasticsearch(ES_HOST, request_timeout=5)
        cutoff = (datetime.datetime.now() - datetime.timedelta(minutes=since_minutes)).isoformat()
        res = es.search(
            index=INDEX_NAME,
            body={
                "size": 0,
                "track_total_hits": True,
                "query": {"range": {"timestamp": {"gte": cutoff}}},
                "aggs": {
                    "label_breakdown": {"terms": {"field": "model_label"}},
                    "domain_breakdown": {"terms": {"field": "env_domain"}},
                    "agent_breakdown": {"terms": {"field": "agent_final_decision"}},
                    "match_breakdown": {"terms": {"field": "env_domain_match"}},
                    "avg_t1_latency": {"avg": {"field": "processing_time_ms"}},
                    "avg_t2_latency": {"avg": {"field": "agent_latency_seconds"}},
                    "avg_memory_user_msgs": {"avg": {"field": "agent_memory_user_msgs"}},
                    "avg_memory_thread_msgs": {"avg": {"field": "agent_memory_thread_msgs"}},
                },
            },
        )
        return {
            "total": res["hits"]["total"]["value"],
            "labels": {b["key"]: b["doc_count"] for b in res["aggregations"]["label_breakdown"]["buckets"]},
            "domains": {b["key"]: b["doc_count"] for b in res["aggregations"]["domain_breakdown"]["buckets"]},
            "agent_decisions": {b["key"]: b["doc_count"] for b in res["aggregations"]["agent_breakdown"]["buckets"]},
            "matches": {b["key"]: b["doc_count"] for b in res["aggregations"]["match_breakdown"]["buckets"]},
            "avg_t1_ms": res["aggregations"]["avg_t1_latency"]["value"],
            "avg_t2_s": res["aggregations"]["avg_t2_latency"]["value"],
            "avg_memory_user": res["aggregations"]["avg_memory_user_msgs"]["value"],
            "avg_memory_thread": res["aggregations"]["avg_memory_thread_msgs"]["value"],
        }
    except Exception as exc:
        return {"error": str(exc)[:120]}


@st.cache_data(ttl=15)
def pending_taxonomy_summary():
    if not PENDING_TAXONOMY_LOG.exists():
        return {"total_lines": 0, "unique_proposals": 0, "latest": []}
    lines = PENDING_TAXONOMY_LOG.read_text(encoding="utf-8").splitlines()
    proposals = []
    for line in lines:
        parts = line.split("\t", 1)
        if len(parts) == 2:
            proposals.append((parts[0], parts[1]))
    return {
        "total_lines": len(lines),
        "unique_proposals": len({p[1] for p in proposals}),
        "latest": list(reversed(proposals[-10:])),
    }


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

st.title("Moderation Pipeline — Operator Dashboard")
st.caption(
    "Read-only monitoring. Auto-refreshes every 5-15s. This is NOT a chat UI — "
    "the analyst console is `src/agents/leader_agent.py` (terminal)."
)

# ===== HEALTH ROW =====
st.subheader("Health")
h1, h2, h3, h4 = st.columns(4)

es_ok, es_msg = check_elasticsearch()
qd_ok, qd_msg = check_qdrant()
ol_ok, ol_msg = check_ollama()

with h1:
    st.metric("Elasticsearch", "OK" if es_ok else "DOWN", help=es_msg)
    st.caption(es_msg)
with h2:
    st.metric("Qdrant", "OK" if qd_ok else "DOWN", help=qd_msg)
    st.caption(qd_msg)
with h3:
    st.metric("Ollama", "OK" if ol_ok else "DOWN", help=ol_msg)
    st.caption(ol_msg)
with h4:
    st.metric("Feature flags", f"MEM={'on' if MEMORY_ENABLED else 'off'} · RAG={'on' if RAG_ENABLED else 'off'}")
    st.caption(f"Model: {ACTIVE_MODEL}")

st.divider()

# ===== VOLUME + AGGREGATES =====
st.subheader("Last 60 minutes")
window_min = st.slider("Aggregation window (minutes)", min_value=5, max_value=1440, value=60, step=5)
agg = aggregate_counts(window_min)

if "error" in agg:
    st.error(f"Aggregation query failed: {agg['error']}")
else:
    v1, v2, v3, v4 = st.columns(4)
    with v1:
        st.metric("Total records", agg["total"])
    with v2:
        st.metric("Avg Tier-1 latency", f"{(agg['avg_t1_ms'] or 0):.1f} ms")
    with v3:
        st.metric("Avg Tier-2 latency", f"{(agg['avg_t2_s'] or 0):.2f} s")
    with v4:
        st.metric(
            "Avg memory ctx (user / thread)",
            f"{(agg['avg_memory_user'] or 0):.1f} / {(agg['avg_memory_thread'] or 0):.1f}",
        )

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Tier-1 label breakdown**")
        if agg["labels"]:
            st.bar_chart(agg["labels"])
        else:
            st.write("_(no records in window)_")
    with c2:
        st.markdown("**Domain breakdown**")
        if agg["domains"]:
            st.bar_chart(agg["domains"])
        else:
            st.write("_(no records in window)_")

    c3, c4 = st.columns(2)
    with c3:
        st.markdown("**Tier-2 verdicts**")
        if agg["agent_decisions"]:
            st.bar_chart(agg["agent_decisions"])
        else:
            st.write("_(no reviewed records in window)_")
    with c4:
        st.markdown("**Taxonomy match quality** (agentic discovery signal)")
        if agg["matches"]:
            st.bar_chart(agg["matches"])
        else:
            st.write("_(no records in window)_")

st.divider()

# ===== RECENT RECORDS =====
st.subheader("Recent records (last 20)")
recs = recent_records(20)
if recs and "error" not in recs[0]:
    import pandas as pd

    rows = []
    for r in recs:
        rows.append({
            "time": (r.get("timestamp") or "")[:19],
            "platform": r.get("source_platform", "?"),
            "domain": r.get("env_domain", "?"),
            "match": r.get("env_domain_match", "?"),
            "author": (r.get("author_name") or "?")[:24],
            "Tier-1": r.get("model_label", "?"),
            "conf": f"{(r.get('model_confidence') or 0):.2f}",
            "Tier-2": r.get("agent_final_decision") or "—",
            "text": (r.get("text") or "")[:80],
        })
    st.dataframe(pd.DataFrame(rows), height=460, use_container_width=True)
elif recs:
    st.error(f"Failed to fetch recent records: {recs[0]['error']}")
else:
    st.info("No records yet — start the producer.")

st.divider()

# ===== AGENTIC DISCOVERY (pending taxonomy) =====
st.subheader("Agentic taxonomy discovery")
st.caption(
    "Off-seed domain proposals from the Context Agent — itself a thesis-publishable signal. "
    "Lives in `data/pending_taxonomy.log`."
)
tax = pending_taxonomy_summary()
t1, t2 = st.columns([1, 2])
with t1:
    st.metric("Total log lines", tax["total_lines"])
    st.metric("Unique proposals", tax["unique_proposals"])
with t2:
    st.markdown("**Latest 10 off-seed proposals**")
    if tax["latest"]:
        for ts, prop in tax["latest"]:
            st.write(f"`{ts[:19]}`  →  **{prop}**")
    else:
        st.write("_(no off-seed proposals logged yet — either the LLM keeps proposing on-seed categories, or the producer hasn't run)_")

st.divider()
st.caption(
    f"Last refresh: {datetime.datetime.now():%H:%M:%S}. "
    "Press R to refresh manually, or wait for the per-panel TTL to expire."
)
