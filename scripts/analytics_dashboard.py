"""
Analytics dashboard — deep, chart-heavy view of the moderation pipeline.

NOT the operator dashboard (`operator_dashboard.py` is the quick "is it
alive?" check). This is the data-exploration surface: 7 tabs, time-series
charts, per-domain comparisons, agentic-discovery analysis, Tier-2
agreement, user-level breakdown, and RAG monitoring.

Designed to replace the Kibana dashboard for thesis-grade analysis. All
queries hit Elasticsearch directly; no Kibana index pattern needed.

Run:
    streamlit run scripts/analytics_dashboard.py --server.port 8503

(operator_dashboard runs on 8501; analyst_chat on 8502; this on 8503.)

Each tab caches its queries with a 10-second TTL by default — change in
the sidebar.
"""

from __future__ import annotations

import datetime
import os
import sys
from collections import Counter
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shared_utils.config import (
    ES_HOST,
    INDEX_NAME,
    ACTIVE_MODEL,
    QDRANT_HOST,
    QDRANT_PORT,
    QDRANT_COLLECTION,
)

PENDING_TAXONOMY_LOG = ROOT / "data" / "pending_taxonomy.log"

# ---------------------------------------------------------------------------
# Page + sidebar
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Pipeline Analytics",
    layout="wide",
    initial_sidebar_state="expanded",
)

with st.sidebar:
    st.title("Pipeline Analytics")
    st.caption(
        "Deep analytics view. For the quick health check, run "
        "`operator_dashboard.py` on a different port."
    )

    st.divider()
    st.subheader("Query window")
    window_options = {
        "Last 15 min": 15,
        "Last 1 hour": 60,
        "Last 6 hours": 360,
        "Last 24 hours": 1440,
        "Last 7 days": 10080,
        "All time": None,
    }
    window_label = st.radio("Time range", list(window_options.keys()), index=1)
    window_minutes = window_options[window_label]

    st.divider()
    st.subheader("Cache")
    cache_ttl = st.slider("Refresh every (seconds)", 5, 60, 10, step=5)
    if st.button("Force refresh now"):
        st.cache_data.clear()

    st.divider()
    st.caption(f"ES: `{ES_HOST}`")
    st.caption(f"Index: `{INDEX_NAME}`")
    st.caption(f"Model: `{ACTIVE_MODEL}`")


# ---------------------------------------------------------------------------
# ES helpers (cached per-query)
# ---------------------------------------------------------------------------

def _es():
    from elasticsearch import Elasticsearch
    return Elasticsearch(ES_HOST, request_timeout=8)


def _time_filter(window_minutes: int | None) -> dict:
    if window_minutes is None:
        return {"match_all": {}}
    cutoff = (
        datetime.datetime.now() - datetime.timedelta(minutes=window_minutes)
    ).isoformat()
    return {"range": {"timestamp": {"gte": cutoff}}}


def _bucket_interval(window_minutes: int | None) -> str:
    if window_minutes is None or window_minutes >= 10080:
        return "1h"
    if window_minutes >= 1440:
        return "30m"
    if window_minutes >= 360:
        return "10m"
    if window_minutes >= 60:
        return "1m"
    return "30s"


@st.cache_data(ttl=10, show_spinner=False)
def query_total(window_minutes: int | None) -> int:
    try:
        es = _es()
        res = es.count(index=INDEX_NAME, body={"query": _time_filter(window_minutes)})
        return res["count"]
    except Exception:
        return 0


