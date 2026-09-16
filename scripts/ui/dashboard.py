"""
dashboard.py — Moderation Operator Console (read-only).

A single-page, tabbed operator console for the two-tier hate-speech moderation
pipeline. It is built so a reviewer can watch the system work end to end — live
status, every pipeline stage, the model's explanations, the RAG precedents, the
multi-agent decomposition, and the offline evaluation — all in one window.

Where the data comes from
    Live tabs (Overview, Live Monitor, Record Inspector) read Elasticsearch,
    which holds Tier-1, Tier-2 baseline, explanations, and memory fields.
    The Evaluation, RAG, and Multi-Agent tabs read the benchmark CSV
    (thesis_benchmark_eval.csv), because the RAG and multi-agent verdicts are
    produced by the offline replay scripts and live there, not in ES. The RAG
    tab also queries Qdrant directly for live similarity search.

This console is monitoring only — it never writes to the pipeline. The
companion analyst chat (scripts/ui/analyst_chat.py) is the interactive surface.

Run:
    streamlit run scripts/ui/dashboard.py
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from shared_utils.config import (
    ES_HOST, INDEX_NAME, ACTIVE_MODEL,
    QDRANT_HOST, QDRANT_PORT, QDRANT_COLLECTION,
    MEMORY_ENABLED, RAG_ENABLED, RETRIEVAL_BACKEND,
)

PENDING_TAXONOMY_LOG = ROOT / "data" / "pending_taxonomy.log"
BENCHMARK_CSV = ROOT / "thesis_benchmark_eval.csv"

st.set_page_config(page_title="Moderation Operator Console", layout="wide")


# ===========================================================================
# Constants and small presentation helpers
# ===========================================================================

# Tier-1 stores "Normal" (capitalised); ground truth uses upper-case NORMAL.
LABEL_COLORS = {
    "Normal": "#2e7d46", "NORMAL": "#2e7d46",
    "OFFENSIVE": "#c77f1a",
    "HATE": "#b23b3b",
}
VERDICT_COLORS = {
    "Correct": "#2e7d46",
    "False Positive": "#c77f1a",
    "False Negative": "#b23b3b",
    "Parsing Error": "#777777",
}
MATCH_COLORS = {"exact": "#2e7d46", "alias": "#3b6fb2", "fuzzy": "#c77f1a", "unknown": "#b23b3b"}
BADGE_COLORS = {"ok": "#2e7d46", "warn": "#b8860b", "bad": "#a32020", "neutral": "#555555"}

TOXIC = {"HATE", "OFFENSIVE"}

WINDOWS = {
    "Last 1 hour":   (60,    "1m"),
    "Last 6 hours":  (360,   "5m"),
    "Last 24 hours": (1440,  "30m"),
    "Last 7 days":   (10080, "3h"),
    "All time":      (None,  "1d"),
}

# Variants compared in the Evaluation tab. (display name, CSV column).
EVAL_VARIANTS = [
    ("Tier-2 baseline",            "agent_final_decision"),
    ("Tier-2 + memory",            "agent_final_decision_with_memory"),
    ("Tier-2 + RAG",               "agent_final_decision_with_rag"),
    ("Tier-2 + LLM-Wiki",          "agent_final_decision_with_wiki"),
    ("Tier-2 multi-agent",         "agent_final_decision_with_multi_agent"),
]


def badge(text: str, kind: str = "neutral") -> str:
    """A small, calm text badge. No emoji anywhere in this console by design."""
    color = BADGE_COLORS.get(kind, BADGE_COLORS["neutral"])
    return (
        f"<span style='background:{color};color:#fff;padding:2px 9px;"
        f"border-radius:4px;font-size:0.78rem;font-weight:600;"
        f"letter-spacing:0.2px;white-space:nowrap'>{text}</span>"
    )


def _age_seconds(ts) -> float | None:
    try:
        t = datetime.datetime.fromisoformat(str(ts).replace("Z", ""))
        return (datetime.datetime.now() - t).total_seconds()
    except Exception:
        return None


def humanize_age(secs: float | None) -> str:
    if secs is None:
        return "unknown"
    secs = max(0, int(secs))
    if secs < 60:
        return f"{secs} seconds ago"
    if secs < 3600:
        return f"{secs // 60} minutes ago"
    if secs < 86400:
        return f"{secs // 3600} hours ago"
    return f"{secs // 86400} days ago"


def current_window():
    name = st.session_state.get("window", "Last 24 hours")
    minutes, interval = WINDOWS[name]
    return name, minutes, interval


def _range_query(minutes):
    if minutes is None:
        return {"match_all": {}}
    cutoff = (datetime.datetime.now() - datetime.timedelta(minutes=minutes)).isoformat()
    return {"range": {"timestamp": {"gte": cutoff}}}


# ===========================================================================
# Cached data access
# ===========================================================================

@st.cache_resource(show_spinner=False)
def get_es():
    from elasticsearch import Elasticsearch
    return Elasticsearch(ES_HOST, request_timeout=8)


@st.cache_data(ttl=5, show_spinner=False)
def probe_health() -> dict:
    """Granular, honest health probe. Reports each component separately and —
    crucially — how long ago the most recent record landed, which is the real
    'is the pipeline doing anything right now' signal."""
    out = {
        "es_up": False, "es_count": 0, "latest_ts": None, "latest_age_s": None,
        "qdrant_up": False, "qdrant_collection": False, "qdrant_points": 0,
        "ollama_up": False, "ollama_model": False,
    }
    try:
        from elasticsearch import Elasticsearch
        es = Elasticsearch(ES_HOST, request_timeout=2)
        if es.ping():
            out["es_up"] = True
            try:
                out["es_count"] = es.count(index=INDEX_NAME)["count"]
            except Exception:
                out["es_count"] = 0
            try:
                r = es.search(index=INDEX_NAME, body={
                    "size": 1, "sort": [{"timestamp": {"order": "desc"}}],
                    "_source": ["timestamp"],
                })
                hits = r["hits"]["hits"]
                if hits:
                    out["latest_ts"] = hits[0]["_source"].get("timestamp")
                    out["latest_age_s"] = _age_seconds(out["latest_ts"])
            except Exception:
                pass
    except Exception:
        pass

    try:
        import requests
        r = requests.get(f"http://{QDRANT_HOST}:{QDRANT_PORT}/collections", timeout=2)
        out["qdrant_up"] = r.status_code == 200
    except Exception:
        pass
    if out["qdrant_up"]:
        try:
            import requests
            r = requests.get(f"http://{QDRANT_HOST}:{QDRANT_PORT}/collections/{QDRANT_COLLECTION}", timeout=2)
            if r.status_code == 200:
                out["qdrant_collection"] = True
                out["qdrant_points"] = (r.json().get("result", {}) or {}).get("points_count", 0) or 0
        except Exception:
            pass

    try:
        import requests
        r = requests.get("http://localhost:11434/api/tags", timeout=2)
        if r.status_code == 200:
            out["ollama_up"] = True
            names = [m.get("name", "") for m in r.json().get("models", [])]
            base = ACTIVE_MODEL.split(":")[0]
            out["ollama_model"] = any(n == ACTIVE_MODEL or base in n for n in names)
    except Exception:
        pass
    return out


@st.cache_data(ttl=8, show_spinner=False)
def live_aggs(minutes) -> dict:
    es = get_es()
    body = {
        "size": 0, "track_total_hits": True, "query": _range_query(minutes),
        "aggs": {
            "labels":    {"terms": {"field": "model_label"}},
            "platforms": {"terms": {"field": "source_platform"}},
            "domains":   {"terms": {"field": "env_domain", "size": 15}},
            "matches":   {"terms": {"field": "env_domain_match"}},
            "agent":     {"terms": {"field": "agent_final_decision"}},
            "t1":        {"avg": {"field": "processing_time_ms"}},
            "t2":        {"avg": {"field": "agent_latency_seconds"}},
            "mem_user":  {"avg": {"field": "agent_memory_user_msgs"}},
            "reviewed":  {"filter": {"term": {"agent_reviewed": True}}},
        },
    }
    r = es.search(index=INDEX_NAME, body=body)
    a = r["aggregations"]
    buckets = lambda key: {b["key"]: b["doc_count"] for b in a[key]["buckets"]}
    return {
        "total":     r["hits"]["total"]["value"],
        "labels":    buckets("labels"),
        "platforms": buckets("platforms"),
        "domains":   buckets("domains"),
        "matches":   buckets("matches"),
        "agent":     buckets("agent"),
        "t1_ms":     a["t1"]["value"] or 0.0,
        "t2_s":      a["t2"]["value"] or 0.0,
        "mem_user":  a["mem_user"]["value"] or 0.0,
        "reviewed":  a["reviewed"]["doc_count"],
    }


@st.cache_data(ttl=8, show_spinner=False)
def volume_series(minutes, interval) -> pd.DataFrame:
    es = get_es()
    body = {
        "size": 0, "query": _range_query(minutes),
        "aggs": {"vol": {"date_histogram": {
            "field": "timestamp", "fixed_interval": interval, "min_doc_count": 1,
        }}},
    }
    try:
        r = es.search(index=INDEX_NAME, body=body)
        rows = [{"time": b["key_as_string"], "records": b["doc_count"]}
                for b in r["aggregations"]["vol"]["buckets"]]
        df = pd.DataFrame(rows)
        if not df.empty:
            df["time"] = pd.to_datetime(df["time"])
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=8, show_spinner=False)
def recent_records(minutes, size=25) -> list[dict]:
    es = get_es()
    r = es.search(index=INDEX_NAME, body={
        "query": _range_query(minutes),
        "sort": [{"timestamp": {"order": "desc"}}], "size": size,
    })
    return [h["_source"] for h in r["hits"]["hits"]]


@st.cache_data(ttl=8, show_spinner=False)
def search_records(text, author, reviewed_only, size=40) -> list[dict]:
    es = get_es()
    must = []
    if text:
        must.append({"match": {"text": text}})
    if author:
        must.append({"match": {"author_name": author}})
    if reviewed_only:
        must.append({"term": {"agent_reviewed": True}})
    query = {"bool": {"must": must}} if must else {"match_all": {}}
    r = es.search(index=INDEX_NAME, body={
        "query": query, "sort": [{"timestamp": {"order": "desc"}}], "size": size,
    })
    return [h["_source"] for h in r["hits"]["hits"]]


@st.cache_data(ttl=30, show_spinner=False)
def qdrant_stats() -> dict:
    out = {"up": False, "points": 0, "dim": None, "distance": None}
    try:
        import requests
        r = requests.get(f"http://{QDRANT_HOST}:{QDRANT_PORT}/collections/{QDRANT_COLLECTION}", timeout=3)
        if r.status_code == 200:
            res = r.json().get("result", {}) or {}
            out["up"] = True
            out["points"] = res.get("points_count", 0) or 0
            vectors = (((res.get("config", {}) or {}).get("params", {}) or {}).get("vectors", {}) or {})
            out["dim"] = vectors.get("size")
            out["distance"] = vectors.get("distance")
    except Exception:
        pass
    return out


@st.cache_data(ttl=60, show_spinner=False)
def load_benchmark() -> pd.DataFrame:
    if not BENCHMARK_CSV.exists():
        return pd.DataFrame()
    df = pd.read_csv(BENCHMARK_CSV, dtype=str, keep_default_na=False)
    return df


# ===========================================================================
# Evaluation metrics  (mirrors scripts/eval/check_results.py — keep in sync)
# ===========================================================================

def effective_label(model_label: str, decision: str) -> str:
    d = str(decision).strip().lower()
    if d == "correct":
        return model_label
    if d == "false positive":
        return "NORMAL"
    if d == "false negative":
        return "OFFENSIVE"
    return model_label


def compute_metrics(pred: pd.Series, gt: pd.Series) -> dict:
    acc = (pred == gt).mean()
    pb, gb = pred.isin(TOXIC), gt.isin(TOXIC)
    bacc = (pb == gb).mean()
    tp = int((pb & gb).sum())
    fp = int((pb & ~gb).sum())
    fn = int((~pb & gb).sum())
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return {"n": int(len(pred)), "acc": acc, "bacc": bacc,
            "prec": prec, "rec": rec, "f1": f1, "tp": tp, "fp": fp, "fn": fn}


def labelled_benchmark(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "human_ground_truth" not in df.columns:
        return pd.DataFrame()
    d = df.copy()
    d["human_ground_truth"] = d["human_ground_truth"].fillna("").astype(str).str.strip().str.upper()
    d["model_label"] = d["model_label"].astype(str).str.strip().str.upper()
    return d[d["human_ground_truth"].isin(["NORMAL", "OFFENSIVE", "HATE"])]


def variant_predictions(d: pd.DataFrame, col: str) -> pd.Series:
    sub = d[d[col].astype(str).str.strip().str.lower().replace("nan", "").str.len() > 0]
    if sub.empty:
        return pd.Series(dtype=str)
    return sub.apply(lambda x: effective_label(x["model_label"], x[col]), axis=1)


# ===========================================================================
# Sidebar
# ===========================================================================

with st.sidebar:
    st.subheader("Operator console")
    st.caption("Read-only monitoring for the moderation pipeline. The console "
               "never changes the pipeline; it only observes it.")

    st.selectbox("Time window", list(WINDOWS.keys()), index=2, key="window",
                 help="Applies to the live tabs (Overview, Live Monitor, Record Inspector).")

    st.selectbox(
        "Live refresh", [0, 5, 10, 30],
        format_func=lambda s: "Off" if s == 0 else f"Every {s} seconds",
        index=2, key="cadence",
        help="How often the live panels re-query Elasticsearch. The analytical "
             "tabs (Evaluation, RAG, Multi-Agent) do not auto-refresh.",
    )

    st.divider()
    st.caption("Pipeline configuration")
    st.markdown(
        f"Memory-augmented judging: {badge('On', 'ok') if MEMORY_ENABLED else badge('Off', 'warn')}<br>"
        f"Live RAG injection: {badge('On', 'ok') if RAG_ENABLED else badge('Off', 'neutral')}",
        unsafe_allow_html=True,
    )
    st.caption(f"Tier-2 model: {ACTIVE_MODEL}")
    st.caption(f"Index: {INDEX_NAME}")

    st.divider()
    st.caption("Other surfaces")
    st.markdown(
        "- [Kibana](http://localhost:5601) — ad-hoc Elasticsearch exploration\n"
        "- [Qdrant dashboard](http://localhost:6333/dashboard) — vector store\n"
        "- Analyst chat — ask the pipeline questions in plain English:\n"
        "  `streamlit run scripts/ui/analyst_chat.py --server.port 8502`"
    )


# ===========================================================================
# System status strip  (rendered above the tabs, on every view)
# ===========================================================================

def render_status_body():
    h = probe_health()

    # Translate the freshness signal into honest, human language.
    age = h["latest_age_s"]
    if not h["es_up"]:
        flow_badge, flow_note = badge("Unknown", "neutral"), "Elasticsearch unreachable."
    elif age is None:
        flow_badge, flow_note = badge("No data", "bad"), "No records in the index yet."
    elif age < 120:
        flow_badge, flow_note = badge("Flowing", "ok"), f"Newest record {humanize_age(age)}."
    elif age < 3600:
        flow_badge, flow_note = badge("Quiet", "warn"), f"Newest record {humanize_age(age)}."
    else:
        flow_badge, flow_note = badge("Idle", "warn"), f"Newest record {humanize_age(age)}."

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        with st.container(border=True):
            st.caption("Elasticsearch")
            st.markdown(badge("Online", "ok") if h["es_up"] else badge("Offline", "bad"),
                        unsafe_allow_html=True)
            st.caption(f"{h['es_count']:,} records indexed" if h["es_up"]
                       else "Start the stack: docker-compose up -d")

    with c2:
        with st.container(border=True):
            st.caption("Data flow")
            st.markdown(flow_badge, unsafe_allow_html=True)
            st.caption(flow_note)

    with c3:
        with st.container(border=True):
            st.caption("Qdrant (RAG store)")
            if not h["qdrant_up"]:
                st.markdown(badge("Offline", "bad"), unsafe_allow_html=True)
                st.caption("Vector store unreachable.")
            elif not h["qdrant_collection"]:
                st.markdown(badge("No collection", "warn"), unsafe_allow_html=True)
                st.caption("Service up; collection not seeded yet.")
            elif h["qdrant_points"] == 0:
                st.markdown(badge("Empty", "warn"), unsafe_allow_html=True)
                st.caption("Collection exists but holds no precedents.")
            else:
                st.markdown(badge("Online", "ok"), unsafe_allow_html=True)
                st.caption(f"{h['qdrant_points']:,} precedents indexed")

    with c4:
        with st.container(border=True):
            st.caption("Ollama (Tier-2 judge)")
            if not h["ollama_up"]:
                st.markdown(badge("Offline", "bad"), unsafe_allow_html=True)
                st.caption("LLM server not reachable on :11434.")
            elif h["ollama_model"]:
                st.markdown(badge("Ready", "ok"), unsafe_allow_html=True)
                st.caption(f"Server up; model '{ACTIVE_MODEL}' available.")
            else:
                st.markdown(badge("Model missing", "warn"), unsafe_allow_html=True)
                st.caption(f"Server up; '{ACTIVE_MODEL}' not listed.")


# ===========================================================================
# Tab 1 — Overview
# ===========================================================================

def _stage_row(name, what, status_badge, coverage):
    with st.container(border=True):
        col_a, col_b, col_c = st.columns([3, 1.2, 1.6])
        with col_a:
            st.markdown(f"**{name}**")
            st.caption(what)
        with col_b:
            st.markdown(status_badge, unsafe_allow_html=True)
        with col_c:
            st.caption(coverage)


def render_overview_body():
    _, minutes, interval = current_window()
    h = probe_health()
    if not h["es_up"]:
        st.error("Elasticsearch is not reachable. Start the stack with "
                 "`docker-compose up -d`, then this view will populate.")
        return

    try:
        a = live_aggs(minutes)
    except Exception as e:
        st.error(f"Could not read Elasticsearch aggregations: {e}")
        return

    total = a["total"]
    toxic = a["labels"].get("OFFENSIVE", 0) + a["labels"].get("HATE", 0)
    toxic_rate = (toxic / total * 100) if total else 0.0

    st.markdown("#### At a glance")
    st.caption("Headline numbers for the selected time window. These update live "
               "as the producer and Tier-1 processor write new records.")
    m = st.columns(5)
    m[0].metric("Records in window", f"{total:,}")
    m[1].metric("Tier-2 reviewed", f"{a['reviewed']:,}")
    m[2].metric("Flagged as toxic", f"{toxic_rate:.1f}%",
                help="Share of records Tier-1 labelled OFFENSIVE or HATE.")
    m[3].metric("Avg Tier-1 latency", f"{a['t1_ms']:.0f} ms")
    m[4].metric("Avg Tier-2 latency", f"{a['t2_s']:.1f} s" if a["t2_s"] else "n/a")

    st.markdown("#### Records over time")
    vol = volume_series(minutes, interval)
    if vol.empty:
        st.info("No records in the selected window yet. Widen the time window, or "
                "check that the producer and Tier-1 processor are running.")
    else:
        fig = px.area(vol, x="time", y="records")
        fig.update_traces(line_color="#3b6fb2", fillcolor="rgba(59,111,178,0.15)")
        fig.update_layout(height=260, margin=dict(t=10, b=10, l=10, r=10),
                          xaxis_title="", yaxis_title="records")
        st.plotly_chart(fig, width="stretch")

    st.markdown("#### Pipeline stages")
    st.caption("What each stage does and whether it is active right now. Stages 1-4 "
               "run live; RAG and Multi-Agent are evaluated offline (see their tabs).")

    bm = load_benchmark()
    ma_rows = 0
    if not bm.empty and "agent_final_decision_with_multi_agent" in bm.columns:
        ma_rows = int((bm["agent_final_decision_with_multi_agent"].astype(str).str.strip().str.len() > 0).sum())

    # 1. Ingest
    age = h["latest_age_s"]
    if age is None:
        ingest = badge("No data", "bad")
    elif age < 120:
        ingest = badge("Flowing", "ok")
    else:
        ingest = badge("Idle", "warn")
    _stage_row("1. Ingestion", "Pulls live chat from YouTube, Twitch and Reddit and "
               "publishes a universal record to Kafka.", ingest,
               f"Newest record {humanize_age(age)}")

    # 2. Tier-1
    _stage_row("2. Tier-1 — DistilBERT", "Fast static classifier; labels every "
               "message Normal / OFFENSIVE / HATE with a confidence.",
               badge("Active", "ok") if total else badge("Idle", "warn"),
               f"{total:,} classified · {a['t1_ms']:.0f} ms avg")

    # 3. Tier-2
    cov = (a["reviewed"] / total * 100) if total else 0.0
    _stage_row("3. Tier-2 — LLM judge", "Audits low-confidence records, confirms or "
               "overturns Tier-1, and writes a written explanation.",
               badge("Active", "ok") if a["reviewed"] else badge("Not yet run", "warn"),
               f"{a['reviewed']:,} reviewed ({cov:.0f}% of window)")

    # 4. Memory
    _stage_row("4. Temporal memory", "Gives the judge the author's recent history, "
               "the thread context, and a behavioural fingerprint.",
               badge("On", "ok") if MEMORY_ENABLED else badge("Off", "warn"),
               f"{a['mem_user']:.1f} prior msgs/record avg")

    # 5. RAG
    qs = qdrant_stats()
    if not qs["up"]:
        rag_badge = badge("Store offline", "bad")
    elif qs["points"] == 0:
        rag_badge = badge("Not seeded", "warn")
    else:
        rag_badge = badge("Live: On", "ok") if RAG_ENABLED else badge("Eval-ready", "neutral")
    _stage_row("5. Retrieval (RAG)", "Retrieves semantically similar past cases from "
               "Qdrant as precedents for the judge.", rag_badge,
               f"{qs['points']:,} precedents in store")

    # 6. Multi-agent
    _stage_row("6. Multi-agent", "Splits the judge into Risk Scorer, Behavior "
               "Profiler, Escalator and Supervisor specialists.",
               badge("Evaluated offline", "neutral") if ma_rows else badge("Not run", "warn"),
               f"{ma_rows:,} records judged (benchmark)")


# ===========================================================================
# Tab 2 — Live Monitor
# ===========================================================================

def _pie(d, title, color_map=None):
    fig = px.pie(names=list(d), values=list(d.values()), hole=0.45, title=title,
                 color=list(d), color_discrete_map=color_map or {})
    fig.update_layout(height=330, margin=dict(t=45, b=10, l=10, r=10))
    return fig


def render_live_body():
    _, minutes, _ = current_window()
    h = probe_health()
    if not h["es_up"]:
        st.error("Elasticsearch is not reachable. Start the stack with `docker-compose up -d`.")
        return
    try:
        a = live_aggs(minutes)
    except Exception as e:
        st.error(f"Could not read Elasticsearch aggregations: {e}")
        return

    if a["total"] == 0:
        st.info("No records in the selected window. Widen the time window in the "
                "sidebar, or start a producer to bring in live chat.")
        return

    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(_pie(a["labels"], "Tier-1 labels", LABEL_COLORS), width="stretch")
    with c2:
        if a["platforms"]:
            fig = px.bar(x=list(a["platforms"]), y=list(a["platforms"].values()),
                         title="Source platforms", color=list(a["platforms"]))
            fig.update_layout(height=330, showlegend=False, xaxis_title="",
                              yaxis_title="records", margin=dict(t=45, b=10, l=10, r=10))
            st.plotly_chart(fig, width="stretch")

    c3, c4 = st.columns(2)
    with c3:
        if a["domains"]:
            dd = (pd.DataFrame({"domain": list(a["domains"]), "n": list(a["domains"].values())})
                  .sort_values("n").tail(15))
            fig = px.bar(dd, x="n", y="domain", orientation="h", title="Top conversation domains")
            fig.update_layout(height=400, margin=dict(t=45, b=10, l=10, r=10),
                              xaxis_title="records", yaxis_title="")
            st.plotly_chart(fig, width="stretch")
    with c4:
        if a["matches"]:
            st.plotly_chart(_pie(a["matches"], "Taxonomy match quality", MATCH_COLORS),
                            width="stretch")
            st.caption("How the agent's free-text domain guess mapped onto the seed "
                       "taxonomy. 'unknown' marks an off-seed discovery.")

    if a["agent"]:
        st.markdown("#### Tier-2 verdicts in this window")
        st.caption("Once the batch judge has run, this shows how often it confirmed "
                   "Tier-1 (Correct) versus overturned it (False Positive / Negative).")
        fig = px.bar(x=list(a["agent"]), y=list(a["agent"].values()),
                     color=list(a["agent"]), color_discrete_map=VERDICT_COLORS)
        fig.update_layout(height=300, showlegend=False, xaxis_title="",
                          yaxis_title="records", margin=dict(t=10, b=10, l=10, r=10))
        st.plotly_chart(fig, width="stretch")

    st.markdown("#### Most recent records")
    rows = recent_records(minutes, size=25)
    table = [{
        "Time": (r.get("timestamp") or "")[:19].replace("T", "  "),
        "Platform": r.get("source_platform", "?"),
        "Domain": r.get("env_domain", "?"),
        "Author": (r.get("author_name") or "?")[:22],
        "Tier-1": r.get("model_label", "?"),
        "Conf.": f"{float(r.get('model_confidence') or 0):.2f}",
        "Tier-2": r.get("agent_final_decision") or "—",
        "Message": (r.get("text") or "")[:90],
    } for r in rows]
    st.dataframe(pd.DataFrame(table), width="stretch", height=420, hide_index=True)

    if PENDING_TAXONOMY_LOG.exists():
        st.markdown("#### Agentic off-seed discoveries")
        st.caption("Domains the Context Agent proposed that were not in the seed "
                   "taxonomy — evidence of open-vocabulary discovery by the LLM.")
        lines = PENDING_TAXONOMY_LOG.read_text(encoding="utf-8").splitlines()
        props = [ln.split("\t", 1)[1] for ln in lines if "\t" in ln]
        cc1, cc2 = st.columns([1, 2])
        cc1.metric("Off-seed events", f"{len(props):,}")
        cc1.metric("Distinct categories", f"{len(set(props)):,}")
        if props:
            top = pd.Series(props).value_counts().head(15).rename("count")
            cc2.dataframe(top, width="stretch")


# ===========================================================================
# Tab 3 — Record Inspector
# ===========================================================================

def _kv(label, value):
    st.markdown(f"<span style='color:#888'>{label}</span><br>{value}",
                unsafe_allow_html=True)


def _verdict_badge(verdict):
    kind = {"Correct": "ok", "False Positive": "warn",
            "False Negative": "bad", "Parsing Error": "neutral"}.get(verdict, "neutral")
    return badge(verdict or "not reviewed", kind if verdict else "neutral")


def render_inspector():
    st.markdown("#### Record inspector")
    st.caption("Trace a single message through every stage of the pipeline — the "
               "Tier-1 call, the Tier-2 judge and its explanation, the memory it "
               "used, and (for records in the benchmark) the RAG precedents and the "
               "multi-agent breakdown.")

    f1, f2, f3 = st.columns([2, 2, 1])
    text_q = f1.text_input("Filter by message text", placeholder="e.g. noob, scam, slur…")
    author_q = f2.text_input("Filter by author name", placeholder="e.g. lery28")
    reviewed_only = f3.checkbox("Reviewed only", value=True,
                                help="Show only records the Tier-2 judge has audited "
                                     "(these carry an explanation).")

    h = probe_health()
    if not h["es_up"]:
        st.error("Elasticsearch is not reachable.")
        return
    try:
        records = search_records(text_q.strip(), author_q.strip(), reviewed_only, size=40)
    except Exception as e:
        st.error(f"Search failed: {e}")
        return
    if not records:
        st.info("No records matched. Loosen the filters or turn off 'Reviewed only'.")
        return

    def _opt(i, r):
        return (f"{(r.get('timestamp') or '')[:19].replace('T',' ')}  ·  "
                f"{(r.get('author_name') or '?')[:18]}  ·  "
                f"{r.get('model_label','?')}  ·  {(r.get('text') or '')[:50]}")

    idx = st.selectbox("Select a record", range(len(records)),
                       format_func=lambda i: _opt(i, records[i]))
    r = records[idx]

    # ---- the message itself ----
    with st.container(border=True):
        st.markdown("**Message**")
        st.markdown(f"> {r.get('text') or '(empty)'}")
        cols = st.columns(4)
        with cols[0]: _kv("Author", r.get("author_name", "?"))
        with cols[1]: _kv("Platform", r.get("source_platform", "?"))
        with cols[2]: _kv("Thread", (r.get("thread_title") or r.get("thread_id") or "?")[:28])
        with cols[3]: _kv("Time", (r.get("timestamp") or "?")[:19].replace("T", " "))

    # ---- Stage 1: ingest context ----
    with st.container(border=True):
        st.markdown("**Stage 1 — Ingestion context**")
        st.caption("Environment the message was posted in, as discovered by the Context Agent.")
        c = st.columns(4)
        with c[0]: _kv("Domain", r.get("env_domain", "?"))
        with c[1]: _kv("Raw guess", r.get("env_domain_raw", "?"))
        with c[2]:
            mk = r.get("env_domain_match", "?")
            kind = {"exact": "ok", "alias": "ok", "fuzzy": "warn", "unknown": "bad"}.get(mk, "neutral")
            st.markdown(f"<span style='color:#888'>Taxonomy match</span><br>{badge(mk, kind)}",
                        unsafe_allow_html=True)
        with c[3]: _kv("Strictness", r.get("env_strictness", "?"))
        if r.get("env_strictness_reasoning"):
            st.caption(f"Why this strictness: {r['env_strictness_reasoning']}")

    # ---- Stage 2: Tier-1 ----
    with st.container(border=True):
        st.markdown("**Stage 2 — Tier-1 DistilBERT**")
        conf = float(r.get("model_confidence") or 0)
        cc = st.columns([1, 3])
        with cc[0]:
            lbl = r.get("model_label", "?")
            st.markdown(f"<span style='color:#888'>Label</span><br>"
                        f"{badge(lbl, {'Normal':'ok','OFFENSIVE':'warn','HATE':'bad'}.get(lbl,'neutral'))}",
                        unsafe_allow_html=True)
        with cc[1]:
            st.caption(f"Confidence: {conf:.2f}  ·  processed in "
                       f"{float(r.get('processing_time_ms') or 0):.0f} ms")
            st.progress(min(max(conf, 0.0), 1.0))

    # ---- Stage 3: Tier-2 ----
    with st.container(border=True):
        st.markdown("**Stage 3 — Tier-2 LLM judge**")
        if not r.get("agent_reviewed"):
            st.caption("This record has not been audited by the Tier-2 judge yet. "
                       "Run the batch judge, or turn on 'Reviewed only' above.")
        else:
            cc = st.columns([1, 3])
            with cc[0]:
                st.markdown(f"<span style='color:#888'>Verdict on Tier-1</span><br>"
                            f"{_verdict_badge(r.get('agent_final_decision'))}",
                            unsafe_allow_html=True)
            with cc[1]:
                st.caption(f"Model: {r.get('agent_model_used') or '?'}  ·  "
                           f"{float(r.get('agent_latency_seconds') or 0):.1f} s")
            st.markdown("**Explanation**")
            st.info(r.get("agent_explanation") or "(no explanation recorded)")

    # ---- Stage 4: memory ----
    if r.get("agent_memory_used"):
        with st.container(border=True):
            st.markdown("**Stage 4 — Temporal memory used by the judge**")
            c = st.columns(2)
            c[0].metric("Author history messages", int(r.get("agent_memory_user_msgs") or 0))
            c[1].metric("Thread context messages", int(r.get("agent_memory_thread_msgs") or 0))
            if r.get("agent_memory_user_profile"):
                st.caption(f"Behavioural fingerprint: {r['agent_memory_user_profile']}")

    # ---- benchmark-only stages: RAG + LLM-Wiki + multi-agent ----
    st.caption("Note: the RAG, LLM-Wiki, and multi-agent verdicts are computed offline "
               "on the evaluation benchmark, so they appear below only for records that "
               "are part of that benchmark.")
    bm = load_benchmark()
    row = None
    if not bm.empty and r.get("message_id"):
        match = bm[bm["message_id"] == r.get("message_id")]
        if not match.empty:
            row = match.iloc[0]

    if row is None:
        st.caption("This record is not in the evaluation benchmark, so the RAG, "
                   "LLM-Wiki, and multi-agent verdicts are not available for it. Open the "
                   "RAG, LLM-Wiki, and Multi-Agent tabs to see those stages across the benchmark.")
        return

    rag_dec = str(row.get("agent_final_decision_with_rag", "")).strip()
    if rag_dec:
        with st.container(border=True):
            st.markdown("**Stage 5 — Retrieval-augmented judging (RAG)**")
            cc = st.columns([1, 3])
            with cc[0]:
                st.markdown(f"<span style='color:#888'>Verdict with RAG</span><br>"
                            f"{_verdict_badge(rag_dec)}", unsafe_allow_html=True)
            with cc[1]:
                st.caption(f"Precedents retrieved: {row.get('agent_retrieval_count', '0')}")
                ids = str(row.get("agent_retrieved_precedent_ids", "")).strip()
                if ids:
                    st.caption(f"Precedent ids: {ids[:160]}")
            if str(row.get("agent_explanation_with_rag", "")).strip():
                st.info(row.get("agent_explanation_with_rag"))

    wiki_dec = str(row.get("agent_final_decision_with_wiki", "")).strip()
    if wiki_dec:
        with st.container(border=True):
            st.markdown("**Stage 5b — Curated-knowledge judging (LLM-Wiki)**")
            cc = st.columns([1, 3])
            with cc[0]:
                st.markdown(f"<span style='color:#888'>Verdict with LLM-Wiki</span><br>"
                            f"{_verdict_badge(wiki_dec)}", unsafe_allow_html=True)
            with cc[1]:
                st.caption(f"Knowledge entries used: {row.get('agent_wiki_count', '0')}")
                pages = str(row.get("agent_wiki_pages_used", "")).strip()
                if pages:
                    st.caption(f"Pages: {pages[:160]}")
            if str(row.get("agent_explanation_with_wiki", "")).strip():
                st.info(row.get("agent_explanation_with_wiki"))

    ma_dec = str(row.get("agent_final_decision_with_multi_agent", "")).strip()
    if ma_dec:
        with st.container(border=True):
            st.markdown("**Stage 6 — Multi-agent decomposition**")
            c = st.columns(3)
            try:
                rs = float(row.get("agent_ma_risk_score") or 0)
            except Exception:
                rs = 0.0
            c[0].metric("Content risk score", f"{rs:.2f}")
            c[1].metric("Behaviour risk", str(row.get("agent_ma_behavior_risk", "?")))
            c[2].metric("Routing", str(row.get("agent_ma_escalation_action", "?")))

            with st.expander("Per-agent reasoning"):
                st.markdown("**Risk Scorer** — scores the message content in isolation.")
                st.caption(row.get("agent_ma_risk_rationale", "—") or "—")
                st.markdown("**Behavior Profiler** — characterises the author from history.")
                st.caption(row.get("agent_ma_profile_summary", "—") or "—")
                st.markdown("**Escalator** — routes the case (clear / flag / human review).")
                st.caption(row.get("agent_ma_escalation_rationale", "—") or "—")
                st.markdown(f"Escalate to human: **{row.get('agent_ma_escalate_to_human', '?')}**")

            cc = st.columns([1, 3])
            with cc[0]:
                st.markdown(f"<span style='color:#888'>Supervisor verdict</span><br>"
                            f"{_verdict_badge(ma_dec)}", unsafe_allow_html=True)
            with cc[1]:
                if str(row.get("agent_explanation_with_multi_agent", "")).strip():
                    st.info(row.get("agent_explanation_with_multi_agent"))


# ===========================================================================
# Tab 4 — Evaluation
# ===========================================================================

def render_evaluation():
    st.markdown("#### Evaluation")
    st.caption("How each pipeline variant scores against the hand-labelled benchmark "
               f"({BENCHMARK_CSV.name}). The set is heavily imbalanced toward Normal, "
               "so we lead with the toxic-class F1, precision and recall — not raw "
               "accuracy, where an 'always Normal' baseline already looks strong.")

    bm = load_benchmark()
    d = labelled_benchmark(bm)
    if d.empty:
        st.warning("No labelled rows found in the benchmark CSV. Fill in the "
                   "'human_ground_truth' column to enable evaluation.")
        return

    n_toxic = int(d["human_ground_truth"].isin(TOXIC).sum())
    cap = st.columns(3)
    cap[0].metric("Labelled records", f"{len(d):,}")
    cap[1].metric("Toxic (HATE + OFFENSIVE)", f"{n_toxic:,}")
    cap[2].metric("Normal", f"{len(d) - n_toxic:,}")

    # ---- comparison table ----
    rows = []
    base = compute_metrics(d["model_label"], d["human_ground_truth"])
    rows.append({"Variant": "Tier-1 DistilBERT", "n": base["n"],
                 "3-class acc": base["acc"] * 100, "Toxic-vs-normal acc": base["bacc"] * 100,
                 "Toxic precision": base["prec"], "Toxic recall": base["rec"],
                 "Toxic F1": base["f1"]})

    baseline_f1 = None
    for name, col in EVAL_VARIANTS:
        if col not in d.columns:
            continue
        pred = variant_predictions(d, col)
        if pred.empty:
            continue
        gt = d.loc[pred.index, "human_ground_truth"]
        mt = compute_metrics(pred, gt)
        if col == "agent_final_decision":
            baseline_f1 = mt["f1"]
        rows.append({"Variant": name, "n": mt["n"],
                     "3-class acc": mt["acc"] * 100, "Toxic-vs-normal acc": mt["bacc"] * 100,
                     "Toxic precision": mt["prec"], "Toxic recall": mt["rec"],
                     "Toxic F1": mt["f1"]})

    table = pd.DataFrame(rows)
    st.dataframe(
        table, width="stretch", hide_index=True,
        column_config={
            "3-class acc":          st.column_config.NumberColumn(format="%.1f%%", help="Exact NORMAL/OFFENSIVE/HATE match"),
            "Toxic-vs-normal acc":  st.column_config.NumberColumn(format="%.1f%%"),
            "Toxic precision":      st.column_config.NumberColumn(format="%.2f"),
            "Toxic recall":         st.column_config.NumberColumn(format="%.2f"),
            "Toxic F1":             st.column_config.ProgressColumn(format="%.2f", min_value=0.0, max_value=1.0),
        },
    )
    st.caption("Toxic F1 is the headline metric. Higher is better; the progress bar "
               "is scaled 0–1. Accuracy columns are shown for completeness only.")

    # ---- deltas vs baseline ----
    if baseline_f1 is not None:
        st.markdown("#### Contribution of each stage (Toxic F1 vs Tier-2 baseline)")
        delta_cols = st.columns(3)
        for i, (name, col) in enumerate([v for v in EVAL_VARIANTS if v[1] != "agent_final_decision"]):
            if col not in d.columns:
                continue
            pred = variant_predictions(d, col)
            if pred.empty:
                continue
            gt = d.loc[pred.index, "human_ground_truth"]
            f1 = compute_metrics(pred, gt)["f1"]
            delta_cols[i % 3].metric(name, f"{f1:.2f}", delta=f"{f1 - baseline_f1:+.2f}")

    # ---- confusion matrix ----
    st.markdown("#### Confusion matrix")
    pickable = [("Tier-1 DistilBERT", "model_label")] + [
        (n, c) for n, c in EVAL_VARIANTS if c in d.columns and not variant_predictions(d, c).empty
    ]
    choice = st.selectbox("Variant", [p[0] for p in pickable])
    chosen_col = dict(pickable)[choice]

    if chosen_col == "model_label":
        pred = d["model_label"]
        gt = d["human_ground_truth"]
    else:
        pred = variant_predictions(d, chosen_col)
        gt = d.loc[pred.index, "human_ground_truth"]

    mode = st.radio("Granularity", ["Toxic vs normal", "Three classes"], horizontal=True)
    if mode == "Toxic vs normal":
        pr = pred.isin(TOXIC).map({True: "Toxic", False: "Normal"})
        gtb = gt.isin(TOXIC).map({True: "Toxic", False: "Normal"})
        order = ["Normal", "Toxic"]
    else:
        pr, gtb, order = pred, gt, ["NORMAL", "OFFENSIVE", "HATE"]

    cm = pd.crosstab(gtb, pr).reindex(index=order, columns=order, fill_value=0)
    fig = px.imshow(cm, text_auto=True, color_continuous_scale="Blues",
                    labels=dict(x="Predicted", y="Ground truth", color="records"),
                    x=order, y=order, aspect="auto")
    fig.update_layout(height=380, margin=dict(t=20, b=10, l=10, r=10), coloraxis_showscale=False)
    st.plotly_chart(fig, width="stretch")

    # ---- per-record explanation explorer ----
    st.markdown("#### Compare verdicts on one record")
    st.caption("Pick a record to see what every variant decided and why. By default "
               "this lists records where the variants disagree — the interesting cases.")
    present = [c for _, c in EVAL_VARIANTS if c in d.columns]
    only_disagree = st.checkbox("Only records where variants disagree", value=True)

    def _eff(row, col):
        val = str(row.get(col, "")).strip()
        return effective_label(row["model_label"], val) if val else "—"

    view = d.copy()
    if only_disagree and present:
        def _disagrees(row):
            labels = {_eff(row, c) for c in present if str(row.get(c, "")).strip()}
            labels.add(row["model_label"])
            return len(labels) > 1
        view = view[view.apply(_disagrees, axis=1)]

    if view.empty:
        st.info("No records to show with the current filter.")
        return

    view = view.head(200)
    sel = st.selectbox(
        "Record", range(len(view)),
        format_func=lambda i: f"{view.iloc[i]['human_ground_truth']}  ·  "
                              f"{(view.iloc[i].get('author_name') or '?')[:16]}  ·  "
                              f"{(view.iloc[i].get('text') or '')[:60]}",
    )
    row = view.iloc[sel]
    st.markdown(f"> {row.get('text') or '(empty)'}")
    st.caption(f"Ground truth: **{row['human_ground_truth']}**  ·  "
               f"Tier-1: **{row['model_label']}**")

    expl_cols = {
        "agent_final_decision": ("Tier-2 baseline", "agent_explanation"),
        "agent_final_decision_with_memory": ("Tier-2 + memory", "agent_explanation_with_memory"),
        "agent_final_decision_with_rag": ("Tier-2 + RAG", "agent_explanation_with_rag"),
        "agent_final_decision_with_wiki": ("Tier-2 + LLM-Wiki", "agent_explanation_with_wiki"),
        "agent_final_decision_with_multi_agent": ("Tier-2 multi-agent", "agent_explanation_with_multi_agent"),
    }
    for col, (name, expl_col) in expl_cols.items():
        if col not in d.columns:
            continue
        dec = str(row.get(col, "")).strip()
        if not dec:
            continue
        eff = effective_label(row["model_label"], dec)
        correct = eff == row["human_ground_truth"]
        with st.container(border=True):
            st.markdown(f"**{name}** — verdict on Tier-1: {_verdict_badge(dec)}  "
                        f"which maps to label **{eff}**  "
                        f"{badge('correct', 'ok') if correct else badge('wrong', 'bad')}",
                        unsafe_allow_html=True)
            if expl_col in d.columns and str(row.get(expl_col, "")).strip():
                st.caption(str(row.get(expl_col)))


# ===========================================================================
# Tab 5 — RAG
# ===========================================================================

def render_rag():
    st.markdown("#### Retrieval-augmented moderation (RAG)")
    st.caption("The judge can be given semantically similar past cases as precedents. "
               "Vectors live in Qdrant; the embedder is sentence-transformers MiniLM "
               "(384-dim, cosine). Below: the live vector store, a similarity search "
               "you can drive, and RAG's measured contribution on the benchmark.")

    qs = qdrant_stats()
    m = st.columns(4)
    m[0].metric("Vector store", "Online" if qs["up"] else "Offline")
    m[1].metric("Precedents indexed", f"{qs['points']:,}")
    m[2].metric("Vector dimension", qs["dim"] or "—")
    m[3].metric("Distance", str(qs["distance"] or "—"))
    st.markdown(
        f"Live RAG injection into the judge is "
        f"{badge('On', 'ok') if RAG_ENABLED else badge('Off', 'neutral')} "
        f"(env flag RAG_ENABLED). Evaluation always uses RAG regardless of this flag.",
        unsafe_allow_html=True,
    )

    st.markdown("#### Try a similarity search")
    st.caption("Paste any message; the console embeds it and asks Qdrant for the "
               "closest precedents — exactly what the judge receives at retrieval time. "
               "The first search loads the embedding model and can take 20–40 seconds.")
    query = st.text_area("Message", placeholder="e.g. go back to where you came from", height=80)
    k = st.slider("Precedents to retrieve", 1, 10, 5)

    if st.button("Search precedents", type="primary"):
        if not qs["up"] or qs["points"] == 0:
            st.warning("Qdrant is offline or holds no precedents. Seed it first: "
                       "`python scripts/setup/seed_rag_from_csv.py thesis_benchmark_eval.csv --apply`.")
        elif not query.strip():
            st.warning("Enter a message to search for.")
        else:
            try:
                with st.spinner("Embedding the query and searching Qdrant…"):
                    from shared_utils.rag import retrieve_similar
                    hits = retrieve_similar(query.strip(), k=k)
            except Exception as e:
                st.error(f"Search failed: {e}")
                hits = []
            if not hits:
                st.info("No precedents scored above the similarity threshold (0.55). "
                        "Try a longer or more characteristic message.")
            else:
                for hit in hits:
                    p = hit.get("payload", {}) or {}
                    with st.container(border=True):
                        st.markdown(f"Similarity **{hit.get('score', 0):.2f}**  ·  "
                                    f"Tier-1 {p.get('model_label', '?')}  ·  "
                                    f"domain {p.get('env_domain', '?')}")
                        st.markdown(f"> {p.get('text') or '(empty)'}")

    # ---- RAG contribution from the benchmark ----
    st.markdown("#### RAG's contribution on the benchmark")
    bm = load_benchmark()
    d = labelled_benchmark(bm)
    if d.empty or "agent_final_decision_with_rag" not in d.columns:
        st.info("No RAG verdicts in the benchmark yet. Run "
                "`scripts/eval/replay_with_rag.py` to populate them.")
        return

    if "agent_retrieval_count" in d.columns:
        counts = pd.to_numeric(d["agent_retrieval_count"], errors="coerce").dropna()
        if not counts.empty:
            with_prec = int((counts > 0).sum())
            cc = st.columns(2)
            cc[0].metric("Records with at least one precedent", f"{with_prec:,}",
                         help=f"out of {len(counts):,} judged with RAG")
            cc[1].metric("Avg precedents retrieved", f"{counts.mean():.1f}")
            fig = px.histogram(counts, nbins=int(counts.max()) + 1 if counts.max() else 1,
                               title="Precedents retrieved per record")
            fig.update_layout(height=280, showlegend=False, xaxis_title="precedents",
                              yaxis_title="records", margin=dict(t=40, b=10, l=10, r=10))
            st.plotly_chart(fig, width="stretch")

    base_pred = variant_predictions(d, "agent_final_decision")
    rag_pred = variant_predictions(d, "agent_final_decision_with_rag")
    if not base_pred.empty and not rag_pred.empty:
        bf = compute_metrics(base_pred, d.loc[base_pred.index, "human_ground_truth"])["f1"]
        rf = compute_metrics(rag_pred, d.loc[rag_pred.index, "human_ground_truth"])["f1"]
        cc = st.columns(2)
        cc[0].metric("Tier-2 baseline — Toxic F1", f"{bf:.2f}")
        cc[1].metric("Tier-2 + RAG — Toxic F1", f"{rf:.2f}", delta=f"{rf - bf:+.2f}")


# ===========================================================================
# Tab 6 — Multi-Agent
# ===========================================================================

def render_multi_agent():
    st.markdown("#### Multi-agent decomposition")
    st.caption("Instead of one monolithic judge, four specialists run in sequence. "
               "Each is a focused LLM call; the Supervisor reconciles their signals "
               "into the final verdict. This view summarises their behaviour across "
               "the benchmark.")

    chain = [
        ("Risk Scorer", "Scores the message content in isolation, 0 to 1."),
        ("Behavior Profiler", "Characterises the author from their history (low/medium/high)."),
        ("Escalator", "Routes the case: auto-clear, auto-flag, or human review."),
        ("Supervisor", "Reconciles all signals into the final verdict and explanation."),
    ]
    cols = st.columns(4)
    for col, (name, what) in zip(cols, chain):
        with col:
            with st.container(border=True):
                st.markdown(f"**{name}**")
                st.caption(what)

    bm = load_benchmark()
    d = labelled_benchmark(bm)
    col = "agent_final_decision_with_multi_agent"
    if d.empty or col not in d.columns:
        st.info("No multi-agent verdicts in the benchmark yet. Run "
                "`scripts/eval/replay_with_multi_agent.py` to populate them.")
        return
    sub = d[d[col].astype(str).str.strip().str.len() > 0]
    if sub.empty:
        st.info("No multi-agent verdicts in the benchmark yet.")
        return

    # ---- accuracy vs baseline ----
    base_pred = variant_predictions(d, "agent_final_decision")
    ma_pred = variant_predictions(d, col)
    cc = st.columns(3)
    cc[0].metric("Records judged", f"{len(sub):,}")
    if not base_pred.empty:
        bf = compute_metrics(base_pred, d.loc[base_pred.index, "human_ground_truth"])["f1"]
        mf = compute_metrics(ma_pred, d.loc[ma_pred.index, "human_ground_truth"])["f1"]
        cc[1].metric("Baseline — Toxic F1", f"{bf:.2f}")
        cc[2].metric("Multi-agent — Toxic F1", f"{mf:.2f}", delta=f"{mf - bf:+.2f}")

    # ---- distributions ----
    g1, g2 = st.columns(2)
    with g1:
        risk = pd.to_numeric(sub.get("agent_ma_risk_score"), errors="coerce").dropna()
        if not risk.empty:
            fig = px.histogram(risk, nbins=20, title="Content risk score (Risk Scorer)")
            fig.update_layout(height=300, showlegend=False, xaxis_title="risk score",
                              yaxis_title="records", margin=dict(t=40, b=10, l=10, r=10))
            st.plotly_chart(fig, width="stretch")
    with g2:
        if "agent_ma_behavior_risk" in sub.columns:
            beh = sub["agent_ma_behavior_risk"].astype(str).str.strip().str.lower()
            beh = beh[beh.isin(["low", "medium", "high"])].value_counts().reindex(
                ["low", "medium", "high"]).fillna(0)
            fig = px.bar(x=beh.index, y=beh.values, title="Behaviour risk (Behavior Profiler)",
                         color=beh.index,
                         color_discrete_map={"low": "#2e7d46", "medium": "#c77f1a", "high": "#b23b3b"})
            fig.update_layout(height=300, showlegend=False, xaxis_title="",
                              yaxis_title="records", margin=dict(t=40, b=10, l=10, r=10))
            st.plotly_chart(fig, width="stretch")

    g3, g4 = st.columns(2)
    with g3:
        if "agent_ma_escalation_action" in sub.columns:
            esc = sub["agent_ma_escalation_action"].astype(str).str.strip().str.lower()
            esc = esc[esc.str.len() > 0].value_counts()
            if not esc.empty:
                fig = px.pie(names=esc.index, values=esc.values, hole=0.45,
                             title="Routing decisions (Escalator)")
                fig.update_layout(height=320, margin=dict(t=45, b=10, l=10, r=10))
                st.plotly_chart(fig, width="stretch")
    with g4:
        if "agent_ma_escalate_to_human" in sub.columns:
            esc_h = sub["agent_ma_escalate_to_human"].astype(str).str.strip().str.lower()
            n_yes = int(esc_h.isin(["true", "1", "yes"]).sum())
            rate = (n_yes / len(sub) * 100) if len(sub) else 0
            st.metric("Sent to human review", f"{n_yes:,}", help=f"{rate:.1f}% of judged records")
            st.caption("The Escalator flags ambiguous cases for a human moderator "
                       "rather than auto-deciding — a safety valve the thesis can "
                       "report on directly.")

    # ---- per-record agent signals ----
    st.markdown("#### Inspect one record's agent signals")
    view = sub.head(200)
    sel = st.selectbox(
        "Record", range(len(view)),
        format_func=lambda i: f"{view.iloc[i]['human_ground_truth']}  ·  "
                              f"{(view.iloc[i].get('text') or '')[:60]}",
    )
    row = view.iloc[sel]
    st.markdown(f"> {row.get('text') or '(empty)'}")
    st.caption(f"Ground truth: **{row['human_ground_truth']}**  ·  Tier-1: **{row['model_label']}**")
    cc = st.columns(3)
    try:
        rs = float(row.get("agent_ma_risk_score") or 0)
    except Exception:
        rs = 0.0
    cc[0].metric("Content risk", f"{rs:.2f}")
    cc[1].metric("Behaviour risk", str(row.get("agent_ma_behavior_risk", "?")))
    cc[2].metric("Routing", str(row.get("agent_ma_escalation_action", "?")))
    with st.expander("Per-agent reasoning", expanded=True):
        st.markdown("**Risk Scorer**")
        st.caption(row.get("agent_ma_risk_rationale", "—") or "—")
        st.markdown("**Behavior Profiler**")
        st.caption(row.get("agent_ma_profile_summary", "—") or "—")
        st.markdown("**Escalator**")
        st.caption(row.get("agent_ma_escalation_rationale", "—") or "—")
        st.markdown(f"**Supervisor verdict:** {_verdict_badge(str(row.get(col)).strip())}",
                    unsafe_allow_html=True)
        if str(row.get("agent_explanation_with_multi_agent", "")).strip():
            st.info(row.get("agent_explanation_with_multi_agent"))


# ===========================================================================
# Page layout
# ===========================================================================

st.title("Moderation Operator Console")
st.caption("A live and historical view of the two-tier moderation pipeline: every "
           "stage, the model's reasoning, the retrieved precedents, the multi-agent "
           "breakdown, and the evaluation — in one place.")

cadence = st.session_state.get("cadence", 10)
run_every = cadence if cadence else None

# ===========================================================================
# Tab 7 — LLM-Wiki (curated knowledge backend)
# ===========================================================================

def render_wiki():
    st.markdown("#### LLM-Wiki — curated knowledge backend")
    st.caption("The switchable alternative to RAG. Instead of retrieving similar past "
               "cases, the judge consults a curated knowledge base (core policy, domain "
               "rules, a dog-whistle glossary, and edge-case rulings) under wiki/. Below: "
               "the knowledge base, a lookup you can drive, and Wiki's measured contribution.")

    try:
        from shared_utils.wiki import _load_entries
        entries = _load_entries()
    except Exception as e:
        entries = []
        st.error(f"Could not load the knowledge base: {e}")

    kinds = {}
    for e in entries:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    m = st.columns(4)
    m[0].metric("Knowledge entries", f"{len(entries):,}")
    m[1].metric("Policy + domain", kinds.get("policy", 0) + kinds.get("domain", 0))
    m[2].metric("Glossary", kinds.get("glossary", 0))
    m[3].metric("Edge cases", kinds.get("edge", 0))
    live = badge(RETRIEVAL_BACKEND, "ok" if RETRIEVAL_BACKEND == "wiki" else "neutral")
    st.markdown(
        f"Live retrieval backend: {live} (env flag RETRIEVAL_BACKEND). Set it to `wiki` to "
        f"use this backend in the live judge; evaluation uses it regardless via "
        f"replay_with_wiki.py.",
        unsafe_allow_html=True,
    )

    st.markdown("#### Try a knowledge lookup")
    st.caption("Paste a message and pick a domain; the console shows which knowledge-base "
               "entries the judge would be given — the Wiki analog of RAG's similarity search. "
               "The first lookup loads the embedding model and can take 20–40 seconds.")
    query = st.text_area("Message", placeholder="e.g. these globalists are replacing us",
                         height=80, key="wiki_query")
    domain = st.selectbox("Domain", ["Gaming", "Politics", "News", "Reviews", "General"],
                          key="wiki_domain")
    if st.button("Look up knowledge", type="primary", key="wiki_lookup"):
        if not query.strip():
            st.warning("Enter a message to look up.")
        else:
            try:
                with st.spinner("Embedding the message and selecting knowledge…"):
                    from shared_utils.wiki import retrieve_wiki
                    hits = retrieve_wiki(query.strip(), domain=domain)
            except Exception as e:
                st.error(f"Lookup failed: {e}")
                hits = []
            if not hits:
                st.info("No knowledge-base entries matched.")
            else:
                for e in hits:
                    score = "" if e.get("score") is None else f"  ·  relevance {e['score']:.2f}"
                    with st.container(border=True):
                        st.markdown(f"**[{e['kind'].upper()}] {e['title']}**{score}")
                        st.markdown(f"> {e['text'][:400]}")

    st.markdown("#### LLM-Wiki's contribution on the benchmark")
    bm = load_benchmark()
    d = labelled_benchmark(bm)
    if d.empty or "agent_final_decision_with_wiki" not in d.columns:
        st.info("No Wiki verdicts in the benchmark yet. Run "
                "`python scripts/eval/replay_with_wiki.py --csv thesis_benchmark_eval.csv --apply`.")
        return

    base_pred = variant_predictions(d, "agent_final_decision")
    wiki_pred = variant_predictions(d, "agent_final_decision_with_wiki")
    rag_pred = variant_predictions(d, "agent_final_decision_with_rag")
    if not base_pred.empty and not wiki_pred.empty:
        bf = compute_metrics(base_pred, d.loc[base_pred.index, "human_ground_truth"])["f1"]
        wf = compute_metrics(wiki_pred, d.loc[wiki_pred.index, "human_ground_truth"])["f1"]
        cc = st.columns(3)
        cc[0].metric("Tier-2 baseline — Toxic F1", f"{bf:.2f}")
        cc[1].metric("Tier-2 + LLM-Wiki — Toxic F1", f"{wf:.2f}", delta=f"{wf - bf:+.2f}")
        if not rag_pred.empty:
            rf = compute_metrics(rag_pred, d.loc[rag_pred.index, "human_ground_truth"])["f1"]
            cc[2].metric("Tier-2 + RAG — Toxic F1", f"{rf:.2f}",
                         delta=f"{wf - rf:+.2f} Wiki vs RAG")


# The live panels auto-refresh as fragments; the analytical tabs are user-driven.
st.fragment(run_every=run_every)(render_status_body)()

tab_overview, tab_live, tab_inspect, tab_eval, tab_rag, tab_wiki, tab_ma = st.tabs(
    ["Overview", "Live Monitor", "Record Inspector", "Evaluation", "RAG", "LLM-Wiki", "Multi-Agent"]
)

with tab_overview:
    st.fragment(run_every=run_every)(render_overview_body)()
with tab_live:
    st.fragment(run_every=run_every)(render_live_body)()
with tab_inspect:
    render_inspector()
with tab_eval:
    render_evaluation()
with tab_rag:
    render_rag()
with tab_wiki:
    render_wiki()
with tab_ma:
    render_multi_agent()

st.caption(f"Last refreshed {datetime.datetime.now():%H:%M:%S}. "
           "This console is read-only and does not alter the pipeline.")