@st.cache_data(ttl=10, show_spinner=False)
def query_breakdowns(window_minutes: int | None) -> dict:
    try:
        es = _es()
        res = es.search(
            index=INDEX_NAME,
            body={
                "size": 0,
                "track_total_hits": True,
                "query": _time_filter(window_minutes),
                "aggs": {
                    "labels":       {"terms": {"field": "model_label", "size": 5}},
                    "domains":      {"terms": {"field": "env_domain", "size": 20}},
                    "platforms":    {"terms": {"field": "source_platform", "size": 10}},
                    "matches":      {"terms": {"field": "env_domain_match", "size": 5}},
                    "strictness":   {"terms": {"field": "env_strictness", "size": 5}},
                    "agent_dec":    {"terms": {"field": "agent_final_decision", "size": 8}},
                    "subgenres":    {"terms": {"field": "env_subgenre", "size": 20}},
                    "avg_t1":       {"avg":   {"field": "processing_time_ms"}},
                    "p95_t1":       {"percentiles": {"field": "processing_time_ms", "percents": [50, 95, 99]}},
                    "avg_t2":       {"avg":   {"field": "agent_latency_seconds"}},
                    "p95_t2":       {"percentiles": {"field": "agent_latency_seconds", "percents": [50, 95, 99]}},
                    "avg_conf":     {"avg":   {"field": "model_confidence"}},
                    "avg_mem_user": {"avg":   {"field": "agent_memory_user_msgs"}},
                    "avg_mem_thread": {"avg": {"field": "agent_memory_thread_msgs"}},
                },
            },
        )
        return res
    except Exception as exc:
        return {"error": str(exc)}


@st.cache_data(ttl=10, show_spinner=False)
def query_time_series(window_minutes: int | None) -> list[dict]:
    """Records bucketed by time + label, returned as a long-format list."""
    try:
        es = _es()
        res = es.search(
            index=INDEX_NAME,
            body={
                "size": 0,
                "query": _time_filter(window_minutes),
                "aggs": {
                    "ts": {
                        "date_histogram": {
                            "field": "timestamp",
                            "fixed_interval": _bucket_interval(window_minutes),
                            "min_doc_count": 0,
                        },
                        "aggs": {
                            "by_label": {"terms": {"field": "model_label"}},
                            "avg_lat":  {"avg": {"field": "processing_time_ms"}},
                        },
                    },
                },
            },
        )
        rows = []
        for bucket in res["aggregations"]["ts"]["buckets"]:
            ts = bucket["key_as_string"]
            for lbl in bucket["by_label"]["buckets"]:
                rows.append({"timestamp": ts, "model_label": lbl["key"], "count": lbl["doc_count"]})
            # if no labels yet, still record zero so the chart isn't gappy
            if not bucket["by_label"]["buckets"]:
                rows.append({"timestamp": ts, "model_label": "(none)", "count": 0})
        return rows
    except Exception as exc:
        return [{"error": str(exc)}]


@st.cache_data(ttl=10, show_spinner=False)
def query_domain_x_label(window_minutes: int | None) -> list[dict]:
    """For per-domain toxicity rate."""
    try:
        es = _es()
        res = es.search(
            index=INDEX_NAME,
            body={
                "size": 0,
                "query": _time_filter(window_minutes),
                "aggs": {
                    "domains": {
                        "terms": {"field": "env_domain", "size": 50},
                        "aggs": {
                            "by_label": {"terms": {"field": "model_label"}},
                        },
                    },
                },
            },
        )
        rows = []
        for d in res["aggregations"]["domains"]["buckets"]:
            domain = d["key"]
            total = d["doc_count"]
            label_counts = {l["key"]: l["doc_count"] for l in d["by_label"]["buckets"]}
            rows.append({
                "env_domain": domain,
                "total": total,
                "Normal":    label_counts.get("Normal", 0),
                "OFFENSIVE": label_counts.get("OFFENSIVE", 0),
                "HATE":      label_counts.get("HATE", 0),
                "toxic_pct": (label_counts.get("OFFENSIVE", 0) + label_counts.get("HATE", 0)) / max(total, 1) * 100,
            })
        return rows
    except Exception:
        return []


@st.cache_data(ttl=10, show_spinner=False)
def query_match_quality_over_time(window_minutes: int | None) -> list[dict]:
    try:
        es = _es()
        res = es.search(
            index=INDEX_NAME,
            body={
                "size": 0,
                "query": _time_filter(window_minutes),
                "aggs": {
                    "ts": {
                        "date_histogram": {
                            "field": "timestamp",
                            "fixed_interval": _bucket_interval(window_minutes),
                            "min_doc_count": 0,
                        },
                        "aggs": {
                            "by_match": {"terms": {"field": "env_domain_match"}},
                        },
                    },
                },
            },
        )
        rows = []
        for bucket in res["aggregations"]["ts"]["buckets"]:
            ts = bucket["key_as_string"]
            for m in bucket["by_match"]["buckets"]:
                rows.append({"timestamp": ts, "match_quality": m["key"], "count": m["doc_count"]})
        return rows
    except Exception:
        return []


@st.cache_data(ttl=10, show_spinner=False)
def query_off_seed_proposals(window_minutes: int | None) -> list[dict]:
    try:
        es = _es()
        res = es.search(
            index=INDEX_NAME,
            body={
                "size": 0,
                "query": {
                    "bool": {
                        "must": [_time_filter(window_minutes)],
                        "filter": [{"term": {"env_domain_match": "unknown"}}],
                    }
                },
                "aggs": {
                    "raw": {"terms": {"field": "env_domain_raw.keyword", "size": 30}},
                },
            },
        )
        return [
            {"proposal": b["key"], "count": b["doc_count"]}
            for b in res["aggregations"]["raw"]["buckets"]
            if b["key"]
        ]
    except Exception:
        return []


@st.cache_data(ttl=10, show_spinner=False)
def query_top_authors(window_minutes: int | None, top: int = 25) -> list[dict]:
    try:
        es = _es()
        res = es.search(
            index=INDEX_NAME,
            body={
                "size": 0,
                "query": _time_filter(window_minutes),
                "aggs": {
                    "authors": {
                        "terms": {"field": "author_name.keyword", "size": top},
                        "aggs": {
                            "by_label": {"terms": {"field": "model_label"}},
                        },
                    },
                },
            },
        )
        rows = []
        for a in res["aggregations"]["authors"]["buckets"]:
            label_counts = {l["key"]: l["doc_count"] for l in a["by_label"]["buckets"]}
            total = a["doc_count"]
            toxic = label_counts.get("OFFENSIVE", 0) + label_counts.get("HATE", 0)
            rows.append({
                "author":     a["key"],
                "msgs":       total,
                "Normal":     label_counts.get("Normal", 0),
                "OFFENSIVE":  label_counts.get("OFFENSIVE", 0),
                "HATE":       label_counts.get("HATE", 0),
                "toxic_pct":  toxic / max(total, 1) * 100,
            })
        return rows
    except Exception:
        return []


@st.cache_data(ttl=10, show_spinner=False)
def query_tier_agreement(window_minutes: int | None) -> list[dict]:
    """Tier-1 model_label vs Tier-2 agent_final_decision crosstab (where reviewed)."""
    try:
        es = _es()
        res = es.search(
            index=INDEX_NAME,
            body={
                "size": 0,
                "query": {
                    "bool": {
                        "must": [_time_filter(window_minutes)],
                        "filter": [{"term": {"agent_reviewed": True}}],
                    }
                },
                "aggs": {
                    "tier1": {
                        "terms": {"field": "model_label"},
                        "aggs": {
                            "tier2": {"terms": {"field": "agent_final_decision"}},
                        },
                    },
                },
            },
        )
        rows = []
        for t1 in res["aggregations"]["tier1"]["buckets"]:
            for t2 in t1["tier2"]["buckets"]:
                rows.append({"tier1": t1["key"], "tier2": t2["key"], "count": t2["doc_count"]})
        return rows
    except Exception:
        return []


@st.cache_data(ttl=10, show_spinner=False)
def query_recent_records(limit: int = 50) -> list[dict]:
    try:
        es = _es()
        res = es.search(
            index=INDEX_NAME,
            body={
                "query": {"match_all": {}},
                "sort": [{"timestamp": {"order": "desc"}}],
                "size": limit,
            },
        )
        return [hit["_source"] for hit in res["hits"]["hits"]]
    except Exception:
        return []


@st.cache_data(ttl=10, show_spinner=False)
def query_qdrant_count() -> tuple[bool, int, str]:
    try:
        import requests
        r = requests.get(
            f"http://{QDRANT_HOST}:{QDRANT_PORT}/collections/{QDRANT_COLLECTION}",
            timeout=2,
        )
        if r.status_code == 200:
            d = r.json().get("result", {})
            n = d.get("points_count") or d.get("vectors_count") or 0
            return True, n, ""
        if r.status_code == 404:
            return False, 0, "collection not created yet (run scripts/seed_rag_from_csv.py)"
        return False, 0, f"HTTP {r.status_code}"
    except Exception as exc:
        return False, 0, str(exc)[:80]


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.title("Pipeline analytics")
st.caption(
    f"Window: **{window_label}** · Cache TTL: **{cache_ttl}s**. "
    "Each tab queries Elasticsearch on demand. Sidebar controls apply to all tabs."
)

total = query_total(window_minutes)
agg = query_breakdowns(window_minutes)

if "error" in agg:
    st.error(f"ES query failed: {agg['error']}")
    st.stop()


# ---------------------------------------------------------------------------
# Top metrics row (always visible)
# ---------------------------------------------------------------------------

m1, m2, m3, m4, m5, m6 = st.columns(6)

with m1:
    st.metric("Records in window", f"{total:,}")
with m2:
    st.metric("Domains seen", len(agg["aggregations"]["domains"]["buckets"]))
with m3:
    st.metric("Platforms", len(agg["aggregations"]["platforms"]["buckets"]))
with m4:
    t1 = agg["aggregations"]["avg_t1"]["value"]
    st.metric("Avg Tier-1 latency", f"{(t1 or 0):.1f} ms")
with m5:
    t2 = agg["aggregations"]["avg_t2"]["value"]
    st.metric("Avg Tier-2 latency", f"{(t2 or 0):.2f} s")
with m6:
    c = agg["aggregations"]["avg_conf"]["value"]
    st.metric("Avg Tier-1 confidence", f"{(c or 0):.2f}")

st.divider()


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab_overview, tab_time, tab_domains, tab_agentic, tab_tier2, tab_users, tab_rag, tab_raw = st.tabs(
    ["Overview", "Time series", "Domains", "Agentic discovery", "Tier-2 analytics", "Users", "RAG", "Raw records"]
)


# ============== TAB 1 — Overview ==============
with tab_overview:
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Tier-1 label breakdown")
        label_data = {b["key"]: b["doc_count"] for b in agg["aggregations"]["labels"]["buckets"]}
        if label_data:
            fig = px.pie(
                names=list(label_data.keys()),
                values=list(label_data.values()),
                color=list(label_data.keys()),
                color_discrete_map={"Normal": "#2ecc71", "OFFENSIVE": "#f39c12", "HATE": "#e74c3c"},
                hole=0.4,
            )
            fig.update_layout(height=350, margin=dict(t=10, b=10, l=10, r=10))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No records in window.")

    with col2:
        st.subheader("Platform distribution")
        plat_data = {b["key"]: b["doc_count"] for b in agg["aggregations"]["platforms"]["buckets"]}
        if plat_data:
            fig = px.bar(x=list(plat_data.keys()), y=list(plat_data.values()), color=list(plat_data.keys()))
            fig.update_layout(height=350, showlegend=False, xaxis_title="", yaxis_title="records",
                              margin=dict(t=10, b=10, l=10, r=10))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No records in window.")

    st.subheader("Domain volume — top 20")
    dom_data = {b["key"]: b["doc_count"] for b in agg["aggregations"]["domains"]["buckets"]}
    if dom_data:
        df = pd.DataFrame({"domain": list(dom_data.keys()), "count": list(dom_data.values())})
        df = df.sort_values("count", ascending=True).tail(20)
        fig = px.bar(df, x="count", y="domain", orientation="h", color="count", color_continuous_scale="Viridis")
        fig.update_layout(height=500, margin=dict(t=10, b=10, l=10, r=10))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No domains yet.")


# ============== TAB 2 — Time series ==============
with tab_time:
    st.subheader("Records over time, broken down by Tier-1 label")
    ts_rows = query_time_series(window_minutes)
    if ts_rows and "error" not in ts_rows[0]:
        df = pd.DataFrame(ts_rows)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        fig = px.area(
            df, x="timestamp", y="count", color="model_label",
            color_discrete_map={"Normal": "#2ecc71", "OFFENSIVE": "#f39c12", "HATE": "#e74c3c", "(none)": "#bdc3c7"},
        )
        fig.update_layout(height=420, margin=dict(t=10, b=10, l=10, r=10),
                          xaxis_title="", yaxis_title="records per bucket")
        st.plotly_chart(fig, use_container_width=True)
    elif ts_rows and "error" in ts_rows[0]:
        st.error(ts_rows[0]["error"])
    else:
        st.info("No time-series data yet.")

    st.divider()
    st.subheader("Tier-1 latency percentiles (this window)")
    pcts = agg["aggregations"].get("p95_t1", {}).get("values", {})
    if pcts:
        fig = go.Figure()
        for k, v in pcts.items():
            if v is None:
                continue
            fig.add_trace(go.Bar(x=[f"P{int(float(k))}"], y=[v], name=f"P{int(float(k))}"))
        fig.update_layout(
            height=300, showlegend=False, yaxis_title="ms",
            margin=dict(t=10, b=10, l=10, r=10),
        )
        st.plotly_chart(fig, use_container_width=True)
    st.caption(
        f"Tier-1 avg {(agg['aggregations']['avg_t1']['value'] or 0):.1f} ms · "
        f"Tier-2 avg {(agg['aggregations']['avg_t2']['value'] or 0):.2f} s"
    )

    st.divider()
    st.subheader("Tier-2 latency percentiles (this window, only reviewed records)")
    pcts2 = agg["aggregations"].get("p95_t2", {}).get("values", {})
    if pcts2 and any(v is not None for v in pcts2.values()):
        fig = go.Figure()
        for k, v in pcts2.items():
            if v is None:
                continue
            fig.add_trace(go.Bar(x=[f"P{int(float(k))}"], y=[v], name=f"P{int(float(k))}"))
        fig.update_layout(
            height=300, showlegend=False, yaxis_title="seconds",
            margin=dict(t=10, b=10, l=10, r=10),
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No reviewed records in this window yet — run the batch judge.")


# ============== TAB 3 — Domains ==============
with tab_domains:
    st.subheader("Per-domain toxicity rate")
    st.caption("`toxic_pct` = (OFFENSIVE + HATE) / total. Domains with high rates indicate either active toxicity or DistilBERT misfires worth auditing.")

    dxl = query_domain_x_label(window_minutes)
    if dxl:
        df = pd.DataFrame(dxl)
        df = df.sort_values("toxic_pct", ascending=False)
        st.dataframe(df, use_container_width=True, height=420)

        st.divider()
        st.subheader("Toxicity rate per domain (chart)")
        fig = px.bar(
            df.head(20),
            x="env_domain", y="toxic_pct",
            hover_data=["total", "Normal", "OFFENSIVE", "HATE"],
            color="toxic_pct", color_continuous_scale="Reds",
        )
        fig.update_layout(height=400, margin=dict(t=10, b=10, l=10, r=10),
                          xaxis_title="", yaxis_title="% toxic")
        st.plotly_chart(fig, use_container_width=True)

        st.divider()
        st.subheader("Stacked label distribution per domain")
        df_long = df.head(15).melt(
            id_vars=["env_domain"],
            value_vars=["Normal", "OFFENSIVE", "HATE"],
            var_name="label",
            value_name="count",
        )
        fig = px.bar(
            df_long, x="env_domain", y="count", color="label",
            color_discrete_map={"Normal": "#2ecc71", "OFFENSIVE": "#f39c12", "HATE": "#e74c3c"},
        )
        fig.update_layout(height=400, margin=dict(t=10, b=10, l=10, r=10),
                          xaxis_title="", yaxis_title="records")
        st.plotly_chart(fig, use_container_width=True)

    sub_buckets = agg["aggregations"].get("subgenres", {}).get("buckets", [])
    if sub_buckets:
        st.divider()
        st.subheader("Top subgenres")
        sub_data = {b["key"]: b["doc_count"] for b in sub_buckets if b["key"]}
        if sub_data:
            df = pd.DataFrame({"subgenre": list(sub_data.keys()), "count": list(sub_data.values())})
            df = df.sort_values("count", ascending=True).tail(15)
            fig = px.bar(df, x="count", y="subgenre", orientation="h")
            fig.update_layout(height=400, margin=dict(t=10, b=10, l=10, r=10))
            st.plotly_chart(fig, use_container_width=True)


# ============== TAB 4 — Agentic discovery ==============
with tab_agentic:
    st.subheader("Match-quality breakdown")
    st.caption(
        "`exact`/`alias` = the LLM proposed a domain that landed cleanly on the seed taxonomy. "
        "`fuzzy` = SequenceMatcher pulled it into a canonical. "
        "`unknown` = genuinely off-seed — these are the **agentic-discovery signal** for your thesis."
    )

    match_data = {b["key"]: b["doc_count"] for b in agg["aggregations"]["matches"]["buckets"]}
    if match_data:
        col1, col2 = st.columns([1, 1])
        with col1:
            fig = px.pie(
                names=list(match_data.keys()),
                values=list(match_data.values()),
                color=list(match_data.keys()),
                color_discrete_map={"exact": "#27ae60", "alias": "#3498db", "fuzzy": "#f39c12", "unknown": "#e74c3c"},
                hole=0.4,
            )
            fig.update_layout(height=350, margin=dict(t=10, b=10, l=10, r=10))
            st.plotly_chart(fig, use_container_width=True)
        with col2:
            total_m = sum(match_data.values())
            for k, v in sorted(match_data.items(), key=lambda x: -x[1]):
                st.metric(k, f"{v:,}", delta=f"{v / total_m * 100:.1f}% of records", delta_color="off")

    st.divider()
    st.subheader("Match quality over time")
    mq_ts = query_match_quality_over_time(window_minutes)
    if mq_ts:
        df = pd.DataFrame(mq_ts)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        fig = px.area(
            df, x="timestamp", y="count", color="match_quality",
            color_discrete_map={"exact": "#27ae60", "alias": "#3498db", "fuzzy": "#f39c12", "unknown": "#e74c3c"},
        )
        fig.update_layout(height=350, margin=dict(t=10, b=10, l=10, r=10),
                          xaxis_title="", yaxis_title="records")
        st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("Off-seed proposals (`env_domain_match=unknown`)")
    st.caption("These are categories the LLM proposed that the seed taxonomy didn't anticipate. Each row is one thesis-publishable discovery.")
    off_seed = query_off_seed_proposals(window_minutes)
    if off_seed:
        df = pd.DataFrame(off_seed)
        st.dataframe(df, use_container_width=True, height=400)
    else:
        st.info("No off-seed proposals in this window — either the LLM is converging on seed categories (a positive signal), or no records yet.")

    st.divider()
    st.subheader("Strictness assignment")
    strict_data = {b["key"]: b["doc_count"] for b in agg["aggregations"]["strictness"]["buckets"]}
    if strict_data:
        fig = px.pie(
            names=list(strict_data.keys()),
            values=list(strict_data.values()),
            color=list(strict_data.keys()),
            color_discrete_map={"low": "#3498db", "medium": "#f39c12", "high": "#e74c3c"},
            hole=0.4,
        )
        fig.update_layout(height=300, margin=dict(t=10, b=10, l=10, r=10))
        st.plotly_chart(fig, use_container_width=True)


# ============== TAB 5 — Tier-2 analytics ==============
with tab_tier2:
    st.subheader("Tier-2 verdict distribution (reviewed records only)")
    dec_data = {b["key"]: b["doc_count"] for b in agg["aggregations"]["agent_dec"]["buckets"]}
    if dec_data:
        col1, col2 = st.columns([1, 1])
        with col1:
            fig = px.pie(names=list(dec_data.keys()), values=list(dec_data.values()), hole=0.4)
            fig.update_layout(height=350, margin=dict(t=10, b=10, l=10, r=10))
            st.plotly_chart(fig, use_container_width=True)
        with col2:
            total_d = sum(dec_data.values())
            for k, v in sorted(dec_data.items(), key=lambda x: -x[1]):
                st.metric(k, f"{v:,}", delta=f"{v / total_d * 100:.1f}%", delta_color="off")
    else:
        st.info("No Tier-2 verdicts yet — run `python src/agents/xai_batch_judge.py`.")

    st.divider()
    st.subheader("Tier-1 ↔ Tier-2 agreement heatmap")
    st.caption("Rows = DistilBERT label; columns = Tier-2 judge verdict. The diagonal-ish pattern tells you how often Tier-2 agrees with Tier-1.")
    agree = query_tier_agreement(window_minutes)
    if agree:
        df = pd.DataFrame(agree)
        pivot = df.pivot(index="tier1", columns="tier2", values="count").fillna(0)
        fig = px.imshow(
            pivot.values,
            x=list(pivot.columns), y=list(pivot.index),
            text_auto=True, aspect="auto",
            color_continuous_scale="Blues",
        )
        fig.update_layout(height=400, margin=dict(t=10, b=10, l=10, r=10),
                          xaxis_title="Tier-2 verdict", yaxis_title="Tier-1 label")
        st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("Memory context size — recent reviewed records")
    mem_user = agg["aggregations"].get("avg_mem_user", {}).get("value")
    mem_thread = agg["aggregations"].get("avg_mem_thread", {}).get("value")
    if mem_user is not None and mem_thread is not None:
        c1, c2 = st.columns(2)
        with c1:
            st.metric("Avg user history msgs", f"{mem_user:.2f}")
        with c2:
            st.metric("Avg thread context msgs", f"{mem_thread:.2f}")
    else:
        st.info("No memory-augmented verdicts yet — needs MEMORY_ENABLED=True and a batch judge run.")


# ============== TAB 6 — Users ==============
with tab_users:
    st.subheader("Top authors by volume")
    authors = query_top_authors(window_minutes, top=30)
    if authors:
        df = pd.DataFrame(authors)
        st.dataframe(df, use_container_width=True, height=480)

        st.divider()
        st.subheader("Top 15 by toxicity rate (min 5 messages)")
        df_t = df[df["msgs"] >= 5].sort_values("toxic_pct", ascending=False).head(15)
        if not df_t.empty:
            fig = px.bar(
                df_t, x="author", y="toxic_pct",
                hover_data=["msgs", "Normal", "OFFENSIVE", "HATE"],
                color="toxic_pct", color_continuous_scale="Reds",
            )
            fig.update_layout(height=400, margin=dict(t=10, b=10, l=10, r=10),
                              xaxis_title="", yaxis_title="% toxic")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Not enough volume per author yet.")
    else:
        st.info("No author data yet.")


# ============== TAB 7 — RAG ==============
with tab_rag:
    st.subheader("Qdrant collection status")
    ok, n, msg = query_qdrant_count()
    if ok:
        st.metric("Points in collection", f"{n:,}")
        st.caption(f"Collection: `{QDRANT_COLLECTION}` @ {QDRANT_HOST}:{QDRANT_PORT}")
    else:
        st.error(f"Qdrant: {msg}")
        st.info("To populate: `python scripts/seed_rag_from_csv.py thesis_final_benchmark.csv --apply`")

    st.divider()
    st.subheader("Qdrant built-in dashboard")
    st.caption(f"Full vector search UI is at: http://{QDRANT_HOST}:{QDRANT_PORT}/dashboard")


# ============== TAB 8 — Raw records ==============
with tab_raw:
    st.subheader("Most recent 50 records")
    recs = query_recent_records(50)
    if recs:
        rows = []
        for r in recs:
            rows.append({
                "time": (r.get("timestamp") or "")[:19],
                "platform": r.get("source_platform", "?"),
                "domain": r.get("env_domain", "?"),
                "sub": r.get("env_subgenre", "") or "",
                "match": r.get("env_domain_match", "?"),
                "strictness": r.get("env_strictness", "?"),
                "author": (r.get("author_name") or "?")[:24],
                "Tier-1": r.get("model_label", "?"),
                "conf": f"{(r.get('model_confidence') or 0):.2f}",
                "Tier-2": r.get("agent_final_decision") or "—",
                "memory": "y" if r.get("agent_memory_used") else "—",
                "text": (r.get("text") or "")[:120],
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, height=620)
    else:
        st.info("No records yet.")


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.divider()
st.caption(
    f"Last refresh attempt: {datetime.datetime.now():%H:%M:%S}. "
    "Use the sidebar to change the window or force a refresh."
)
